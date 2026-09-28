//! Recoverable staged filesystem writes.

use crate::review_gates;
use crate::review_lock::ProjectLock;
use anyhow::{Context, Result, anyhow, bail};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use varde_workflow_core::memory::MemoryPaths;

const JOURNAL_NAME: &str = ".varde-workflow-journal.json";
const CONCLUSION_JOURNAL_NAME: &str = ".varde-workflow-conclusion.json";

#[derive(Debug)]
pub struct JournalConflict(pub String);

impl std::fmt::Display for JournalConflict {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for JournalConflict {}

pub fn conflict_message(error: &anyhow::Error) -> Option<&str> {
    error
        .downcast_ref::<JournalConflict>()
        .map(|error| error.0.as_str())
}

fn conflict(message: impl Into<String>) -> anyhow::Error {
    anyhow!(JournalConflict(message.into()))
}

#[derive(Debug)]
pub struct PendingWrite {
    pub target: PathBuf,
    pub content: Vec<u8>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ExpectedSource {
    pub path: PathBuf,
    pub revision: Option<String>,
    #[serde(default)]
    pub inventory: Option<GitInventory>,
    #[serde(default)]
    pub identity: Option<FileIdentity>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct FileIdentity {
    pub entry_type: String,
    pub mode: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct DirectoryCheckpoint {
    path: PathBuf,
    identity: FileIdentity,
}

#[derive(Debug)]
struct DirectoryPlan {
    create: Vec<PathBuf>,
    existing: Vec<DirectoryCheckpoint>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct GitInventory {
    pub roots: Vec<String>,
    pub paths: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReviewCheckpoint {
    pub repository_root: PathBuf,
    pub plan_path: PathBuf,
    pub checkpoint: String,
    pub prerequisites: review_gates::ReviewPrerequisites,
}

pub fn expected_git_inventory(root: &Path, roots: &[String]) -> Result<ExpectedSource> {
    let root = root.canonicalize()?;
    Ok(ExpectedSource {
        path: root.clone(),
        revision: None,
        inventory: Some(GitInventory {
            roots: roots.to_vec(),
            paths: git_inventory_paths(&root, roots)?,
        }),
        identity: None,
    })
}

pub fn expected_source_from_bytes(path: &Path, bytes: &[u8]) -> Result<ExpectedSource> {
    let path = varde_workflow_core::memory::canonical_or_lexical(path);
    Ok(ExpectedSource {
        path: path.clone(),
        revision: Some(varde_workflow_core::occ::version(bytes)),
        inventory: None,
        identity: file_identity(&path)?,
    })
}

pub fn expected_source_at(path: &Path) -> Result<ExpectedSource> {
    let path = varde_workflow_core::memory::canonical_or_lexical(path);
    let bytes = match fs::read(&path) {
        Ok(bytes) => Some(bytes),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(error) => return Err(error.into()),
    };
    Ok(ExpectedSource {
        path: path.clone(),
        revision: bytes.as_deref().map(varde_workflow_core::occ::version),
        inventory: None,
        identity: file_identity(&path)?,
    })
}

pub fn file_identity(path: &Path) -> Result<Option<FileIdentity>> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let file_type = metadata.file_type();
    let entry_type = if file_type.is_symlink() {
        "symlink"
    } else if file_type.is_file() {
        "file"
    } else if file_type.is_dir() {
        "directory"
    } else {
        "special"
    };
    #[cfg(unix)]
    let mode = {
        use std::os::unix::fs::PermissionsExt;
        Some(metadata.permissions().mode() & 0o7777)
    };
    #[cfg(not(unix))]
    let mode = None;
    Ok(Some(FileIdentity {
        entry_type: entry_type.to_string(),
        mode,
    }))
}

fn git_inventory_paths(root: &Path, roots: &[String]) -> Result<Vec<String>> {
    let output = Command::new("git")
        .args([
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ])
        .current_dir(root)
        .output()
        .with_context(|| {
            format!(
                "failed to list workflow prerequisites in {}",
                root.display()
            )
        })?;
    if !output.status.success() {
        bail!(
            "failed to list workflow prerequisites in {}",
            root.display()
        );
    }
    let mut paths = BTreeSet::new();
    for raw in output
        .stdout
        .split(|byte| *byte == 0)
        .filter(|raw| !raw.is_empty())
    {
        let relative = std::str::from_utf8(raw).context("non-UTF-8 workflow prerequisite path")?;
        if roots
            .iter()
            .any(|scope| relative == scope || relative.starts_with(&format!("{scope}/")))
            && root.join(relative).is_file()
        {
            paths.insert(relative.to_string());
        }
    }
    Ok(paths.into_iter().collect())
}

pub fn checkpoint(
    repository_root: &Path,
    plan_path: &Path,
    checkpoint: &str,
    report: &review_gates::CheckReport,
) -> Result<ReviewCheckpoint> {
    if !report.ready || report.consumed.subject_id.is_empty() {
        bail!("cannot journal an unapproved review checkpoint");
    }
    Ok(ReviewCheckpoint {
        repository_root: repository_root.canonicalize()?,
        plan_path: plan_path.canonicalize()?,
        checkpoint: checkpoint.to_string(),
        prerequisites: report.consumed.clone(),
    })
}

pub fn commit_expected_guarded(
    lock: &ProjectLock,
    target: &Path,
    content: &[u8],
    expected_revision: &str,
    sources: &[ExpectedSource],
    review: Option<&ReviewCheckpoint>,
) -> Result<()> {
    reject_pending_project_journals(lock.root())?;
    let target = target.canonicalize()?;
    let memory = MemoryPaths::resolve(lock.root())?;
    let write_roots = memory.write_roots();
    if !write_roots.iter().any(|root| target.starts_with(root)) {
        bail!("workflow target is outside the locked project write roots");
    }
    let current = varde_workflow_core::occ::version(&fs::read(&target)?);
    if current != expected_revision {
        return Err(conflict("workflow target changed before staged write"));
    }
    let source = sources
        .iter()
        .find(|source| source.path == target)
        .context("workflow target was not captured before staged write")?;
    if source.revision.as_deref() != Some(expected_revision) {
        return Err(conflict(
            "workflow target source revision does not match the consumed artifact",
        ));
    }
    validate_sources(sources, None)?;
    validate_review(review, &[], &[])?;
    let stage = stage_bytes(&target, content)?;
    let staged_identity = file_identity(&stage)?;
    let journal_path = lock.root().join(JOURNAL_NAME);
    let journal = json!({
        "version": 2,
        "phase": "staged",
        "repository_root": lock.root(),
        "write_roots": write_roots,
        "subject_id": review.map(|value| value.prerequisites.subject_id.as_str()),
        "target": target,
        "staging": stage,
        "source_hash": expected_revision,
        "target_hash": varde_workflow_core::occ::version(content),
        "source_identity": &source.identity,
        "target_identity": staged_identity,
        "sources": sources,
        "review_checkpoint": review,
        "recovery_action": "commit",
    });
    fs::write(&journal_path, serde_json::to_vec_pretty(&journal)?)?;
    if std::env::var_os("VARDE_WORKFLOW_FAIL_AFTER_STAGE").is_some() {
        bail!("injected interruption after staging");
    }
    validate_sources(sources, None)?;
    validate_review(review, &[], &[])?;
    fs::rename(&stage, &target)?;
    fs::remove_file(journal_path)?;
    Ok(())
}

fn stage_bytes(target: &Path, content: &[u8]) -> Result<PathBuf> {
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let permissions = match fs::metadata(target) {
        Ok(metadata) => Some(metadata.permissions()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(error) => return Err(error.into()),
    };
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    for _ in 0..64 {
        let nonce = NEXT.fetch_add(1, Ordering::Relaxed);
        let stage = target.with_extension(format!("md.varde-stage-{}{nonce}", std::process::id(),));
        match options.open(&stage) {
            Ok(mut file) => {
                // Keep the incomplete stage private, then restore the target's
                // permissions before callers capture its recovery identity.
                let result = file.write_all(content).and_then(|()| {
                    if let Some(permissions) = &permissions {
                        file.set_permissions(permissions.clone())?;
                    }
                    Ok(())
                });
                if let Err(error) = result {
                    let _ = fs::remove_file(&stage);
                    return Err(error.into());
                }
                return Ok(stage);
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        }
    }
    bail!("could not allocate a unique workflow staging path")
}

fn validate_sources(sources: &[ExpectedSource], except: Option<&Path>) -> Result<()> {
    let except = except
        .into_iter()
        .map(Path::to_path_buf)
        .collect::<Vec<_>>();
    validate_sources_except(sources, &except)
}

fn validate_sources_except(sources: &[ExpectedSource], except: &[PathBuf]) -> Result<()> {
    for expected in sources {
        if except.iter().any(|path| path == &expected.path) {
            continue;
        }
        if let Some(inventory) = &expected.inventory {
            let actual = git_inventory_paths(&expected.path, &inventory.roots)?;
            if actual != inventory.paths {
                return Err(conflict(format!(
                    "workflow prerequisite inventory changed: {}",
                    expected.path.display()
                )));
            }
            continue;
        }
        if file_identity(&expected.path)? != expected.identity {
            return Err(conflict(format!(
                "workflow prerequisite type or mode changed: {}",
                expected.path.display()
            )));
        }
        let actual = match fs::read(&expected.path) {
            Ok(bytes) => Some(varde_workflow_core::occ::version(&bytes)),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
            Err(error) => return Err(error.into()),
        };
        if actual != expected.revision {
            return Err(conflict(format!(
                "workflow prerequisite changed: {}",
                expected.path.display()
            )));
        }
    }
    Ok(())
}

fn identity_matches(path: &Path, expected: Option<&FileIdentity>) -> Result<bool> {
    Ok(file_identity(path)?.as_ref() == expected)
}

fn legacy_identity_matches(path: &Path, expected: Option<&FileIdentity>) -> Result<bool> {
    match expected {
        Some(expected) => Ok(file_identity(path)?.as_ref() == Some(expected)),
        None => Ok(true),
    }
}

fn identity_matches_for_journal(
    path: &Path,
    expected: Option<&FileIdentity>,
    version: u64,
) -> Result<bool> {
    if version == 1 {
        legacy_identity_matches(path, expected)
    } else {
        identity_matches(path, expected)
    }
}

pub fn validate_expected_sources(sources: &[ExpectedSource]) -> Result<()> {
    validate_sources(sources, None)
}

fn validate_review(
    review: Option<&ReviewCheckpoint>,
    applied_targets: &[PathBuf],
    created_directories: &[DirectoryCheckpoint],
) -> Result<()> {
    let Some(review) = review else { return Ok(()) };
    let current = review_gates::check_plan(
        &review.repository_root,
        &review.plan_path,
        &review.checkpoint,
    )
    .map_err(|error| conflict(format!("review checkpoint prerequisite changed: {error}")))?;
    let has_transaction_exceptions = !applied_targets.is_empty() || !created_directories.is_empty();
    let expected_stale = has_transaction_exceptions
        && current
            .blockers
            .iter()
            .all(|blocker| blocker["code"].as_str() == Some("review_stale_changes"));
    if !current.ready && !expected_stale {
        return Err(conflict("review checkpoint is no longer ready"));
    }
    let expected = &review.prerequisites;
    let actual = &current.consumed;
    let stable = expected.repository_root == actual.repository_root
        && expected.subject_id == actual.subject_id
        && expected.plan_path == actual.plan_path
        && expected.pre_edit_revision == actual.pre_edit_revision
        && expected.implementation_revision == actual.implementation_revision
        && expected.subject_metadata_revision == actual.subject_metadata_revision
        && expected.baseline_revisions == actual.baseline_revisions
        && expected.contract_fingerprint == actual.contract_fingerprint
        && expected.baseline_id == actual.baseline_id
        && if has_transaction_exceptions {
            manifests_match_except_paths(
                &expected.coverage_manifest,
                &actual.coverage_manifest,
                applied_targets,
                created_directories,
                &review.repository_root,
            )
        } else {
            expected.subject_revision == actual.subject_revision
                && expected.change_fingerprint == actual.change_fingerprint
                && expected.coverage_manifest == actual.coverage_manifest
        };
    if !stable {
        return Err(conflict("review checkpoint prerequisites changed"));
    }
    Ok(())
}

fn manifests_match_except_paths(
    expected: &[Value],
    actual: &[Value],
    targets: &[PathBuf],
    created_directories: &[DirectoryCheckpoint],
    repository: &Path,
) -> bool {
    let relative_exceptions = targets
        .iter()
        .chain(created_directories.iter().map(|directory| &directory.path))
        .filter_map(|target| target.strip_prefix(repository).ok())
        .map(|path| path.to_string_lossy().replace('\\', "/"))
        .collect::<BTreeSet<_>>();
    if relative_exceptions.is_empty() && expected != actual {
        return false;
    }
    let without_target = |manifest: &[Value]| {
        manifest
            .iter()
            .filter(|entry| {
                !entry["path"]
                    .as_str()
                    .is_some_and(|path| relative_exceptions.contains(path))
            })
            .cloned()
            .collect::<Vec<_>>()
    };
    without_target(expected) == without_target(actual)
}

pub fn commit(target: &Path, content: &[u8]) -> Result<()> {
    commit_inner(target, content, None)
}

fn commit_inner(target: &Path, content: &[u8], expected_revision: Option<&str>) -> Result<()> {
    let root = target
        .parent()
        .context("artifact has no parent directory")?;
    let _lock = ProjectLock::acquire(root)?;
    let source = fs::read(target)?;
    let source_hash = varde_workflow_core::occ::version(&source);
    if expected_revision.is_some_and(|expected| expected != source_hash) {
        bail!("artifact changed before staged write");
    }
    commit_staged(target, content, &source)
}

/// Prepare and commit a document update from the snapshot read under its
/// existing parent-directory lock. Preparation must only transform the bytes.
pub fn update<T>(target: &Path, prepare: impl FnOnce(&[u8]) -> Result<(Vec<u8>, T)>) -> Result<T> {
    let root = target
        .parent()
        .context("artifact has no parent directory")?;
    let _lock = ProjectLock::acquire(root)?;
    let source = fs::read(target)?;
    let (content, data) = prepare(&source)?;
    commit_staged(target, &content, &source)?;
    Ok(data)
}

/// Caller holds the target parent's persistent workflow lock.
fn commit_staged(target: &Path, content: &[u8], source: &[u8]) -> Result<()> {
    let root = target
        .parent()
        .context("artifact has no parent directory")?;
    let source_hash = varde_workflow_core::occ::version(source);
    let stage = stage_bytes(target, content)?;
    if root.join(JOURNAL_NAME).exists() {
        let _ = fs::remove_file(&stage);
        bail!("workflow recovery journal already exists; recover it before writing");
    }

    let journal = json!({
        "version": 1,
        "phase": "staged",
        "target": target,
        "staging": stage,
        "source_hash": source_hash,
        "target_hash": varde_workflow_core::occ::version(content),
        "recovery_action": "commit",
    });
    if let Err(error) = fs::write(
        root.join(JOURNAL_NAME),
        serde_json::to_vec_pretty(&journal)?,
    ) {
        let _ = fs::remove_file(&stage);
        return Err(error.into());
    }

    if std::env::var_os("VARDE_WORKFLOW_FAIL_AFTER_STAGE").is_some() {
        bail!("injected interruption after staging");
    }

    fs::rename(&stage, target)?;
    fs::remove_file(root.join(JOURNAL_NAME))?;
    Ok(())
}

pub fn recover(root: &Path) -> Result<bool> {
    let root = root.canonicalize()?;
    let _lock = ProjectLock::acquire(&root)?;
    let conclusion_path = root.join(CONCLUSION_JOURNAL_NAME);
    if conclusion_path.exists() {
        recover_many_guarded(&root, &conclusion_path)?;
        return Ok(true);
    }
    let journal_path = root.join(JOURNAL_NAME);
    if !journal_path.exists() {
        return Ok(false);
    }
    let journal: Value = serde_json::from_slice(&fs::read(&journal_path)?)?;
    match supported_journal_version(&journal)? {
        2 => {
            recover_checkpointed(&root, &journal_path, &journal)?;
            return Ok(true);
        }
        1 => {}
        _ => unreachable!("supported journal version is validated"),
    }
    let target = path_field(&journal, "target")?;
    let stage = path_field(&journal, "staging")?;
    require_contained(&root, &target, "target")?;
    require_contained(&root, &stage, "staging")?;
    let source_hash = string_field(&journal, "source_hash")?;
    let target_hash = string_field(&journal, "target_hash")?;
    let source_identity: Option<FileIdentity> =
        serde_json::from_value(journal["source_identity"].clone())?;
    let target_identity: Option<FileIdentity> =
        serde_json::from_value(journal["target_identity"].clone())?;
    let current_hash = varde_workflow_core::occ::version(&fs::read(&target)?);

    if current_hash == target_hash && legacy_identity_matches(&target, target_identity.as_ref())? {
        if stage.exists() {
            fs::remove_file(&stage)?;
        }
    } else if current_hash == source_hash
        && legacy_identity_matches(&target, source_identity.as_ref())?
        && stage.exists()
        && varde_workflow_core::occ::version(&fs::read(&stage)?) == target_hash
        && legacy_identity_matches(&stage, target_identity.as_ref())?
    {
        fs::rename(&stage, &target)?;
    } else {
        return Err(conflict(
            "journal state does not match its recorded target or staging state",
        ));
    }

    fs::remove_file(journal_path)?;
    Ok(true)
}

fn recover_checkpointed(root: &Path, journal_path: &Path, journal: &Value) -> Result<()> {
    let repository = PathBuf::from(
        journal["repository_root"]
            .as_str()
            .context("checkpoint journal repository identity is missing")?,
    );
    if repository.canonicalize()? != root {
        return Err(conflict(
            "checkpoint journal belongs to another repository lock domain",
        ));
    }
    let memory = MemoryPaths::resolve(root)?;
    let current_roots = memory.write_roots();
    let recorded_roots: Vec<PathBuf> = serde_json::from_value(journal["write_roots"].clone())?;
    if recorded_roots != current_roots {
        return Err(conflict(
            "checkpoint journal project write roots have changed",
        ));
    }
    let target = path_field(journal, "target")?;
    let stage = path_field(journal, "staging")?;
    let target_parent = target
        .parent()
        .and_then(|parent| parent.canonicalize().ok());
    let stage_parent = stage.parent().and_then(|parent| parent.canonicalize().ok());
    if !target_parent
        .as_deref()
        .is_some_and(|parent| current_roots.iter().any(|root| parent.starts_with(root)))
        || !stage_parent
            .as_deref()
            .is_some_and(|parent| current_roots.iter().any(|root| parent.starts_with(root)))
    {
        return Err(conflict(
            "checkpoint journal target or staging path escapes its repository",
        ));
    }
    let review: Option<ReviewCheckpoint> =
        serde_json::from_value(journal["review_checkpoint"].clone())?;
    if let Some(review) = &review
        && journal["subject_id"].as_str() != Some(review.prerequisites.subject_id.as_str())
    {
        return Err(conflict(
            "checkpoint journal subject identity does not match its approval",
        ));
    }
    let sources: Vec<ExpectedSource> = serde_json::from_value(journal["sources"].clone())?;
    let source_hash = string_field(journal, "source_hash")?;
    let target_hash = string_field(journal, "target_hash")?;
    let source_identity: Option<FileIdentity> =
        serde_json::from_value(journal["source_identity"].clone())?;
    let target_identity: Option<FileIdentity> =
        serde_json::from_value(journal["target_identity"].clone())?;
    let current_hash = varde_workflow_core::occ::version(&fs::read(&target)?);
    if current_hash != source_hash && current_hash != target_hash {
        return Err(conflict(
            "checkpoint journal target matches neither its source nor staged hash",
        ));
    }
    let current_matches_source =
        current_hash == source_hash && identity_matches(&target, source_identity.as_ref())?;
    let current_matches_staged =
        current_hash == target_hash && identity_matches(&target, target_identity.as_ref())?;
    if !current_matches_source && !current_matches_staged {
        return Err(conflict(
            "checkpoint journal target type or mode differs from its recorded state",
        ));
    }
    validate_sources(&sources, Some(&target))?;
    let applied = current_matches_staged
        .then_some(target.clone())
        .into_iter()
        .collect::<Vec<_>>();
    validate_review(review.as_ref(), &applied, &[])?;
    if current_matches_staged {
        if stage.exists() {
            if varde_workflow_core::occ::version(&fs::read(&stage)?) != target_hash {
                return Err(conflict("checkpoint journal staging content changed"));
            }
            if !identity_matches(&stage, target_identity.as_ref())? {
                return Err(conflict("checkpoint journal staging type or mode changed"));
            }
            fs::remove_file(stage)?;
        }
    } else {
        if !stage.exists() || varde_workflow_core::occ::version(&fs::read(&stage)?) != target_hash {
            return Err(conflict("checkpoint journal staging content changed"));
        }
        if !identity_matches(&stage, target_identity.as_ref())? {
            return Err(conflict("checkpoint journal staging type or mode changed"));
        }
        fs::rename(stage, target)?;
    }
    fs::remove_file(journal_path)?;
    Ok(())
}

pub fn commit_many_guarded(
    memory: &MemoryPaths,
    writes: &[PendingWrite],
    lock: &ProjectLock,
    sources: &[ExpectedSource],
    review: &ReviewCheckpoint,
) -> Result<()> {
    let root = memory.root.canonicalize()?;
    if lock.root() != root || review.repository_root != root {
        bail!("conclusion repository does not match its cooperative lock and review subject");
    }
    reject_pending_project_journals(&root)?;
    let write_roots = memory
        .write_roots()
        .into_iter()
        .map(|path| varde_workflow_core::memory::canonical_or_lexical(&path))
        .collect::<Vec<_>>();
    let journal_path = root.join(CONCLUSION_JOURNAL_NAME);
    validate_sources(sources, None)?;
    validate_review(Some(review), &[], &[])?;
    let resolved = resolve_writes(&root, &write_roots, writes)?;
    let directory_plan =
        plan_target_directories(&write_roots, resolved.iter().map(|(_, target)| target))?;
    let created_directories = create_transaction_directories(&write_roots, &directory_plan)?;
    let entries = match stage_writes_expected(&write_roots, resolved, sources) {
        Ok(entries) => entries,
        Err(error) => {
            cleanup_created_directories(&created_directories);
            return Err(error);
        }
    };
    let journal = json!({
        "version": 2,
        "kind": "conclusion",
        "phase": "staged",
        "repository_root": root,
        "subject_id": review.prerequisites.subject_id,
        "write_roots": write_roots,
        "entries": entries,
        "sources": sources,
        "review_checkpoint": review,
        "created_directories": created_directories,
        "existing_directories": directory_plan.existing,
        "recovery_action": "commit",
    });
    let journal_bytes = match serde_json::to_vec_pretty(&journal) {
        Ok(bytes) => bytes,
        Err(error) => {
            cleanup_staged_entries(&entries);
            cleanup_created_directories(&created_directories);
            return Err(error.into());
        }
    };
    let mut journal_persisted = false;
    if let Err(error) = write_new_journal(&journal_path, &journal_bytes, &mut journal_persisted) {
        if !journal_persisted {
            cleanup_staged_entries(&entries);
            cleanup_created_directories(&created_directories);
        }
        return Err(error);
    }
    if std::env::var_os("VARDE_WORKFLOW_FAIL_AFTER_CONCLUSION_STAGE").is_some() {
        bail!("injected interruption after conclusion staging");
    }
    validate_sources(sources, None)?;
    validate_review(Some(review), &[], &created_directories)?;
    commit_journal_entries(&write_roots, &journal)?;
    fs::remove_file(journal_path)?;
    Ok(())
}

fn resolve_writes<'a>(
    root: &Path,
    write_roots: &[PathBuf],
    writes: &'a [PendingWrite],
) -> Result<Vec<(&'a PendingWrite, PathBuf)>> {
    let mut targets = BTreeSet::new();
    let mut resolved = Vec::new();
    for write in writes {
        let target = absolute_target(root, write_roots, &write.target)?;
        if !targets.insert(target.clone()) {
            bail!("conclusion contains duplicate target {}", target.display());
        }
        resolved.push((write, target));
    }
    Ok(resolved)
}

fn reject_pending_project_journals(root: &Path) -> Result<()> {
    for name in [JOURNAL_NAME, CONCLUSION_JOURNAL_NAME] {
        match fs::symlink_metadata(root.join(name)) {
            Ok(_) => {
                return Err(conflict(
                    "workflow recovery journal already exists; recover it before writing",
                ));
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
    }
    Ok(())
}

fn plan_target_directories<'a>(
    write_roots: &[PathBuf],
    targets: impl IntoIterator<Item = &'a PathBuf>,
) -> Result<DirectoryPlan> {
    let mut create = BTreeSet::new();
    let mut existing = std::collections::BTreeMap::<PathBuf, DirectoryCheckpoint>::new();
    for target in targets {
        let mut candidate = target
            .parent()
            .context("conclusion target has no parent")?
            .to_path_buf();
        loop {
            candidate = varde_workflow_core::memory::canonical_or_lexical(&candidate);
            if !write_roots
                .iter()
                .any(|root| candidate.starts_with(root) || root.starts_with(&candidate))
            {
                return Err(conflict(
                    "conclusion target parent escapes project write roots",
                ));
            }
            match fs::symlink_metadata(&candidate) {
                Ok(_) => {
                    let identity = file_identity(&candidate)?
                        .context("existing conclusion parent disappeared")?;
                    if identity.entry_type != "directory" {
                        return Err(conflict("conclusion target parent is not a real directory"));
                    }
                    let canonical = candidate.canonicalize()?;
                    if !write_roots
                        .iter()
                        .any(|root| canonical.starts_with(root) || root.starts_with(&canonical))
                    {
                        return Err(conflict(
                            "conclusion target parent escapes project write roots",
                        ));
                    }
                    match existing.get(&canonical) {
                        Some(previous) if previous.identity != identity => {
                            return Err(conflict(
                                "conclusion parent directory changed during preparation",
                            ));
                        }
                        Some(_) => {}
                        None => {
                            existing.insert(
                                canonical.clone(),
                                DirectoryCheckpoint {
                                    path: canonical,
                                    identity,
                                },
                            );
                        }
                    }
                    break;
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    create.insert(candidate.clone());
                    candidate = candidate
                        .parent()
                        .context("conclusion target has no existing ancestor")?
                        .to_path_buf();
                }
                Err(error) => return Err(error.into()),
            }
        }
    }
    let mut create = create.into_iter().collect::<Vec<_>>();
    create.sort_by_key(|path| path.components().count());
    Ok(DirectoryPlan {
        create,
        existing: existing.into_values().collect(),
    })
}

fn create_transaction_directories(
    write_roots: &[PathBuf],
    plan: &DirectoryPlan,
) -> Result<Vec<DirectoryCheckpoint>> {
    let mut created = Vec::new();
    validate_directory_checkpoints(write_roots, &[], &plan.existing)?;
    for path in &plan.create {
        if let Err(error) = validate_directory_checkpoints(write_roots, &created, &plan.existing) {
            cleanup_created_directories(&created);
            return Err(error);
        }
        if !write_roots
            .iter()
            .any(|root| path.starts_with(root) || root.starts_with(path))
        {
            cleanup_created_directories(&created);
            return Err(conflict(
                "created conclusion directory is outside project write roots",
            ));
        }
        match fs::create_dir(path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                cleanup_created_directories(&created);
                return Err(conflict(format!(
                    "conclusion target directory appeared during preparation: {}",
                    path.display()
                )));
            }
            Err(error) => {
                cleanup_created_directories(&created);
                return Err(error.into());
            }
        }
        let canonical = varde_workflow_core::memory::canonical_or_lexical(path);
        let identity = match file_identity(&canonical)? {
            Some(identity) if identity.entry_type == "directory" => identity,
            _ => {
                cleanup_created_directories(&created);
                return Err(conflict(
                    "created conclusion parent is no longer a directory",
                ));
            }
        };
        created.push(DirectoryCheckpoint {
            path: canonical,
            identity,
        });
        if let Err(error) = validate_directory_checkpoints(write_roots, &created, &plan.existing) {
            cleanup_created_directories(&created);
            return Err(error);
        }
    }
    Ok(created)
}

fn validate_directory_checkpoints(
    write_roots: &[PathBuf],
    created: &[DirectoryCheckpoint],
    existing: &[DirectoryCheckpoint],
) -> Result<()> {
    for checkpoint in created {
        if checkpoint.identity.entry_type != "directory"
            || !checkpoint.path.is_absolute()
            || !write_roots
                .iter()
                .any(|root| checkpoint.path.starts_with(root) || root.starts_with(&checkpoint.path))
        {
            return Err(conflict(
                "conclusion journal contains an invalid directory precondition",
            ));
        }
    }
    for checkpoint in existing {
        if checkpoint.identity.entry_type != "directory"
            || !checkpoint.path.is_absolute()
            || !write_roots
                .iter()
                .any(|root| checkpoint.path.starts_with(root) || root.starts_with(&checkpoint.path))
        {
            return Err(conflict(
                "conclusion journal contains an invalid directory ancestor precondition",
            ));
        }
    }
    for checkpoint in created.iter().chain(existing) {
        let canonical = checkpoint.path.canonicalize().map_err(|_| {
            conflict(format!(
                "conclusion directory disappeared: {}",
                checkpoint.path.display()
            ))
        })?;
        if canonical != checkpoint.path
            || file_identity(&checkpoint.path)?.as_ref() != Some(&checkpoint.identity)
        {
            return Err(conflict(format!(
                "conclusion directory identity changed: {}",
                checkpoint.path.display()
            )));
        }
    }
    Ok(())
}

fn cleanup_created_directories(created: &[DirectoryCheckpoint]) {
    for checkpoint in created.iter().rev() {
        if file_identity(&checkpoint.path)
            .is_ok_and(|identity| identity.as_ref() == Some(&checkpoint.identity))
        {
            let _ = fs::remove_dir(&checkpoint.path);
        }
    }
}

fn cleanup_staged_entries(entries: &[Value]) {
    for entry in entries {
        if let (Ok(stage), Ok(Some(identity))) = (
            path_field(entry, "staging"),
            serde_json::from_value::<Option<FileIdentity>>(entry["target_identity"].clone()),
        ) && identity_matches(&stage, Some(&identity)).unwrap_or(false)
        {
            let _ = fs::remove_file(stage);
        }
    }
}

fn journal_directories(journal: &Value, field: &str) -> Result<Vec<DirectoryCheckpoint>> {
    match journal.get(field) {
        Some(value) => serde_json::from_value(value.clone()).map_err(|error| {
            conflict(format!(
                "invalid conclusion journal directory field `{field}`: {error}"
            ))
        }),
        None => Ok(Vec::new()),
    }
}

fn write_new_journal(path: &Path, bytes: &[u8], persisted: &mut bool) -> Result<()> {
    let mut file = match OpenOptions::new().write(true).create_new(true).open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            return Err(conflict(
                "workflow recovery journal already exists; recover it before writing",
            ));
        }
        Err(error) => return Err(error.into()),
    };
    *persisted = true;
    if let Err(error) = file.write_all(bytes) {
        if fs::remove_file(path).is_ok() {
            *persisted = false;
        }
        return Err(error.into());
    }
    Ok(())
}

fn stage_writes_expected(
    write_roots: &[PathBuf],
    resolved: Vec<(&PendingWrite, PathBuf)>,
    sources: &[ExpectedSource],
) -> Result<Vec<Value>> {
    let mut entries = Vec::new();
    let mut stages = Vec::new();
    let result = (|| {
        for (write, target) in resolved {
            let parent = target.parent().context("conclusion target has no parent")?;
            require_tree_contained(write_roots, parent, "target")?;
            let expected = sources
                .iter()
                .find(|source| source.path == target)
                .with_context(|| {
                    format!(
                        "conclusion target was not captured before preparation: {}",
                        target.display()
                    )
                })?;
            let stage = stage_bytes(&target, &write.content)?;
            let target_identity = file_identity(&stage)?;
            if let Some(identity) = &target_identity {
                stages.push((stage.clone(), identity.clone()));
            }
            entries.push(json!({
                "target": target,
                "staging": stage,
                "source_hash": expected.revision,
                "target_hash": varde_workflow_core::occ::version(&write.content),
                "source_identity": &expected.identity,
                "target_identity": target_identity,
            }));
        }
        Ok(entries)
    })();
    if result.is_err() {
        cleanup_owned_stages(&stages);
    }
    result
}

fn cleanup_owned_stages(stages: &[(PathBuf, FileIdentity)]) {
    for (stage, identity) in stages {
        if identity_matches(stage, Some(identity)).unwrap_or(false) {
            let _ = fs::remove_file(stage);
        }
    }
}

fn recover_many_guarded(root: &Path, journal_path: &Path) -> Result<()> {
    let write_roots = MemoryPaths::resolve(root)?.write_roots();
    let journal: Value = serde_json::from_slice(&fs::read(journal_path)?)?;
    match supported_journal_version(&journal)? {
        2 => return recover_conclusion_checkpointed(root, &write_roots, journal_path, &journal),
        1 => {}
        _ => unreachable!("supported journal version is validated"),
    }
    commit_journal_entries(&write_roots, &journal)?;
    fs::remove_file(journal_path)?;
    Ok(())
}

fn recover_conclusion_checkpointed(
    root: &Path,
    write_roots: &[PathBuf],
    journal_path: &Path,
    journal: &Value,
) -> Result<()> {
    let repository = PathBuf::from(
        journal["repository_root"]
            .as_str()
            .context("conclusion journal repository identity is missing")?,
    );
    if repository.canonicalize()? != root {
        return Err(conflict(
            "conclusion journal belongs to another repository lock domain",
        ));
    }
    let recorded_roots: Vec<PathBuf> = serde_json::from_value(journal["write_roots"].clone())?;
    let current_roots = write_roots
        .iter()
        .map(|path| varde_workflow_core::memory::canonical_or_lexical(path))
        .collect::<Vec<_>>();
    if recorded_roots != current_roots {
        return Err(conflict(
            "conclusion journal memory paths differ from its originating project",
        ));
    }
    let review: ReviewCheckpoint = serde_json::from_value(journal["review_checkpoint"].clone())?;
    if journal["subject_id"].as_str() != Some(review.prerequisites.subject_id.as_str())
        || review.repository_root != root
    {
        return Err(conflict(
            "conclusion journal subject identity does not match its originating project",
        ));
    }
    let entries = journal["entries"]
        .as_array()
        .context("conclusion journal entries are missing")?;
    let targets = entries
        .iter()
        .map(|entry| path_field(entry, "target"))
        .collect::<Result<Vec<_>>>()?;
    let sources: Vec<ExpectedSource> = serde_json::from_value(journal["sources"].clone())?;
    let created_directories = journal_directories(journal, "created_directories")?;
    let existing_directories = journal_directories(journal, "existing_directories")?;
    validate_directory_checkpoints(write_roots, &created_directories, &existing_directories)?;
    validate_sources_except(&sources, &targets)?;
    let mut applied = Vec::new();
    for entry in entries {
        let target = path_field(entry, "target")?;
        let source_hash = entry["source_hash"].as_str();
        let target_hash = string_field(entry, "target_hash")?;
        let source_identity: Option<FileIdentity> =
            serde_json::from_value(entry["source_identity"].clone())?;
        let target_identity: Option<FileIdentity> =
            serde_json::from_value(entry["target_identity"].clone())?;
        let current_hash = target
            .exists()
            .then(|| fs::read(&target).map(|bytes| varde_workflow_core::occ::version(&bytes)))
            .transpose()?;
        if current_hash.as_deref() == Some(target_hash.as_str())
            && identity_matches(&target, target_identity.as_ref())?
        {
            applied.push(target);
        } else if current_hash.as_deref() != source_hash
            || !identity_matches(&target, source_identity.as_ref())?
        {
            return Err(conflict(
                "conclusion journal target changed outside its recorded transaction",
            ));
        }
    }
    validate_review(Some(&review), &applied, &created_directories)?;
    commit_journal_entries(write_roots, journal)?;
    fs::remove_file(journal_path)?;
    Ok(())
}

fn commit_journal_entries(write_roots: &[PathBuf], journal: &Value) -> Result<()> {
    let journal_version = supported_journal_version(journal)?;
    let created_directories = journal_directories(journal, "created_directories")?;
    let existing_directories = journal_directories(journal, "existing_directories")?;
    validate_directory_checkpoints(write_roots, &created_directories, &existing_directories)?;
    let entries = journal["entries"]
        .as_array()
        .context("conclusion journal entries are missing")?;
    let fail_after = std::env::var("VARDE_WORKFLOW_FAIL_CONCLUSION_AFTER_RENAMES")
        .ok()
        .and_then(|value| value.parse::<usize>().ok());
    let mut renamed = 0;
    for entry in entries {
        let target = path_field(entry, "target")?;
        let stage = path_field(entry, "staging")?;
        require_tree_contained(
            write_roots,
            target.parent().context("target has no parent")?,
            "target",
        )?;
        require_tree_contained(
            write_roots,
            stage.parent().context("staging has no parent")?,
            "staging",
        )?;
        let target_hash = string_field(entry, "target_hash")?;
        let source_hash = entry["source_hash"].as_str();
        let source_identity: Option<FileIdentity> =
            serde_json::from_value(entry["source_identity"].clone())?;
        let target_identity: Option<FileIdentity> =
            serde_json::from_value(entry["target_identity"].clone())?;
        let current_hash = target
            .exists()
            .then(|| fs::read(&target).map(|bytes| varde_workflow_core::occ::version(&bytes)))
            .transpose()?;

        if current_hash.as_deref() == Some(&target_hash)
            && identity_matches_for_journal(&target, target_identity.as_ref(), journal_version)?
        {
            if stage.exists() {
                fs::remove_file(stage)?;
            }
            continue;
        }
        if current_hash.as_deref() != source_hash
            || !identity_matches_for_journal(&target, source_identity.as_ref(), journal_version)?
        {
            return Err(conflict(format!(
                "conclusion journal source changed for {}",
                target.display()
            )));
        }
        if !stage.exists()
            || varde_workflow_core::occ::version(&fs::read(&stage)?) != target_hash
            || !identity_matches_for_journal(&stage, target_identity.as_ref(), journal_version)?
        {
            return Err(conflict(format!(
                "conclusion journal staging changed for {}",
                target.display()
            )));
        }
        fs::rename(stage, target)?;
        renamed += 1;
        if fail_after == Some(renamed) {
            bail!("injected interruption during conclusion commit");
        }
    }
    Ok(())
}

fn absolute_target(root: &Path, write_roots: &[PathBuf], target: &Path) -> Result<PathBuf> {
    let target = if target.is_absolute() {
        let target = varde_workflow_core::memory::canonical_or_lexical(target);
        let Some(base) = write_roots.iter().find(|base| target.starts_with(base)) else {
            bail!("conclusion target points outside project root and memory directories");
        };
        require_normal_components(target.strip_prefix(base)?)?;
        target.to_path_buf()
    } else {
        require_normal_components(target)?;
        root.join(target)
    };
    if !write_roots.iter().any(|base| target.starts_with(base)) {
        bail!("conclusion target points outside project root and memory directories");
    }
    Ok(target)
}

fn require_normal_components(path: &Path) -> Result<()> {
    if path
        .components()
        .all(|component| matches!(component, std::path::Component::Normal(_)))
    {
        Ok(())
    } else {
        bail!("conclusion target contains unsafe path components")
    }
}

fn require_tree_contained(write_roots: &[PathBuf], path: &Path, field: &str) -> Result<()> {
    let path = path.canonicalize()?;
    if !write_roots.iter().any(|root| path.starts_with(root)) {
        bail!(
            "conclusion journal field `{field}` points outside project root and memory directories"
        );
    }
    Ok(())
}

fn string_field(value: &Value, field: &str) -> Result<String> {
    value[field]
        .as_str()
        .map(str::to_string)
        .with_context(|| format!("journal field `{field}` is missing"))
}

fn supported_journal_version(journal: &Value) -> Result<u64> {
    let version = journal["version"]
        .as_u64()
        .ok_or_else(|| conflict("workflow recovery journal has a missing or invalid version"))?;
    if matches!(version, 1 | 2) {
        Ok(version)
    } else {
        Err(conflict(format!(
            "unsupported workflow recovery journal version {version}"
        )))
    }
}

fn path_field(value: &Value, field: &str) -> Result<PathBuf> {
    Ok(PathBuf::from(string_field(value, field)?))
}

fn require_contained(root: &Path, path: &Path, field: &str) -> Result<()> {
    let root = root.canonicalize()?;
    let parent = path
        .parent()
        .with_context(|| format!("journal field `{field}` has no parent"))?
        .canonicalize()?;
    if parent != root {
        bail!("journal field `{field}` points outside recovery root");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[cfg(unix)]
    fn staging_preserves_existing_modes_and_keeps_new_documents_private() {
        use std::os::unix::fs::PermissionsExt;
        let root = std::env::temp_dir().join(format!(
            "varde-stage-permissions-{}-{:?}",
            std::process::id(),
            std::time::SystemTime::now()
        ));
        fs::create_dir(&root).unwrap();
        let target = root.join("document.md");
        fs::write(&target, b"original").unwrap();
        for mode in [0o600, 0o640, 0o750, 0o440, 0o2640] {
            fs::set_permissions(&target, fs::Permissions::from_mode(mode)).unwrap();
            // The kernel may strip special bits when initially setting them.
            let existing_mode = fs::metadata(&target).unwrap().permissions().mode() & 0o7777;
            let stage = stage_bytes(&target, b"replacement").unwrap();
            assert_eq!(
                fs::metadata(&stage).unwrap().permissions().mode() & 0o7777,
                existing_mode
            );
            assert_eq!(fs::read(&target).unwrap(), b"original");
            assert_eq!(fs::read(&stage).unwrap(), b"replacement");
            fs::remove_file(stage).unwrap();
        }
        let stage = stage_bytes(&root.join("new.md"), b"private").unwrap();
        assert_eq!(
            fs::metadata(stage).unwrap().permissions().mode() & 0o7777 & !0o600,
            0
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn update_reads_and_prepares_only_after_acquiring_parent_lock() {
        let root = std::env::temp_dir().join(format!(
            "varde-journal-update-{}-{:?}",
            std::process::id(),
            std::time::SystemTime::now()
        ));
        fs::create_dir(&root).unwrap();
        let target = root.join("state.md");
        fs::write(&target, b"original").unwrap();
        let lock = ProjectLock::acquire(&root).unwrap();
        let (started_tx, started_rx) = std::sync::mpsc::channel();
        let (prepared_tx, prepared_rx) = std::sync::mpsc::channel();
        let worker_target = target.clone();
        let worker = std::thread::spawn(move || {
            started_tx.send(()).unwrap();
            update(&worker_target, |bytes| {
                prepared_tx.send(bytes.to_vec()).unwrap();
                let mut content = bytes.to_vec();
                content.push(b'!');
                Ok((content, ()))
            })
            .unwrap();
        });
        started_rx.recv().unwrap();
        assert!(matches!(
            prepared_rx.recv_timeout(std::time::Duration::from_millis(100)),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout)
        ));
        fs::write(&target, b"updated").unwrap();
        drop(lock);
        assert_eq!(
            prepared_rx
                .recv_timeout(std::time::Duration::from_secs(5))
                .unwrap(),
            b"updated"
        );
        worker.join().unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"updated!");
        assert!(!root.join(JOURNAL_NAME).exists());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn failed_update_preparation_preserves_document_and_releases_lock() {
        let root = std::env::temp_dir().join(format!(
            "varde-journal-failed-update-{}-{:?}",
            std::process::id(),
            std::time::SystemTime::now()
        ));
        fs::create_dir(&root).unwrap();
        let target = root.join("state.md");
        fs::write(&target, b"original").unwrap();
        let result: Result<()> = update(&target, |_| bail!("invalid document"));
        assert!(result.is_err());
        assert_eq!(fs::read(&target).unwrap(), b"original");
        assert_eq!(
            fs::read_dir(&root).unwrap().count(),
            2,
            "only document and persistent lock"
        );
        update(&target, |_| Ok((b"valid".to_vec(), ()))).unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"valid");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn prejournal_staging_failure_cleans_only_owned_stages_and_empty_directories() {
        let temporary_root = std::env::temp_dir().join(format!(
            "varde-journal-prestage-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&temporary_root).unwrap();
        let root = temporary_root.canonicalize().unwrap();
        let marker = root.join("keep.txt");
        fs::write(&marker, b"preexisting parent content").unwrap();
        let created_parent = root.join("created");
        let first_target = created_parent.join("first.md");
        let second_target = created_parent.join("second.md");
        let first_source = expected_source_at(&first_target).unwrap();
        let writes = [
            PendingWrite {
                target: first_target.clone(),
                content: b"first".to_vec(),
            },
            PendingWrite {
                target: second_target.clone(),
                content: b"second".to_vec(),
            },
        ];
        let write_roots = vec![root.clone()];
        let directory_plan =
            plan_target_directories(&write_roots, [&first_target, &second_target]).unwrap();
        let created = create_transaction_directories(&write_roots, &directory_plan).unwrap();
        let result = stage_writes_expected(
            &write_roots,
            vec![(&writes[0], first_target), (&writes[1], second_target)],
            &[first_source],
        );

        assert!(result.is_err());
        assert!(created_parent.is_dir());
        assert!(fs::read_dir(&created_parent).unwrap().next().is_none());
        cleanup_created_directories(&created);
        assert!(!created_parent.exists());
        assert_eq!(fs::read(&marker).unwrap(), b"preexisting parent content");
        fs::remove_dir_all(root).unwrap();
    }
}
