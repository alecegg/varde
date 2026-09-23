//! Recoverable staged filesystem writes.

use anyhow::{Context, Result, bail};
use fs4::FileExt;
use okf_core::memory::MemoryPaths;
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::fs::{self, File, OpenOptions};
use std::path::{Path, PathBuf};

const JOURNAL_NAME: &str = ".varde-workflow-journal.json";
const CONCLUSION_JOURNAL_NAME: &str = ".varde-workflow-conclusion.json";
const LOCK_NAME: &str = ".varde-workflow.lock";

#[derive(Debug)]
pub struct PendingWrite {
    pub target: PathBuf,
    pub content: Vec<u8>,
}

pub fn commit(target: &Path, content: &[u8]) -> Result<()> {
    commit_inner(target, content, None)
}

pub fn commit_expected(target: &Path, content: &[u8], expected_revision: &str) -> Result<()> {
    commit_inner(target, content, Some(expected_revision))
}

fn commit_inner(target: &Path, content: &[u8], expected_revision: Option<&str>) -> Result<()> {
    let root = target
        .parent()
        .context("artifact has no parent directory")?;
    let lock = acquire_lock(root)?;
    let source = fs::read(target)?;
    let source_hash = okf_core::occ::version(&source);
    if expected_revision.is_some_and(|expected| expected != source_hash) {
        release_lock(lock, root)?;
        bail!("artifact changed before staged write");
    }
    let stage = target.with_extension(format!("md.varde-stage-{}", std::process::id()));
    fs::write(&stage, content)?;

    let journal = json!({
        "version": 1,
        "phase": "staged",
        "target": target,
        "staging": stage,
        "source_hash": source_hash,
        "target_hash": okf_core::occ::version(content),
        "recovery_action": "commit",
    });
    fs::write(
        root.join(JOURNAL_NAME),
        serde_json::to_vec_pretty(&journal)?,
    )?;

    if std::env::var_os("VARDE_WORKFLOW_FAIL_AFTER_STAGE").is_some() {
        release_lock(lock, root)?;
        bail!("injected interruption after staging");
    }

    fs::rename(&stage, target)?;
    fs::remove_file(root.join(JOURNAL_NAME))?;
    release_lock(lock, root)?;
    Ok(())
}

pub fn recover(root: &Path) -> Result<bool> {
    if root.join(CONCLUSION_JOURNAL_NAME).exists() {
        recover_many(root)?;
        return Ok(true);
    }
    let journal_path = root.join(JOURNAL_NAME);
    if !journal_path.exists() {
        return Ok(false);
    }
    let lock = acquire_lock(root)?;
    let journal: Value = serde_json::from_slice(&fs::read(&journal_path)?)?;
    let target = path_field(&journal, "target")?;
    let stage = path_field(&journal, "staging")?;
    if let Err(error) = require_contained(root, &target, "target")
        .and_then(|()| require_contained(root, &stage, "staging"))
    {
        release_lock(lock, root)?;
        return Err(error);
    }
    let source_hash = string_field(&journal, "source_hash")?;
    let target_hash = string_field(&journal, "target_hash")?;
    let current_hash = okf_core::occ::version(&fs::read(&target)?);

    if current_hash == target_hash {
        if stage.exists() {
            fs::remove_file(&stage)?;
        }
    } else if current_hash == source_hash
        && stage.exists()
        && okf_core::occ::version(&fs::read(&stage)?) == target_hash
    {
        fs::rename(&stage, &target)?;
    } else {
        release_lock(lock, root)?;
        bail!("journal state does not match target or staging hashes");
    }

    fs::remove_file(journal_path)?;
    release_lock(lock, root)?;
    Ok(true)
}

/// Stage and commit every write atomically. The journal and lock live in
/// the project root; targets may land in the root or in any redirected
/// working/knowledge directory (see [`MemoryPaths::write_roots`]).
pub fn commit_many(memory: &MemoryPaths, writes: &[PendingWrite]) -> Result<()> {
    let root = memory.root.canonicalize()?;
    let write_roots = memory.write_roots();
    let lock = acquire_lock(&root)?;
    let resolved = match resolve_writes(&root, &write_roots, writes) {
        Ok(resolved) => resolved,
        Err(error) => {
            release_lock(lock, &root)?;
            return Err(error);
        }
    };
    let entries = stage_writes(&write_roots, resolved)?;
    let journal = conclusion_journal(entries);
    fs::write(
        root.join(CONCLUSION_JOURNAL_NAME),
        serde_json::to_vec_pretty(&journal)?,
    )?;

    if std::env::var_os("VARDE_WORKFLOW_FAIL_AFTER_CONCLUSION_STAGE").is_some() {
        release_lock(lock, &root)?;
        bail!("injected interruption after conclusion staging");
    }

    commit_journal_entries(&write_roots, &journal)?;
    fs::remove_file(root.join(CONCLUSION_JOURNAL_NAME))?;
    release_lock(lock, &root)?;
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

fn stage_writes(
    write_roots: &[PathBuf],
    resolved: Vec<(&PendingWrite, PathBuf)>,
) -> Result<Vec<Value>> {
    let mut entries = Vec::new();
    for (index, (write, target)) in resolved.into_iter().enumerate() {
        let parent = target.parent().context("conclusion target has no parent")?;
        fs::create_dir_all(parent)?;
        require_tree_contained(write_roots, parent, "target")?;
        let source_hash = if target.exists() {
            Some(okf_core::occ::version(&fs::read(&target)?))
        } else {
            None
        };
        let stage =
            target.with_extension(format!("varde-conclusion-{}-{index}", std::process::id()));
        fs::write(&stage, &write.content)?;
        entries.push(json!({
            "target": target,
            "staging": stage,
            "source_hash": source_hash,
            "target_hash": okf_core::occ::version(&write.content),
        }));
    }
    Ok(entries)
}

fn conclusion_journal(entries: Vec<Value>) -> Value {
    json!({
        "version": 1,
        "kind": "conclusion",
        "phase": "staged",
        "entries": entries,
        "recovery_action": "commit",
    })
}

fn recover_many(root: &Path) -> Result<()> {
    let root = root.canonicalize()?;
    let write_roots = MemoryPaths::resolve(&root)?.write_roots();
    let journal_path = root.join(CONCLUSION_JOURNAL_NAME);
    let lock = acquire_lock(&root)?;
    let journal: Value = serde_json::from_slice(&fs::read(&journal_path)?)?;
    commit_journal_entries(&write_roots, &journal)?;
    fs::remove_file(journal_path)?;
    release_lock(lock, &root)?;
    Ok(())
}

fn commit_journal_entries(write_roots: &[PathBuf], journal: &Value) -> Result<()> {
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
        let current_hash = target
            .exists()
            .then(|| fs::read(&target).map(|bytes| okf_core::occ::version(&bytes)))
            .transpose()?;

        if current_hash.as_deref() == Some(&target_hash) {
            if stage.exists() {
                fs::remove_file(stage)?;
            }
            continue;
        }
        if current_hash.as_deref() != source_hash {
            bail!("conclusion journal source changed for {}", target.display());
        }
        if !stage.exists() || okf_core::occ::version(&fs::read(&stage)?) != target_hash {
            bail!(
                "conclusion journal staging changed for {}",
                target.display()
            );
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
        let target = okf_core::memory::canonical_or_lexical(target);
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

fn acquire_lock(root: &Path) -> Result<File> {
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(root.join(LOCK_NAME))?;
    FileExt::lock(&file)?;
    Ok(file)
}

fn release_lock(file: File, root: &Path) -> Result<()> {
    FileExt::unlock(&file)?;
    drop(file);
    match fs::remove_file(root.join(LOCK_NAME)) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn string_field(value: &Value, field: &str) -> Result<String> {
    value[field]
        .as_str()
        .map(str::to_string)
        .with_context(|| format!("journal field `{field}` is missing"))
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
