//! Repository-scoped inventories and immutable local baseline snapshots.

use anyhow::{Context, Result, anyhow};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha1::{Digest, Sha1};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::fs::{File, OpenOptions};
use std::io::{self, BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};

use crate::review_contract;
use crate::review_gates;

const HASH_BUFFER_BYTES: usize = 64 * 1024;
const FILE_HASH_TAG: &[u8] = b"review-file-v1";
static NEXT_BLOB_TEMP_ID: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Serialize, Deserialize, Clone, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(crate) struct SnapshotEntry {
    pub entry_type: String,
    pub sha1: Option<String>,
    pub size: Option<u64>,
    pub mode: Option<u32>,
    pub symlink_target: Option<String>,
    pub content_path: Option<PathBuf>,
}

#[derive(Debug)]
pub(crate) struct CurrentEntry {
    pub snapshot: SnapshotEntry,
}

pub(crate) fn inventory(
    repository: &Path,
    working: &Path,
    scope: &[String],
    excludes: &[String],
) -> Result<BTreeMap<String, CurrentEntry>> {
    let mut files = git_files(repository)?.unwrap_or_default();
    let git_inventory = !files.is_empty() || repository.join(".git").exists();
    if git_inventory {
        for root in scope {
            let path = repository.join(root);
            if is_file_or_link(&path) {
                let value = root.clone();
                if !files.contains(&value) {
                    files.push(value);
                }
            }
            if !excluded(root, excludes)
                && !generated(root)
                && !under_working(repository, working, root)
            {
                reject_special_entries(repository, working, root, excludes)?;
            }
        }
    }
    let mut entries = BTreeMap::new();
    if git_inventory {
        files.sort();
        files.dedup();
        for relative in files {
            if !within_roots(&relative, scope)
                || excluded(&relative, excludes)
                || generated(&relative)
                || under_working(repository, working, &relative)
            {
                continue;
            }
            add_current_path(repository, &relative, &mut entries)?;
            add_parent_directories(repository, &relative, &mut entries)?;
        }
        for root in scope {
            let path = repository.join(root);
            if path.is_dir() && !path.symlink_metadata()?.file_type().is_symlink() {
                add_current_path(repository, root, &mut entries)?;
            }
        }
    } else {
        for root in scope {
            walk(repository, working, root, excludes, &mut entries)?;
        }
    }
    Ok(entries)
}

/// Explicit file scopes are separate from repository traversal and working-store exclusion.
pub(crate) fn normalize_artifacts(
    repository: &Path,
    working: &Path,
    artifacts: &[PathBuf],
) -> Result<Vec<String>> {
    let mut normalized = Vec::new();
    for path in artifacts {
        if !path.is_absolute()
            || path.components().any(|part| {
                matches!(
                    part,
                    std::path::Component::ParentDir | std::path::Component::CurDir
                )
            })
            || path.to_str().is_none()
        {
            return Err(review_gates::invalid(
                "artifact must be an absolute UTF-8 file path without traversal",
            ));
        }
        // Keep lexical identity, and reject all aliases rather than silently following them.
        let mut cursor = PathBuf::new();
        for part in path.components() {
            cursor.push(part.as_os_str());
            match fs::symlink_metadata(&cursor) {
                Ok(meta) if meta.file_type().is_symlink() => {
                    return Err(review_gates::invalid(
                        "artifact paths may not contain symlinks",
                    ));
                }
                Ok(meta) if cursor == *path && !meta.is_file() => {
                    return Err(review_gates::invalid(
                        "artifact must be a regular file or a missing future file",
                    ));
                }
                Ok(meta) if cursor != *path && !meta.is_dir() => {
                    return Err(review_gates::invalid(
                        "artifact ancestor must be a directory",
                    ));
                }
                Ok(meta) => {
                    #[cfg(unix)]
                    {
                        use std::os::unix::fs::MetadataExt;
                        if cursor == *path && meta.nlink() > 1 {
                            return Err(review_gates::invalid(
                                "artifact files may not have hard-link aliases",
                            ));
                        }
                    }
                    #[cfg(not(unix))]
                    let _ = meta;
                }
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
        }
        if cursor.to_str() != path.to_str() {
            return Err(review_gates::invalid(
                "artifact path must use its exact lexical identity",
            ));
        }
        if path.starts_with(repository) {
            return Err(review_gates::invalid(
                "artifact is inside the repository; use --scope",
            ));
        }
        if path.starts_with(working.join("review-gates")) || generated(path.to_str().unwrap()) {
            return Err(review_gates::invalid(
                "artifact may not cover review evidence or generated workflow state",
            ));
        }
        normalized.push(path.to_str().unwrap().to_string());
    }
    normalized.sort();
    normalized.dedup();
    Ok(normalized)
}

pub(crate) fn artifact_key(path: &str) -> String {
    format!("artifact:{path}")
}

pub(crate) fn inventory_with_artifacts(
    repository: &Path,
    working: &Path,
    scope: &[String],
    excludes: &[String],
    artifacts: &[String],
) -> Result<BTreeMap<String, CurrentEntry>> {
    let mut entries = inventory(repository, working, scope, excludes)?;
    let paths: Vec<_> = artifacts.iter().map(PathBuf::from).collect();
    let normalized = normalize_artifacts(repository, working, &paths)?;
    if normalized != artifacts {
        return Err(review_gates::invalid(
            "stored artifact scope has invalid identity or ordering",
        ));
    }
    for path in artifacts {
        let mut explicit = BTreeMap::new();
        add_current_path(Path::new("/"), path, &mut explicit)?;
        if let Some(entry) = explicit.remove(path) {
            let key = artifact_key(path);
            if entries.insert(key, entry).is_some() {
                return Err(review_gates::invalid(
                    "artifact identity collides with a repository entry",
                ));
            }
        }
    }
    Ok(entries)
}

pub(crate) fn capture_baseline(
    subject_dir: &Path,
    current: &BTreeMap<String, CurrentEntry>,
    snapshots: &mut BTreeMap<String, SnapshotEntry>,
) -> Result<()> {
    for (path, entry) in current {
        let mut snapshot = entry.snapshot.clone();
        persist_content(subject_dir, &mut snapshot)?;
        snapshots.insert(path.clone(), snapshot);
    }
    Ok(())
}

pub(crate) fn relocate_content_paths(
    snapshots: &mut BTreeMap<String, SnapshotEntry>,
    from: &Path,
    to: &Path,
) {
    for entry in snapshots.values_mut() {
        if let Some(path) = entry.content_path.as_mut()
            && let Ok(relative) = path.strip_prefix(from)
        {
            *path = to.join(relative);
        }
    }
}

pub(crate) fn capture_scope_additions(
    subject_dir: &Path,
    current: &BTreeMap<String, CurrentEntry>,
    new_roots: &[String],
    old_roots: &[String],
    snapshots: &mut BTreeMap<String, SnapshotEntry>,
    scope_additions: &mut BTreeSet<String>,
    ignored_keys: &BTreeSet<String>,
) -> Result<()> {
    for (path, entry) in current {
        if ignored_keys.contains(path)
            || snapshots.contains_key(path)
            || !new_roots.iter().any(|root| covers(root, path))
            || old_roots.iter().any(|root| covers(root, path))
        {
            continue;
        }
        let mut snapshot = entry.snapshot.clone();
        persist_content(subject_dir, &mut snapshot)?;
        snapshots.insert(path.clone(), snapshot);
        scope_additions.insert(path.clone());
    }
    Ok(())
}

pub(crate) fn baseline_fingerprint(
    subject_id: &str,
    scope: &[String],
    excludes: &[String],
    snapshots: &BTreeMap<String, SnapshotEntry>,
    scope_additions: &BTreeSet<String>,
) -> Result<String> {
    review_contract::fingerprint_json(
        "varde-review-baseline-v1",
        &json!({
            "subject_id": subject_id,
            "scope": scope,
            "excludes": excludes,
            "snapshots": snapshots,
            "scope_additions": scope_additions,
        }),
    )
}

/// Empty artifact scopes preserve the exact legacy fingerprint payload.
pub(crate) fn baseline_fingerprint_with_artifacts(
    subject_id: &str,
    scope: &[String],
    excludes: &[String],
    snapshots: &BTreeMap<String, SnapshotEntry>,
    scope_additions: &BTreeSet<String>,
    artifacts: &[String],
) -> Result<String> {
    if artifacts.is_empty() {
        return baseline_fingerprint(subject_id, scope, excludes, snapshots, scope_additions);
    }
    review_contract::fingerprint_json(
        "varde-review-baseline-v1",
        &json!({"subject_id":subject_id, "scope":scope, "excludes":excludes,
            "snapshots":snapshots, "scope_additions":scope_additions, "artifact_scope":artifacts}),
    )
}

pub(crate) fn verify_baseline_blobs(
    subject_dir: &Path,
    snapshots: &BTreeMap<String, SnapshotEntry>,
) -> Result<()> {
    let subject_root = subject_dir.canonicalize()?;
    let baseline_root = subject_root.join("baseline").canonicalize()?;
    if !baseline_root.starts_with(&subject_root) || !baseline_root.is_dir() {
        return Err(review_gates::invalid(
            "review baseline directory escapes its subject storage",
        ));
    }
    let blob_root = baseline_root.join("blobs").canonicalize()?;
    if !blob_root.starts_with(&baseline_root) || !blob_root.is_dir() {
        return Err(review_gates::invalid(
            "review baseline blob directory escapes its local snapshot store",
        ));
    }
    for (path, entry) in snapshots {
        if entry.entry_type != "file" {
            continue;
        }
        let content_path = entry
            .content_path
            .as_ref()
            .ok_or_else(|| anyhow!("baseline file `{path}` has no retrievable content"))?;
        let canonical = content_path
            .canonicalize()
            .with_context(|| format!("baseline content for `{path}` is missing"))?;
        if !canonical.starts_with(&blob_root) || !canonical.is_file() {
            return Err(review_gates::invalid(format!(
                "baseline content for `{path}` escapes its local snapshot store"
            )));
        }
        let (digest, _) = hash_file(&canonical)?;
        if entry.sha1.as_deref() != Some(digest.as_str()) {
            return Err(review_gates::invalid(format!(
                "baseline content for `{path}` failed its fingerprint check"
            )));
        }
    }
    Ok(())
}

pub(crate) fn manifest(
    baseline: &BTreeMap<String, SnapshotEntry>,
    scope_additions: &BTreeSet<String>,
    current: &BTreeMap<String, CurrentEntry>,
) -> Vec<Value> {
    let paths: BTreeSet<String> = baseline.keys().chain(current.keys()).cloned().collect();
    paths
        .into_iter()
        .map(|path| {
            let old = baseline.get(&path);
            let new = current.get(&path).map(|entry| &entry.snapshot);
            let change = match (old, new) {
                (None, Some(_)) => "added",
                (Some(_), None) => "deleted",
                (Some(old), Some(new)) if same_state(old, new) => {
                    if scope_additions.contains(&path) {
                        "added"
                    } else {
                        "unchanged"
                    }
                }
                (Some(_), Some(_)) => "modified",
                (None, None) => unreachable!("manifest paths come from an entry map"),
            };
            json!({
                "path": path,
                "change": change,
                "baseline": old.map(entry_json),
                "current": new.map(entry_json),
                "scope_addition": scope_additions.contains(&path),
            })
        })
        .collect()
}

fn entry_json(entry: &SnapshotEntry) -> Value {
    json!({
        "type": entry.entry_type,
        "sha1": entry.sha1,
        "size": entry.size,
        "mode": entry.mode,
        "symlink_target": entry.symlink_target,
        "content_path": entry.content_path,
    })
}

fn same_state(left: &SnapshotEntry, right: &SnapshotEntry) -> bool {
    left.entry_type == right.entry_type
        && left.sha1 == right.sha1
        && left.size == right.size
        && left.mode == right.mode
        && left.symlink_target == right.symlink_target
}

fn persist_content(subject_dir: &Path, entry: &mut SnapshotEntry) -> Result<()> {
    if entry.entry_type != "file" {
        return Ok(());
    }
    let digest = entry
        .sha1
        .as_deref()
        .ok_or_else(|| anyhow!("baseline file has no fingerprint"))?;
    let source = entry
        .content_path
        .as_deref()
        .ok_or_else(|| anyhow!("baseline file has no source path"))?;
    let size = entry
        .size
        .ok_or_else(|| anyhow!("baseline file has no size"))?;
    let blob = subject_dir
        .join("baseline/blobs")
        .join(format!("{}.blob", digest.trim_start_matches("sha1-v1:")));
    if blob.exists() {
        verify_blob_matches_source(source, &blob, digest, size)?;
        entry.content_path = Some(blob);
        return Ok(());
    }

    let (temporary, file) = create_blob_temp(&blob)?;
    if let Err(error) = copy_and_hash_file(source, file, size).and_then(|actual| {
        if actual == digest {
            Ok(())
        } else {
            Err(anyhow!(
                "scoped file changed while its baseline content was being captured: {}",
                source.display()
            ))
        }
    }) {
        let _ = fs::remove_file(&temporary);
        return Err(error);
    }
    let publish_result = match fs::hard_link(&temporary, &blob) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
            verify_blob_matches_source(source, &blob, digest, size)
        }
        Err(error) => Err(error)
            .with_context(|| format!("failed to publish baseline content at {}", blob.display())),
    };
    let cleanup_result = fs::remove_file(&temporary).with_context(|| {
        format!(
            "failed to remove temporary baseline content at {}",
            temporary.display()
        )
    });
    publish_result?;
    cleanup_result?;
    entry.content_path = Some(blob);
    Ok(())
}

fn create_blob_temp(blob: &Path) -> Result<(PathBuf, File)> {
    let parent = blob
        .parent()
        .ok_or_else(|| anyhow!("baseline blob has no parent directory"))?;
    let name = blob
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| anyhow!("baseline blob path is not valid UTF-8"))?;
    for _ in 0..128 {
        let id = NEXT_BLOB_TEMP_ID.fetch_add(1, Ordering::Relaxed);
        let temporary = parent.join(format!(".{name}.{}.{}.tmp", std::process::id(), id));
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
        {
            Ok(file) => return Ok((temporary, file)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(error).with_context(|| {
                    format!(
                        "failed to create temporary baseline content at {}",
                        temporary.display()
                    )
                });
            }
        }
    }
    Err(anyhow!("could not allocate a temporary baseline blob path"))
}

fn copy_and_hash_file(source: &Path, destination: File, size: u64) -> Result<String> {
    let source = File::open(source)
        .with_context(|| format!("failed to capture baseline content at {}", source.display()))?;
    let mut source = BufReader::new(source);
    let mut destination = BufWriter::new(destination);
    let digest = hash_reader_with_copy(&mut source, size, Some(&mut destination))?;
    destination.flush()?;
    Ok(digest)
}

fn verify_blob_matches_source(source: &Path, blob: &Path, digest: &str, size: u64) -> Result<()> {
    let source_path = source.to_path_buf();
    let mut source = BufReader::new(File::open(&source_path).with_context(|| {
        format!(
            "failed to capture baseline content at {}",
            source_path.display()
        )
    })?);
    let mut blob_reader = BufReader::new(
        File::open(blob)
            .with_context(|| format!("failed to read baseline content at {}", blob.display()))?,
    );
    let mut hasher = file_hasher(size);
    let mut source_buffer = [0_u8; HASH_BUFFER_BYTES];
    let mut blob_buffer = [0_u8; HASH_BUFFER_BYTES];
    let mut bytes_read = 0_u64;
    let mut matches_blob = true;
    loop {
        let source_count = read_chunk(&mut source, &mut source_buffer)?;
        let blob_count = read_chunk(&mut blob_reader, &mut blob_buffer)?;
        matches_blob &= source_count == blob_count
            && source_buffer[..source_count] == blob_buffer[..blob_count];
        if source_count == 0 {
            break;
        }
        bytes_read = bytes_read
            .checked_add(source_count as u64)
            .ok_or_else(|| anyhow!("scoped file is too large to capture"))?;
        hasher.update(&source_buffer[..source_count]);
    }
    if bytes_read != size || finish_file_hash(hasher) != digest {
        return Err(anyhow!(
            "scoped file changed while its baseline content was being captured: {}",
            source_path.display()
        ));
    }
    if !matches_blob {
        return Err(anyhow!(
            "baseline content hash collision at {}",
            blob.display()
        ));
    }
    Ok(())
}

fn hash_file(path: &Path) -> Result<(String, u64)> {
    let file = fs::File::open(path)
        .with_context(|| format!("failed to read scoped file `{}`", path.display()))?;
    let size = file.metadata()?.len();
    Ok((hash_reader(file, size)?, size))
}

fn hash_reader(mut reader: impl Read, size: u64) -> Result<String> {
    hash_reader_with_copy(&mut reader, size, None)
}

fn hash_reader_with_copy(
    reader: &mut impl Read,
    size: u64,
    mut destination: Option<&mut dyn Write>,
) -> Result<String> {
    let mut hasher = file_hasher(size);

    let mut buffer = [0_u8; HASH_BUFFER_BYTES];
    let mut bytes_read = 0_u64;
    loop {
        let count = read_chunk(reader, &mut buffer)?;
        if count == 0 {
            break;
        }
        bytes_read = bytes_read
            .checked_add(count as u64)
            .ok_or_else(|| anyhow!("scoped file is too large to fingerprint"))?;
        hasher.update(&buffer[..count]);
        if let Some(destination) = destination.as_mut() {
            destination.write_all(&buffer[..count])?;
        }
    }
    if bytes_read != size {
        return Err(anyhow!(
            "scoped file changed while it was being fingerprinted (expected {size} bytes, read {bytes_read})"
        ));
    }

    Ok(finish_file_hash(hasher))
}

fn read_chunk(reader: &mut impl Read, buffer: &mut [u8]) -> io::Result<usize> {
    loop {
        match reader.read(buffer) {
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            result => return result,
        }
    }
}

fn file_hasher(size: u64) -> Sha1 {
    let mut hasher = Sha1::new();
    hasher.update(FILE_HASH_TAG);
    hasher.update([0]);
    hasher.update(size.to_be_bytes());
    hasher
}

fn finish_file_hash(hasher: Sha1) -> String {
    let mut digest = String::from("sha1-v1:");
    for byte in hasher.finalize() {
        use std::fmt::Write as _;
        write!(&mut digest, "{byte:02x}").expect("writing to String cannot fail");
    }
    digest
}

fn git_files(repository: &Path) -> Result<Option<Vec<String>>> {
    let root = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .current_dir(repository)
        .output();
    let root = match root {
        Ok(root) => root,
        Err(error) if repository.join(".git").exists() => {
            return Err(anyhow!(
                "Git is required to inventory {}: {error}",
                repository.display()
            ));
        }
        Err(_) => return Ok(None),
    };
    if !root.status.success() {
        if repository.join(".git").exists() {
            return Err(review_gates::invalid(format!(
                "Git review inventory could not resolve repository root {}",
                repository.display()
            )));
        }
        return Ok(None);
    }
    let git_root = PathBuf::from(String::from_utf8_lossy(&root.stdout).trim());
    if git_root.canonicalize().ok().as_deref() != Some(repository) {
        return Err(review_gates::invalid(format!(
            "review repository must be the Git worktree root: {}",
            repository.display()
        )));
    }
    let output = Command::new("git")
        .args([
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ])
        .current_dir(repository)
        .output()
        .context("failed to enumerate Git coverage paths")?;
    if !output.status.success() {
        return Err(anyhow!(
            "git ls-files failed while capturing review coverage"
        ));
    }
    let mut paths = Vec::new();
    for path in output
        .stdout
        .split(|byte| *byte == 0)
        .filter(|path| !path.is_empty())
    {
        let path = std::str::from_utf8(path)
            .map_err(|_| anyhow!("Git contains a non-UTF-8 path in the review scope"))?;
        paths.push(path.to_string());
    }
    Ok(Some(paths))
}

fn within_roots(path: &str, roots: &[String]) -> bool {
    roots.iter().any(|root| covers(root, path))
}

fn covers(root: &str, path: &str) -> bool {
    root == "." || root == path || path.starts_with(&format!("{}/", root.trim_end_matches('/')))
}

fn excluded(path: &str, excludes: &[String]) -> bool {
    excludes.iter().any(|root| covers(root, path))
}

fn under_working(repository: &Path, working: &Path, relative: &str) -> bool {
    let working = if working.is_absolute() {
        working.to_path_buf()
    } else {
        repository.join(working)
    };
    let candidate = repository.join(relative);
    candidate.starts_with(working)
}

fn generated(relative: &str) -> bool {
    if relative == ".git" || relative.starts_with(".git/") {
        return true;
    }
    let name = Path::new(relative)
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default();
    matches!(
        name,
        ".varde-workflow.lock" | ".varde-workflow-journal.json" | ".varde-workflow-conclusion.json"
    ) || stage_name(name)
}

fn stage_name(name: &str) -> bool {
    if let Some((target, pid)) = name.rsplit_once(".md.varde-stage-") {
        return !target.is_empty()
            && !pid.is_empty()
            && pid.bytes().all(|byte| byte.is_ascii_digit());
    }
    if let Some(suffix) = name.strip_prefix(".varde-conclusion-") {
        let mut fields = suffix.split('-');
        return fields.next().is_some_and(|value| {
            !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_digit())
        }) && fields.next().is_some_and(|value| {
            !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_digit())
        }) && fields.next().is_none();
    }
    false
}

fn is_file_or_link(path: &Path) -> bool {
    fs::symlink_metadata(path)
        .is_ok_and(|metadata| metadata.is_file() || metadata.file_type().is_symlink())
}

fn reject_special_entries(
    repository: &Path,
    working: &Path,
    relative: &str,
    excludes: &[String],
) -> Result<()> {
    if excluded(relative, excludes)
        || generated(relative)
        || under_working(repository, working, relative)
    {
        return Ok(());
    }
    reject_symlink_ancestors(repository, relative)?;
    let path = repository.join(relative);
    let metadata = match fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.into()),
    };
    if metadata.is_file() || metadata.file_type().is_symlink() {
        return Ok(());
    }
    if !metadata.is_dir() {
        return Err(review_gates::invalid(format!(
            "special filesystem entry `{relative}` is not supported in a review baseline"
        )));
    }

    let mut children = fs::read_dir(&path)?
        .map(|entry| entry.map(|entry| entry.file_name()))
        .collect::<std::result::Result<Vec<_>, _>>()?;
    children.sort();
    for child in children {
        let child_name = child
            .to_str()
            .ok_or_else(|| anyhow!("review scope path is not UTF-8"))?;
        let child_relative = if relative == "." {
            child_name.to_string()
        } else {
            format!("{relative}/{child_name}")
        };
        reject_special_entries(repository, working, &child_relative, excludes)?;
    }
    Ok(())
}

fn add_current_path(
    repository: &Path,
    relative: &str,
    entries: &mut BTreeMap<String, CurrentEntry>,
) -> Result<()> {
    reject_symlink_ancestors(repository, relative)?;
    let path = repository.join(relative);
    let metadata = match fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.into()),
    };
    let (entry_type, sha1, size, symlink_target, content_path) =
        if metadata.file_type().is_symlink() {
            let target = fs::read_link(&path)?;
            let target = target
                .to_str()
                .ok_or_else(|| {
                    review_gates::invalid(format!("symlink target for `{relative}` is not UTF-8"))
                })?
                .to_string();
            let sha1 = review_contract::hash_bytes(FILE_HASH_TAG, target.as_bytes());
            let size = target.len() as u64;
            ("symlink", Some(sha1), Some(size), Some(target), None)
        } else if metadata.is_file() {
            let (sha1, size) = hash_file(&path)
                .with_context(|| format!("failed to fingerprint scoped file `{relative}`"))?;
            ("file", Some(sha1), Some(size), None, Some(path.clone()))
        } else if metadata.is_dir() {
            if relative != "." && path.join(".git").exists() {
                return Err(review_gates::invalid(format!(
                    "submodule directory `{relative}` is not supported in a review baseline"
                )));
            }
            ("directory", None, None, None, None)
        } else {
            return Err(review_gates::invalid(format!(
                "special filesystem entry `{relative}` is not supported in a review baseline"
            )));
        };
    let mode = file_mode(&metadata);
    entries.insert(
        relative.to_string(),
        CurrentEntry {
            snapshot: SnapshotEntry {
                entry_type: entry_type.to_string(),
                sha1,
                size,
                mode,
                symlink_target,
                content_path,
            },
        },
    );
    Ok(())
}

fn reject_symlink_ancestors(repository: &Path, relative: &str) -> Result<()> {
    let mut cursor = PathBuf::new();
    let components: Vec<_> = Path::new(relative).components().collect();
    for component in components.iter().take(components.len().saturating_sub(1)) {
        cursor.push(component.as_os_str());
        let path = repository.join(&cursor);
        if fs::symlink_metadata(&path).is_ok_and(|metadata| metadata.file_type().is_symlink()) {
            return Err(review_gates::invalid(format!(
                "review scope path `{relative}` traverses a symlink directory"
            )));
        }
    }
    Ok(())
}

fn add_parent_directories(
    repository: &Path,
    relative: &str,
    entries: &mut BTreeMap<String, CurrentEntry>,
) -> Result<()> {
    let mut path = Path::new(relative).parent();
    while let Some(parent) = path {
        if parent.as_os_str().is_empty() || parent == Path::new(".") {
            break;
        }
        let value = parent
            .to_str()
            .ok_or_else(|| anyhow!("review scope path is not UTF-8"))?;
        if !entries.contains_key(value) {
            add_current_path(repository, value, entries)?;
        }
        path = parent.parent();
    }
    Ok(())
}

fn walk(
    repository: &Path,
    working: &Path,
    relative: &str,
    excludes: &[String],
    entries: &mut BTreeMap<String, CurrentEntry>,
) -> Result<()> {
    if excluded(relative, excludes)
        || generated(relative)
        || under_working(repository, working, relative)
    {
        return Ok(());
    }
    let path = repository.join(relative);
    let metadata = match fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.into()),
    };
    add_current_path(repository, relative, entries)?;
    if metadata.is_dir() && !metadata.file_type().is_symlink() {
        let mut children = fs::read_dir(&path)?
            .map(|entry| entry.map(|entry| entry.file_name()))
            .collect::<std::result::Result<Vec<_>, _>>()?;
        children.sort();
        for child in children {
            let child_name = child
                .to_str()
                .ok_or_else(|| anyhow!("review scope path is not UTF-8"))?;
            let child_relative = if relative == "." {
                child_name.to_string()
            } else {
                format!("{relative}/{child_name}")
            };
            walk(repository, working, &child_relative, excludes, entries)?;
        }
    }
    Ok(())
}

#[cfg(unix)]
fn file_mode(metadata: &fs::Metadata) -> Option<u32> {
    use std::os::unix::fs::PermissionsExt;
    Some(metadata.permissions().mode() & 0o111)
}

#[cfg(not(unix))]
fn file_mode(_metadata: &fs::Metadata) -> Option<u32> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TrackingReader {
        inner: io::Cursor<Vec<u8>>,
        max_read: usize,
        calls: usize,
    }

    impl io::Read for TrackingReader {
        fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
            self.max_read = self.max_read.max(buffer.len());
            self.calls += 1;
            self.inner.read(buffer)
        }
    }

    #[test]
    fn review_file_hash_streams_fixed_size_chunks_with_the_existing_fingerprint() {
        let bytes = (0..(64 * 1024 * 3 + 17))
            .map(|index| (index % 251) as u8)
            .collect::<Vec<_>>();
        let expected = review_contract::hash_bytes(b"review-file-v1", &bytes);
        let mut reader = TrackingReader {
            inner: io::Cursor::new(bytes.clone()),
            max_read: 0,
            calls: 0,
        };

        let actual = hash_reader(&mut reader, bytes.len() as u64).unwrap();

        assert_eq!(actual, expected);
        assert_eq!(reader.max_read, 64 * 1024);
        assert!(reader.calls > 1);
    }

    #[test]
    fn current_entry_retains_only_manifest_metadata() {
        assert_eq!(
            std::mem::size_of::<CurrentEntry>(),
            std::mem::size_of::<SnapshotEntry>()
        );
    }
}
