use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use ast_grep_language::SupportLang;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::query::{ApiError, find_pattern};
use crate::rules::pattern::validate_rewrite_template;
use crate::rules::rewrite::{
    RewritePlan, RewriteTarget, plan_file_rewrites, substitute_with_source,
};

pub(super) const PROPOSAL_VERSION: u32 = 1;

/// A structural relation filter supported by `find_pattern`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Relation {
    pub kind: String,
}

/// One independent rewrite rule. Rules always match the original source
/// snapshots; no rule observes another rule's replacement.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RewriteRule {
    pub id: String,
    pub language: String,
    pub pattern: String,
    pub replacement: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub inside: Option<Relation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub has: Option<Relation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub precedes: Option<Relation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub follows: Option<Relation>,
}

/// Inputs owned by the caller. `store_dir` is the final `ast-edit` proposal
/// directory, not its parent working-store directory.
#[derive(Debug, Clone)]
pub struct PreviewOptions {
    pub repository_root: PathBuf,
    pub invoking_cwd: PathBuf,
    pub paths: Vec<PathBuf>,
    pub store_dir: PathBuf,
    pub rules: Vec<RewriteRule>,
}

/// A diagnostic does not hide a skipped rule, path, or edit. Warnings leave
/// the proposal complete; blocking diagnostics prevent an applicable proposal
/// from being written.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Diagnostic {
    pub code: String,
    pub message: String,
    pub blocking: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub rule_ids: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub start_byte: Option<usize>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub end_byte: Option<usize>,
}

/// One exact replacement against the original byte snapshot.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MatchSpan {
    pub start_byte: usize,
    pub end_byte: usize,
    pub original: String,
    pub replacement: String,
    pub rule_ids: Vec<String>,
}

/// The exact before and after source for one changed file.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FileChange {
    pub path: String,
    pub language: String,
    pub original_sha256: String,
    pub replacement_sha256: String,
    pub original_content: String,
    pub replacement_content: String,
    pub match_spans: Vec<MatchSpan>,
    pub replacement_count: usize,
    pub original_error_nodes: usize,
    pub replacement_error_nodes: usize,
}

/// A complete, content-addressed proposal. `id` is SHA-256 of the serialized
/// proposal body before the `id` field is added.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Proposal {
    pub id: String,
    pub version: u32,
    pub repository_root: String,
    pub scope: Vec<String>,
    pub rules: Vec<RewriteRule>,
    pub files: Vec<FileChange>,
    pub diagnostics: Vec<Diagnostic>,
    pub complete: bool,
}

/// Result of a read-only preview. An incomplete or no-op preview has no
/// proposal paths or proposal payload.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreviewResult {
    pub complete: bool,
    pub applicable: bool,
    pub diagnostics: Vec<Diagnostic>,
    pub proposal: Option<Proposal>,
    pub diff: Option<String>,
    pub proposal_json: Option<String>,
    pub proposal_path: Option<PathBuf>,
    pub diff_path: Option<PathBuf>,
}

#[derive(Debug)]
struct Snapshot {
    path: String,
    language: SupportLang,
    source: String,
}

#[derive(Debug, Clone)]
struct Candidate {
    start_byte: usize,
    end_byte: usize,
    replacement: String,
    rule_id: String,
}

#[derive(Debug, Clone)]
struct UniqueEdit {
    start_byte: usize,
    end_byte: usize,
    original: String,
    replacement: String,
    rule_ids: Vec<String>,
}

#[derive(Serialize)]
struct ProposalBody<'a> {
    version: u32,
    repository_root: &'a str,
    scope: &'a [String],
    rules: &'a [RewriteRule],
    files: &'a [FileChange],
    diagnostics: &'a [Diagnostic],
    complete: bool,
}

/// Build a deterministic proposal from bounded paths, without writing to
/// source files. Proposal JSON and its complete unified diff are written only
/// below `options.store_dir`.
pub fn preview(options: &PreviewOptions) -> Result<PreviewResult> {
    let mut diagnostics = Vec::new();
    let root = match fs::canonicalize(&options.repository_root) {
        Ok(root) if root.is_dir() => root,
        Ok(_) => anyhow::bail!(
            "repository root is not a directory: {}",
            options.repository_root.display()
        ),
        Err(error) => anyhow::bail!(
            "cannot resolve repository root {}: {error}",
            options.repository_root.display()
        ),
    };
    let cwd = match fs::canonicalize(&options.invoking_cwd) {
        Ok(cwd) => cwd,
        Err(error) => {
            diagnostics.push(Diagnostic::blocking(
                "invalid_cwd",
                format!("cannot resolve invoking directory: {error}"),
                None,
                Vec::new(),
            ));
            return Ok(PreviewResult::incomplete(diagnostics));
        }
    };
    if options.paths.is_empty() {
        diagnostics.push(Diagnostic::blocking(
            "invalid_scope",
            "at least one explicit path scope is required",
            None,
            Vec::new(),
        ));
    }
    if options.rules.is_empty() {
        diagnostics.push(Diagnostic::blocking(
            "invalid_rules",
            "at least one rewrite rule is required",
            None,
            Vec::new(),
        ));
    }

    let (rules, rule_languages) = normalize_rules(&options.rules, &mut diagnostics);
    let (scope, snapshots) = collect_snapshots(&root, &cwd, &options.paths, &mut diagnostics);
    let mut candidates = BTreeMap::<String, Vec<Candidate>>::new();

    for (rule, language) in rules.iter().zip(rule_languages) {
        let Some(language) = language else {
            continue;
        };
        let template_valid = match validate_rewrite_template(&rule.replacement, &rule.pattern) {
            Ok(()) => true,
            Err(message) => {
                diagnostics.push(Diagnostic::blocking(
                    "invalid_rewrite_template",
                    message,
                    None,
                    vec![rule.id.clone()],
                ));
                false
            }
        };
        let relation_input = serde_json::json!({
            "inside": rule.inside,
            "has": rule.has,
            "precedes": rule.precedes,
            "follows": rule.follows,
        });
        let result = find_pattern::with_compiled_pattern(
            &language,
            &rule.pattern,
            &relation_input,
            |compiled| {
                if !template_valid {
                    return Ok(());
                }
                for snapshot in snapshots.iter().filter(|file| file.language == language) {
                    match compiled.matches_source(&snapshot.source) {
                        Ok(matches) => {
                            for matched in matches {
                                let span = &matched["span"];
                                let Some(start_byte) = span["start_byte"]
                                    .as_u64()
                                    .and_then(|n| usize::try_from(n).ok())
                                else {
                                    diagnostics.push(Diagnostic::blocking(
                                        "invalid_match_span",
                                        "matcher returned a missing or invalid start byte",
                                        Some(snapshot.path.clone()),
                                        vec![rule.id.clone()],
                                    ));
                                    continue;
                                };
                                let Some(end_byte) = span["end_byte"]
                                    .as_u64()
                                    .and_then(|n| usize::try_from(n).ok())
                                else {
                                    diagnostics.push(Diagnostic::blocking(
                                        "invalid_match_span",
                                        "matcher returned a missing or invalid end byte",
                                        Some(snapshot.path.clone()),
                                        vec![rule.id.clone()],
                                    ));
                                    continue;
                                };
                                let Some(captures) = matched.get("captures") else {
                                    diagnostics.push(Diagnostic::blocking(
                                        "invalid_match_captures",
                                        "matcher returned no capture map",
                                        Some(snapshot.path.clone()),
                                        vec![rule.id.clone()],
                                    ));
                                    continue;
                                };
                                if start_byte > end_byte
                                    || end_byte > snapshot.source.len()
                                    || !snapshot.source.is_char_boundary(start_byte)
                                    || !snapshot.source.is_char_boundary(end_byte)
                                {
                                    diagnostics.push(Diagnostic::blocking_at(
                                        "invalid_match_span",
                                        "matcher returned a span outside the UTF-8 source snapshot",
                                        Some(snapshot.path.clone()),
                                        vec![rule.id.clone()],
                                        start_byte,
                                        end_byte,
                                    ));
                                    continue;
                                }
                                let replacement = substitute_with_source(
                                    &rule.replacement,
                                    captures,
                                    Some(&snapshot.source),
                                );
                                candidates.entry(snapshot.path.clone()).or_default().push(
                                    Candidate {
                                        start_byte,
                                        end_byte,
                                        replacement,
                                        rule_id: rule.id.clone(),
                                    },
                                );
                            }
                        }
                        Err(error) => diagnostics.push(matcher_diagnostic(error, snapshot, rule)),
                    }
                }
                Ok(())
            },
        );
        if let Err(error) = result {
            diagnostics.push(Diagnostic::blocking(
                error.code,
                error.message,
                None,
                vec![rule.id.clone()],
            ));
        }
    }

    let snapshot_by_path = snapshots
        .iter()
        .map(|snapshot| (snapshot.path.as_str(), snapshot))
        .collect::<BTreeMap<_, _>>();
    let mut files = Vec::new();
    for (path, edits) in candidates {
        let Some(snapshot) = snapshot_by_path.get(path.as_str()) else {
            diagnostics.push(Diagnostic::blocking(
                "missing_snapshot",
                "matched file has no original snapshot",
                Some(path),
                Vec::new(),
            ));
            continue;
        };
        if let Some(change) = build_file_change(snapshot, edits, &mut diagnostics) {
            files.push(change);
        }
    }
    files.sort_by(|left, right| left.path.cmp(&right.path));
    diagnostics.sort_by(|left, right| {
        (
            left.path.as_deref().unwrap_or(""),
            left.code.as_str(),
            left.start_byte,
            left.end_byte,
            left.rule_ids.as_slice(),
            left.message.as_str(),
        )
            .cmp(&(
                right.path.as_deref().unwrap_or(""),
                right.code.as_str(),
                right.start_byte,
                right.end_byte,
                right.rule_ids.as_slice(),
                right.message.as_str(),
            ))
    });

    if diagnostics.iter().any(|diagnostic| diagnostic.blocking) {
        return Ok(PreviewResult::incomplete(diagnostics));
    }
    if files.is_empty() {
        return Ok(PreviewResult {
            complete: true,
            applicable: false,
            diagnostics,
            proposal: None,
            diff: None,
            proposal_json: None,
            proposal_path: None,
            diff_path: None,
        });
    }

    let scope = sort_dedup(scope);
    let root_text = path_text(&root)?;
    let mut proposal = Proposal {
        id: String::new(),
        version: PROPOSAL_VERSION,
        repository_root: root_text,
        scope,
        rules,
        files,
        diagnostics: diagnostics.clone(),
        complete: true,
    };
    proposal.id = proposal_digest(&proposal)?;
    let id = proposal.id.clone();
    let proposal_json = format!(
        "{}\n",
        serde_json::to_string_pretty(&proposal).context("serialize proposal")?
    );
    let diff = unified_diff(&proposal.files);
    create_private_store(&options.store_dir)
        .with_context(|| format!("create proposal store {}", options.store_dir.display()))?;
    let proposal_path = options.store_dir.join(format!("{id}.json"));
    let diff_path = options.store_dir.join(format!("{id}.diff"));
    write_private_file(&proposal_path, &proposal_json)
        .with_context(|| format!("write proposal {}", proposal_path.display()))?;
    write_private_file(&diff_path, &diff)
        .with_context(|| format!("write diff {}", diff_path.display()))?;

    Ok(PreviewResult {
        complete: true,
        applicable: true,
        diagnostics,
        proposal: Some(proposal),
        diff: Some(diff),
        proposal_json: Some(proposal_json),
        proposal_path: Some(proposal_path),
        diff_path: Some(diff_path),
    })
}

impl Diagnostic {
    fn blocking(
        code: impl Into<String>,
        message: impl Into<String>,
        path: Option<String>,
        rule_ids: Vec<String>,
    ) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            blocking: true,
            path,
            rule_ids,
            start_byte: None,
            end_byte: None,
        }
    }

    fn warning(code: impl Into<String>, message: impl Into<String>, path: String) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            blocking: false,
            path: Some(path),
            rule_ids: Vec::new(),
            start_byte: None,
            end_byte: None,
        }
    }

    fn blocking_at(
        code: impl Into<String>,
        message: impl Into<String>,
        path: Option<String>,
        rule_ids: Vec<String>,
        start_byte: usize,
        end_byte: usize,
    ) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            blocking: true,
            path,
            rule_ids,
            start_byte: Some(start_byte),
            end_byte: Some(end_byte),
        }
    }
}

impl PreviewResult {
    fn incomplete(diagnostics: Vec<Diagnostic>) -> Self {
        Self {
            complete: false,
            applicable: false,
            diagnostics,
            proposal: None,
            diff: None,
            proposal_json: None,
            proposal_path: None,
            diff_path: None,
        }
    }
}

fn normalize_rules(
    input: &[RewriteRule],
    diagnostics: &mut Vec<Diagnostic>,
) -> (Vec<RewriteRule>, Vec<Option<SupportLang>>) {
    let mut rules = input.to_vec();
    rules.sort_by(|left, right| {
        (&left.id, &left.language, &left.pattern, &left.replacement).cmp(&(
            &right.id,
            &right.language,
            &right.pattern,
            &right.replacement,
        ))
    });
    let mut seen = BTreeSet::new();
    let mut languages = Vec::with_capacity(rules.len());
    for rule in &mut rules {
        if rule.id.trim().is_empty() {
            diagnostics.push(Diagnostic::blocking(
                "invalid_rule_id",
                "rewrite rule id must not be empty",
                None,
                Vec::new(),
            ));
        } else if !seen.insert(rule.id.clone()) {
            diagnostics.push(Diagnostic::blocking(
                "duplicate_rule_id",
                format!("rewrite rule id {:?} is used more than once", rule.id),
                None,
                vec![rule.id.clone()],
            ));
        }
        let input = serde_json::json!({ "language": rule.language });
        match find_pattern::resolve_lang(&input, None) {
            Ok(language) => {
                rule.language = language.to_string();
                languages.push(Some(language));
            }
            Err(error) => {
                diagnostics.push(Diagnostic::blocking(
                    error.code,
                    error.message,
                    None,
                    vec![rule.id.clone()],
                ));
                languages.push(None);
            }
        }
    }
    (rules, languages)
}

fn collect_snapshots(
    root: &Path,
    cwd: &Path,
    scopes: &[PathBuf],
    diagnostics: &mut Vec<Diagnostic>,
) -> (Vec<String>, Vec<Snapshot>) {
    let mut scope_names = Vec::new();
    let mut paths = BTreeMap::<String, PathBuf>::new();
    for scope in scopes {
        let target = if scope.is_absolute() {
            scope.clone()
        } else {
            cwd.join(scope)
        };
        let canonical = match validate_target_path(&target, root) {
            Ok(path) => path,
            Err(message) => {
                diagnostics.push(Diagnostic::blocking(
                    "unsafe_path",
                    message,
                    Some(path_text_lossy(&target)),
                    Vec::new(),
                ));
                continue;
            }
        };
        let relative = match canonical.strip_prefix(root).ok().and_then(path_text_opt) {
            Some(path) if !path.is_empty() => path,
            Some(_) => ".".to_string(),
            None => {
                diagnostics.push(Diagnostic::blocking(
                    "unsafe_path",
                    "scope path cannot be represented relative to repository root",
                    Some(path_text_lossy(&canonical)),
                    Vec::new(),
                ));
                continue;
            }
        };
        scope_names.push(relative);
        if canonical.is_file() {
            if let Some(path) = relative_path(root, &canonical, diagnostics) {
                paths.insert(path, canonical);
            }
        } else if canonical.is_dir() {
            for entry in ignore::WalkBuilder::new(&canonical)
                .hidden(false)
                .filter_entry(|entry| !crate::scan::is_vcs_internal(entry))
                .build()
            {
                match entry {
                    Ok(entry) => {
                        let path = entry.path();
                        match validate_walk_entry(path, root) {
                            Ok(Some(canonical_file)) => {
                                if !canonical_file.is_file() {
                                    continue;
                                }
                                if let Some(relative) =
                                    relative_path(root, &canonical_file, diagnostics)
                                {
                                    paths.insert(relative, canonical_file);
                                }
                            }
                            Ok(None) => {}
                            Err(message) => diagnostics.push(Diagnostic::blocking(
                                "unsafe_path",
                                message,
                                Some(path_text_lossy(path)),
                                Vec::new(),
                            )),
                        }
                    }
                    Err(error) => diagnostics.push(Diagnostic::blocking(
                        "scope_walk_error",
                        format!("cannot traverse scoped path: {error}"),
                        walk_error_path(&error).map(path_text_lossy),
                        Vec::new(),
                    )),
                }
            }
        } else {
            diagnostics.push(Diagnostic::blocking(
                "invalid_scope",
                "path scope is neither a regular file nor a directory",
                Some(path_text_lossy(&canonical)),
                Vec::new(),
            ));
        }
    }

    let mut snapshots = Vec::new();
    for (path, absolute_path) in paths {
        let language_input = serde_json::json!({});
        let language = match find_pattern::resolve_lang(&language_input, Some(&absolute_path)) {
            Ok(language) => language,
            Err(error) => {
                diagnostics.push(Diagnostic::warning(
                    "unsupported_file_type",
                    error.message,
                    path,
                ));
                continue;
            }
        };
        let bytes = match fs::read(&absolute_path) {
            Ok(bytes) => bytes,
            Err(error) => {
                diagnostics.push(Diagnostic::blocking(
                    "unreadable_file",
                    format!("cannot read source snapshot: {error}"),
                    Some(path),
                    Vec::new(),
                ));
                continue;
            }
        };
        let source = match String::from_utf8(bytes) {
            Ok(source) => source,
            Err(error) => {
                diagnostics.push(Diagnostic::blocking(
                    "unreadable_file",
                    format!("source is not valid UTF-8: {error}"),
                    Some(path),
                    Vec::new(),
                ));
                continue;
            }
        };
        snapshots.push(Snapshot {
            path,
            language,
            source,
        });
    }
    snapshots.sort_by(|left, right| left.path.cmp(&right.path));
    (sort_dedup(scope_names), snapshots)
}

fn validate_target_path(target: &Path, root: &Path) -> std::result::Result<PathBuf, String> {
    let metadata = fs::symlink_metadata(target)
        .map_err(|error| format!("cannot inspect path {}: {error}", target.display()))?;
    if metadata.file_type().is_symlink() {
        return Err(format!(
            "final path component is a symlink: {}",
            target.display()
        ));
    }
    verify_ancestors_inside(target, root)?;
    let canonical = fs::canonicalize(target)
        .map_err(|error| format!("cannot resolve path {}: {error}", target.display()))?;
    if !canonical.starts_with(root) {
        return Err(format!(
            "resolved path escapes repository root: {}",
            target.display()
        ));
    }
    Ok(canonical)
}

fn walk_error_path(error: &ignore::Error) -> Option<&Path> {
    match error {
        ignore::Error::WithPath { path, .. } => Some(path),
        ignore::Error::WithDepth { err, .. } | ignore::Error::WithLineNumber { err, .. } => {
            walk_error_path(err)
        }
        ignore::Error::Loop { child, .. } => Some(child),
        ignore::Error::Partial(errors) => errors.iter().find_map(walk_error_path),
        _ => None,
    }
}

fn validate_walk_entry(path: &Path, root: &Path) -> std::result::Result<Option<PathBuf>, String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("cannot inspect scoped entry {}: {error}", path.display()))?;
    if metadata.file_type().is_symlink() {
        return Err(format!(
            "scoped path component is a symlink: {}",
            path.display()
        ));
    }
    verify_ancestors_inside(path, root)?;
    let canonical = fs::canonicalize(path)
        .map_err(|error| format!("cannot resolve scoped entry {}: {error}", path.display()))?;
    if !canonical.starts_with(root) {
        return Err(format!(
            "resolved scoped entry escapes repository root: {}",
            path.display()
        ));
    }
    Ok(Some(canonical))
}

fn verify_ancestors_inside(path: &Path, root: &Path) -> std::result::Result<(), String> {
    let mut current = path.parent();
    let mut entered_root = false;
    while let Some(parent) = current {
        let canonical = fs::canonicalize(parent)
            .map_err(|error| format!("cannot resolve path parent {}: {error}", parent.display()))?;
        if canonical.starts_with(root) {
            entered_root = true;
        } else if entered_root {
            return Err(format!(
                "path parent resolves outside repository root: {}",
                parent.display()
            ));
        }
        if canonical == root {
            break;
        }
        current = parent.parent();
    }
    Ok(())
}

fn relative_path(root: &Path, path: &Path, diagnostics: &mut Vec<Diagnostic>) -> Option<String> {
    match path.strip_prefix(root).ok().and_then(path_text_opt) {
        Some(path) => Some(path),
        None => {
            diagnostics.push(Diagnostic::blocking(
                "invalid_path_encoding",
                "scoped path cannot be represented as a UTF-8 repository-relative path",
                Some(path_text_lossy(path)),
                Vec::new(),
            ));
            None
        }
    }
}

fn path_text(path: &Path) -> Result<String> {
    path.to_str()
        .map(str::to_string)
        .context("path is not valid UTF-8")
}

fn path_text_opt(path: &Path) -> Option<String> {
    path.to_str().map(|value| value.replace('\\', "/"))
}

fn path_text_lossy(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

fn sort_dedup<T: Ord>(mut values: Vec<T>) -> Vec<T> {
    values.sort();
    values.dedup();
    values
}

fn matcher_diagnostic(error: ApiError, snapshot: &Snapshot, rule: &RewriteRule) -> Diagnostic {
    Diagnostic::blocking(
        error.code,
        error.message,
        Some(snapshot.path.clone()),
        vec![rule.id.clone()],
    )
}

fn build_file_change(
    snapshot: &Snapshot,
    candidates: Vec<Candidate>,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<FileChange> {
    let mut grouped = BTreeMap::<(usize, usize, String), BTreeSet<String>>::new();
    for candidate in candidates {
        grouped
            .entry((
                candidate.start_byte,
                candidate.end_byte,
                candidate.replacement,
            ))
            .or_default()
            .insert(candidate.rule_id);
    }
    let mut edits = Vec::with_capacity(grouped.len());
    for ((start_byte, end_byte, replacement), rule_ids) in grouped {
        if start_byte > end_byte
            || end_byte > snapshot.source.len()
            || !snapshot.source.is_char_boundary(start_byte)
            || !snapshot.source.is_char_boundary(end_byte)
        {
            diagnostics.push(Diagnostic::blocking_at(
                "invalid_match_span",
                "rewrite span is outside the UTF-8 source snapshot",
                Some(snapshot.path.clone()),
                rule_ids.into_iter().collect(),
                start_byte,
                end_byte,
            ));
            continue;
        }
        edits.push(UniqueEdit {
            start_byte,
            end_byte,
            original: snapshot.source[start_byte..end_byte].to_string(),
            replacement,
            rule_ids: rule_ids.into_iter().collect(),
        });
    }
    edits.sort_by(|left, right| {
        (
            left.start_byte,
            left.end_byte,
            &left.replacement,
            &left.rule_ids,
        )
            .cmp(&(
                right.start_byte,
                right.end_byte,
                &right.replacement,
                &right.rule_ids,
            ))
    });
    let targets = edits
        .iter()
        .map(|edit| {
            Ok(RewriteTarget {
                start_byte: u32::try_from(edit.start_byte).context("rewrite start exceeds u32")?,
                end_byte: u32::try_from(edit.end_byte).context("rewrite end exceeds u32")?,
                replacement: edit.replacement.clone(),
            })
        })
        .collect::<Result<Vec<_>>>();
    let targets = match targets {
        Ok(targets) => targets,
        Err(error) => {
            diagnostics.push(Diagnostic::blocking(
                "invalid_match_span",
                format!("cannot plan rewrite span: {error:#}"),
                Some(snapshot.path.clone()),
                edits
                    .iter()
                    .flat_map(|edit| edit.rule_ids.clone())
                    .collect(),
            ));
            return None;
        }
    };
    let plans = plan_file_rewrites(&targets);
    if plans.contains(&RewritePlan::SkippedOverlap) {
        let mut reported = BTreeSet::new();
        for (index, plan) in plans.iter().enumerate() {
            if *plan != RewritePlan::SkippedOverlap {
                continue;
            }
            for (other_index, other) in edits.iter().enumerate() {
                if index == other_index || !spans_overlap(&edits[index], other) {
                    continue;
                }
                let mut rule_ids = edits[index]
                    .rule_ids
                    .iter()
                    .chain(other.rule_ids.iter())
                    .cloned()
                    .collect::<Vec<_>>();
                rule_ids.sort();
                rule_ids.dedup();
                let key = (
                    edits[index].start_byte,
                    edits[index].end_byte,
                    rule_ids.clone(),
                );
                if reported.insert(key) {
                    diagnostics.push(Diagnostic::blocking_at(
                        "overlapping_edits",
                        format!(
                            "rewrite spans overlap ({}..{} and {}..{})",
                            edits[index].start_byte,
                            edits[index].end_byte,
                            other.start_byte,
                            other.end_byte
                        ),
                        Some(snapshot.path.clone()),
                        rule_ids,
                        edits[index].start_byte.min(other.start_byte),
                        edits[index].end_byte.max(other.end_byte),
                    ));
                }
            }
        }
        return None;
    }

    let mut replacement_content = snapshot.source.clone();
    for edit in edits.iter().rev() {
        replacement_content.replace_range(edit.start_byte..edit.end_byte, &edit.replacement);
    }
    if replacement_content == snapshot.source {
        return None;
    }
    let original_error_nodes = syntax_error_count(snapshot.language, &snapshot.source);
    let replacement_error_nodes = syntax_error_count(snapshot.language, &replacement_content);
    if replacement_error_nodes > original_error_nodes {
        diagnostics.push(Diagnostic::blocking(
            "rewrite_added_syntax_errors",
            format!(
                "rewrite adds syntax-tree ERROR/MISSING nodes ({} before, {} after)",
                original_error_nodes, replacement_error_nodes
            ),
            Some(snapshot.path.clone()),
            edits
                .iter()
                .flat_map(|edit| edit.rule_ids.clone())
                .collect(),
        ));
        return None;
    }
    if original_error_nodes > 0 {
        diagnostics.push(Diagnostic::warning(
            "preexisting_syntax_errors",
            format!(
                "source already contains {original_error_nodes} ERROR/MISSING syntax-tree nodes; rewrite adds none"
            ),
            snapshot.path.clone(),
        ));
    }
    Some(FileChange {
        path: snapshot.path.clone(),
        language: snapshot.language.to_string(),
        original_sha256: sha256(snapshot.source.as_bytes()),
        replacement_sha256: sha256(replacement_content.as_bytes()),
        original_content: snapshot.source.clone(),
        replacement_content,
        match_spans: edits
            .into_iter()
            .map(|edit| MatchSpan {
                start_byte: edit.start_byte,
                end_byte: edit.end_byte,
                original: edit.original,
                replacement: edit.replacement,
                rule_ids: edit.rule_ids,
            })
            .collect(),
        replacement_count: targets.len(),
        original_error_nodes,
        replacement_error_nodes,
    })
}

fn spans_overlap(left: &UniqueEdit, right: &UniqueEdit) -> bool {
    left.start_byte < right.end_byte && right.start_byte < left.end_byte
}

fn syntax_error_count(language: SupportLang, source: &str) -> usize {
    crate::parse::parse_source(&language, source)
        .root
        .root()
        .dfs()
        .filter(|node| node.is_error() || node.is_missing())
        .count()
}

pub(super) fn proposal_digest(proposal: &Proposal) -> Result<String> {
    let body = ProposalBody {
        version: proposal.version,
        repository_root: &proposal.repository_root,
        scope: &proposal.scope,
        rules: &proposal.rules,
        files: &proposal.files,
        diagnostics: &proposal.diagnostics,
        complete: proposal.complete,
    };
    let body = serde_json::to_vec(&body).context("serialize proposal body")?;
    Ok(sha256(&body))
}

pub(super) fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn create_private_store(path: &Path) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;

        let mut builder = fs::DirBuilder::new();
        builder.recursive(true).mode(0o700).create(path)
    }
    #[cfg(not(unix))]
    {
        fs::create_dir_all(path)
    }
}

fn write_private_file(path: &Path, contents: &str) -> std::io::Result<()> {
    let mut options = fs::OpenOptions::new();
    options.write(true).create(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        file.set_permissions(fs::Permissions::from_mode(0o600))?;
    }
    file.set_len(0)?;
    file.write_all(contents.as_bytes())
}

fn unified_diff(files: &[FileChange]) -> String {
    let mut output = String::new();
    for file in files {
        let from = format!("a/{}", file.path);
        let to = format!("b/{}", file.path);
        output.push_str(
            &similar::TextDiff::from_lines(&file.original_content, &file.replacement_content)
                .unified_diff()
                .header(&from, &to)
                .to_string(),
        );
    }
    output
}

#[cfg(test)]
mod tests {
    use super::sha256;

    #[test]
    fn sha256_uses_standard_lowercase_hex() {
        assert_eq!(
            sha256(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
}
