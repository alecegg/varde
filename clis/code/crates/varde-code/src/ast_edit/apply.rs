//! Guarded application of an exact AST edit proposal.

use std::collections::HashSet;
use std::fs;
use std::path::{Component, Path, PathBuf};

use super::Proposal;
use super::preview::{FileChange, PROPOSAL_VERSION, proposal_digest, sha256};
use anyhow::{Context, Result, bail};

/// Inputs required to apply a proposal to its original repository.
#[derive(Debug, Clone)]
pub struct ApplyOptions {
    pub repository_root: PathBuf,
}

/// Outcome of attempting to write one proposal file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ApplyStatus {
    Applied,
    SourceChanged { message: String },
    WriteFailed { message: String },
}

/// The path and outcome for one file in the proposal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApplyFileResult {
    pub path: String,
    pub status: ApplyStatus,
}

impl ApplyFileResult {
    /// Whether the saved replacement bytes were written for this file.
    pub fn is_applied(&self) -> bool {
        matches!(self.status, ApplyStatus::Applied)
    }
}

/// Per-file results. A write failure may leave earlier files applied and
/// later files untouched; this result makes each outcome explicit.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApplyResult {
    pub proposal_id: String,
    pub files: Vec<ApplyFileResult>,
}

struct PreparedFile<'a> {
    change: &'a FileChange,
    relative_path: PathBuf,
    canonical_path: PathBuf,
}

/// Apply the saved replacement bytes after validating the complete proposal
/// and every source snapshot. This performs no Git checks and never changes
/// the Git index.
pub fn apply(proposal: &Proposal, options: &ApplyOptions) -> Result<ApplyResult> {
    let root = fs::canonicalize(&options.repository_root).with_context(|| {
        format!(
            "cannot resolve repository root {}",
            options.repository_root.display()
        )
    })?;
    if !root.is_dir() {
        bail!("repository root is not a directory: {}", root.display());
    }
    let root_text = root
        .to_str()
        .context("canonical repository root is not valid UTF-8")?;
    if proposal.repository_root != root_text {
        bail!(
            "proposal repository root does not match canonical repository root {}",
            root.display()
        );
    }
    if proposal.version != PROPOSAL_VERSION {
        bail!(
            "unsupported AST edit proposal version {} (expected {})",
            proposal.version,
            PROPOSAL_VERSION
        );
    }
    if !proposal.complete || proposal.files.is_empty() {
        bail!("proposal is incomplete or contains no file changes");
    }
    if proposal
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.blocking)
    {
        bail!("proposal contains blocking diagnostics");
    }
    for scope in &proposal.scope {
        validate_scope_path(scope)?;
    }

    let rule_ids = proposal
        .rules
        .iter()
        .map(|rule| rule.id.as_str())
        .collect::<HashSet<_>>();
    let mut seen_paths = HashSet::new();
    for change in &proposal.files {
        validate_relative_path(&change.path)?;
        if !seen_paths.insert(change.path.as_str()) {
            bail!("proposal contains duplicate file path {:?}", change.path);
        }
        let change_path = Path::new(&change.path);
        if !proposal
            .scope
            .iter()
            .any(|scope| scope == "." || change_path.starts_with(Path::new(scope)))
        {
            bail!(
                "proposal file path {:?} is not in its recorded scope",
                change.path
            );
        }
        if sha256(change.original_content.as_bytes()) != change.original_sha256 {
            bail!("original payload digest does not match for {}", change.path);
        }
        if sha256(change.replacement_content.as_bytes()) != change.replacement_sha256 {
            bail!(
                "replacement payload digest does not match for {}",
                change.path
            );
        }
        validate_spans(change, &rule_ids)?;
    }
    let expected_id = proposal_digest(proposal)?;
    if proposal.id != expected_id {
        bail!("proposal body digest does not match its id");
    }

    // Finish every path and snapshot check before the first write. A stale or
    // unsafe later file therefore cannot leave an earlier file partially
    // applied.
    let mut prepared = Vec::with_capacity(proposal.files.len());
    for change in &proposal.files {
        let relative_path = PathBuf::from(&change.path);
        let canonical_path = resolve_target(&root, &relative_path)?;
        let current = fs::read(&canonical_path)
            .with_context(|| format!("read proposal target {}", change.path))?;
        if current != change.original_content.as_bytes()
            || sha256(&current) != change.original_sha256
        {
            bail!("original snapshot identity changed for {}", change.path);
        }
        prepared.push(PreparedFile {
            change,
            relative_path,
            canonical_path,
        });
    }

    let mut files = Vec::with_capacity(prepared.len());
    for target in prepared {
        let current_path = match resolve_target(&root, &target.relative_path) {
            Ok(path) if path == target.canonical_path => path,
            Ok(_) => {
                files.push(source_changed(
                    target.change,
                    "target path resolved to a different file after preflight",
                ));
                continue;
            }
            Err(error) => {
                files.push(source_changed(
                    target.change,
                    &format!("target path failed its pre-write check: {error:#}"),
                ));
                continue;
            }
        };
        let current = match fs::read(&current_path) {
            Ok(current) => current,
            Err(error) => {
                files.push(source_changed(
                    target.change,
                    &format!("cannot re-read original source before write: {error}"),
                ));
                continue;
            }
        };
        if current != target.change.original_content.as_bytes()
            || sha256(&current) != target.change.original_sha256
        {
            files.push(source_changed(
                target.change,
                "original snapshot changed after preflight",
            ));
            continue;
        }
        let status = match crate::scan_cli::write_atomic(
            &current_path,
            &target.change.replacement_content,
        ) {
            Ok(()) => ApplyStatus::Applied,
            Err(error) => ApplyStatus::WriteFailed {
                message: error.to_string(),
            },
        };
        files.push(ApplyFileResult {
            path: target.change.path.clone(),
            status,
        });
    }

    Ok(ApplyResult {
        proposal_id: proposal.id.clone(),
        files,
    })
}

fn source_changed(change: &FileChange, message: &str) -> ApplyFileResult {
    ApplyFileResult {
        path: change.path.clone(),
        status: ApplyStatus::SourceChanged {
            message: message.to_owned(),
        },
    }
}

fn validate_relative_path(path: &str) -> Result<()> {
    let relative = Path::new(path);
    if path.is_empty()
        || relative.is_absolute()
        || relative
            .components()
            .any(|component| !matches!(component, Component::Normal(_)))
    {
        bail!("proposal path must be a clean relative repository path: {path:?}");
    }
    Ok(())
}

fn validate_scope_path(path: &str) -> Result<()> {
    if path != "." {
        validate_relative_path(path)?;
    }
    Ok(())
}

fn resolve_target(root: &Path, relative_path: &Path) -> Result<PathBuf> {
    let path = root.join(relative_path);
    let metadata = fs::symlink_metadata(&path)
        .with_context(|| format!("inspect proposal target {}", path.display()))?;
    if metadata.file_type().is_symlink() {
        bail!(
            "proposal target final path component is a symlink: {}",
            path.display()
        );
    }
    if !metadata.is_file() {
        bail!("proposal target is not a regular file: {}", path.display());
    }

    let parent = path
        .parent()
        .context("proposal target has no parent directory")?;
    let canonical_parent = fs::canonicalize(parent)
        .with_context(|| format!("resolve proposal target parent {}", parent.display()))?;
    if !canonical_parent.starts_with(root) {
        bail!(
            "proposal target parent resolves outside the repository: {}",
            parent.display()
        );
    }

    let canonical_path = fs::canonicalize(&path)
        .with_context(|| format!("resolve proposal target {}", path.display()))?;
    if !canonical_path.starts_with(root) {
        bail!(
            "proposal target resolves outside the repository: {}",
            path.display()
        );
    }
    Ok(canonical_path)
}

fn validate_spans(change: &FileChange, rule_ids: &HashSet<&str>) -> Result<()> {
    if change.match_spans.is_empty() || change.match_spans.len() != change.replacement_count {
        bail!("invalid match span count for {}", change.path);
    }

    let mut reconstructed = String::with_capacity(change.replacement_content.len());
    let mut cursor = 0;
    for span in &change.match_spans {
        if span.start_byte < cursor || span.start_byte >= span.end_byte {
            bail!("invalid or overlapping match span for {}", change.path);
        }
        let original = change
            .original_content
            .get(span.start_byte..span.end_byte)
            .with_context(|| format!("match span is not on UTF-8 boundaries in {}", change.path))?;
        if original != span.original {
            bail!("match span original text does not match {}", change.path);
        }
        if span.rule_ids.is_empty()
            || span
                .rule_ids
                .iter()
                .any(|id| !rule_ids.contains(id.as_str()))
        {
            bail!("match span has invalid rule provenance in {}", change.path);
        }
        reconstructed.push_str(&change.original_content[cursor..span.start_byte]);
        reconstructed.push_str(&span.replacement);
        cursor = span.end_byte;
    }
    reconstructed.push_str(&change.original_content[cursor..]);
    if reconstructed != change.replacement_content {
        bail!(
            "match spans do not produce the saved replacement for {}",
            change.path
        );
    }
    Ok(())
}
