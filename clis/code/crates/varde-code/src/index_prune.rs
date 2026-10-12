//! `prune` orchestration: remove index folders whose recorded source folder
//! is gone.
//!
//! Index folders live under `<config>/repos/<name>-<hash>/`, where `<hash>` is
//! a hash of the source root — so an orphaned folder cannot be proven an
//! orphan from its name. Every build records its source root in a
//! `source-root` sidecar ([`crate::db::path::record_source_root`]); prune
//! reads that sidecar and removes folders whose source folder no longer
//! exists.
//!
//! Classification per folder:
//!
//! - sidecar records a path that is gone (`NotFound`) → `source_missing`,
//!   removed.
//! - sidecar records a path that still exists → kept.
//! - no sidecar, or an empty/unreadable sidecar → `unknown`, kept unless the
//!   caller opts in with `unknownOlderThanDays` and the folder's `index.db`
//!   was last modified longer ago → `unknown_idle`, removed.
//! - a recorded path that cannot be inspected (permission denied) →
//!   `unknown`, always kept.
//! - repository lock held by a live process → skipped entirely.
//!
//! The default is a dry run: only `apply: true` deletes anything. A removal
//! that fails is reported in `failed` and the rest of the scan continues, so
//! the envelope still names the folders already removed. A wrong prune costs
//! a rebuild, never source data.

use crate::query::ApiError;
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};

const SOURCE_MISSING: &str = "source_missing";
const UNKNOWN_IDLE: &str = "unknown_idle";
const SECONDS_PER_DAY: u64 = 86_400;

/// Prune index folders under the conventional config root.
pub fn run(input: &Value) -> Result<Value, ApiError> {
    run_in(&crate::db::path::config_dir(), input)
}

/// Prune index folders under `config_dir`.
///
/// Split from [`run`] so integration tests can drive an explicit config root
/// without redirecting `HOME`.
pub fn run_in(config_dir: &Path, input: &Value) -> Result<Value, ApiError> {
    if !input.is_object() {
        return Err(ApiError::new(
            "invalid_input",
            "prune input must be a JSON object",
        ));
    }
    let apply = input.get("apply").and_then(Value::as_bool).unwrap_or(false);
    let older_than_days = match input.get("unknownOlderThanDays") {
        None | Some(Value::Null) => None,
        Some(value) => Some(value.as_u64().ok_or_else(|| {
            ApiError::new(
                "invalid_input",
                "unknownOlderThanDays must be a non-negative integer",
            )
        })?),
    };

    let outcome_key = if apply { "removed" } else { "wouldRemove" };
    let mut selected: Vec<Value> = Vec::new();
    let mut failed: Vec<Value> = Vec::new();
    let mut unknown: Vec<Value> = Vec::new();
    let mut kept_bytes: u64 = 0;
    let mut selected_bytes: u64 = 0;
    let mut scanned: u64 = 0;
    let mut locked: u64 = 0;
    let mut kept: u64 = 0;

    for folder in crate::db::path::list_index_folders(config_dir) {
        scanned += 1;
        let bytes = folder_bytes(&folder);
        // A live builder owns its folder's lock; a held lock leaves the
        // folder alone. The probe never creates the lock file: a dry run
        // would otherwise write `index.db.lock` into every scanned folder.
        //
        // Keep the probe's lock alive through this iteration's deletion: a
        // builder that acquired the lock between the probe and
        // `remove_dir_all` would otherwise have its folder deleted mid-build.
        // A builder blocked on this lock then sees the folder gone and
        // recreates it.
        let _probe_guard = match probe_lock(&folder.join("index.db")) {
            LockProbe::Held => {
                locked += 1;
                continue;
            }
            LockProbe::Free(guard) => guard,
        };

        let reason = match classify(&folder, older_than_days) {
            Classification::Keep => {
                kept += 1;
                kept_bytes += bytes;
                None
            }
            Classification::SourceMissing => Some(SOURCE_MISSING),
            Classification::UnknownIdle => Some(UNKNOWN_IDLE),
            Classification::Unknown => {
                kept_bytes += bytes;
                unknown.push(json!({
                    "folder": folder.to_string_lossy(),
                    "bytes": bytes,
                }));
                None
            }
        };

        if let Some(reason) = reason {
            if apply {
                // Report a failed removal and keep going: earlier folders are
                // already gone, and the caller needs to see what was reclaimed
                // as well as what failed.
                if let Err(err) = std::fs::remove_dir_all(&folder) {
                    failed.push(json!({
                        "folder": folder.to_string_lossy(),
                        "error": err.to_string(),
                    }));
                    continue;
                }
            }
            selected_bytes += bytes;
            selected.push(json!({
                "folder": folder.to_string_lossy(),
                "reason": reason,
                "bytes": bytes,
            }));
        }
    }

    let mut counts = serde_json::Map::new();
    counts.insert("scanned".to_string(), json!(scanned));
    counts.insert(outcome_key.to_string(), json!(selected.len() as u64));
    counts.insert("failed".to_string(), json!(failed.len() as u64));
    counts.insert("unknown".to_string(), json!(unknown.len() as u64));
    counts.insert("locked".to_string(), json!(locked));
    counts.insert("kept".to_string(), json!(kept));

    let mut data = serde_json::Map::new();
    data.insert("apply".to_string(), Value::Bool(apply));
    data.insert(outcome_key.to_string(), Value::Array(selected));
    data.insert("failed".to_string(), Value::Array(failed));
    data.insert("unknown".to_string(), Value::Array(unknown));
    data.insert("keptBytes".to_string(), json!(kept_bytes));
    data.insert("selectedBytes".to_string(), json!(selected_bytes));
    data.insert("counts".to_string(), Value::Object(counts));
    Ok(Value::Object(data))
}

/// What prune knows about one index folder.
enum Classification {
    /// The recorded source root still exists.
    Keep,
    /// The recorded source root is gone (`NotFound`).
    SourceMissing,
    /// No sidecar (or an unreadable one) and `index.db` is older than the
    /// caller's threshold.
    UnknownIdle,
    /// No sidecar (or an unreadable one) and not old enough to prune.
    Unknown,
}

fn classify(folder: &Path, older_than_days: Option<u64>) -> Classification {
    let recorded = match std::fs::read_to_string(folder.join(crate::db::path::SOURCE_ROOT_FILE)) {
        Ok(text) => text,
        Err(_) => return unknown_classification(folder, older_than_days),
    };
    let recorded = recorded.trim();
    if recorded.is_empty() {
        return unknown_classification(folder, older_than_days);
    }
    match std::fs::metadata(recorded) {
        Ok(_) => Classification::Keep,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Classification::SourceMissing,
        Err(_) => Classification::Unknown,
    }
}

fn unknown_classification(folder: &Path, older_than_days: Option<u64>) -> Classification {
    let Some(days) = older_than_days else {
        return Classification::Unknown;
    };
    let Ok(modified) = std::fs::metadata(folder.join("index.db")).and_then(|m| m.modified()) else {
        return Classification::Unknown;
    };
    let age = SystemTime::now()
        .duration_since(modified)
        .unwrap_or_default();
    if age >= Duration::from_secs(days.saturating_mul(SECONDS_PER_DAY)) {
        Classification::UnknownIdle
    } else {
        Classification::Unknown
    }
}

/// The result of probing an index folder's repository lock without creating
/// its lock file.
enum LockProbe {
    /// No live process holds the lock (or the lock file does not exist, so
    /// none can). The guard, when present, holds the exclusive lock so a
    /// builder cannot start before the caller releases it.
    Free(Option<ProbeGuard>),
    /// The lock is held by a live process: the folder must be left alone.
    Held,
}

/// The lock hold a successful probe returns. On unix the opened `File` is the
/// `flock`; on non-unix it is the exclusive-create guard.
#[cfg(unix)]
type ProbeGuard = std::fs::File;
#[cfg(not(unix))]
type ProbeGuard = crate::repo_lock::RepoLock;

/// Probe an index folder's repository lock without creating its lock file.
///
/// A lock file that does not exist means no one can hold the lock, so the
/// probe reports `Free(None)`. When the file exists and the `flock` succeeds,
/// the opened handle is returned as the guard so the caller can hold the lock
/// across a deletion; skipping this hold would let a builder start between the
/// probe and `remove_dir_all`.
///
/// [`crate::repo_lock::acquire`] cannot be used here: it opens the lock file
/// with `create`, so a dry run would write `index.db.lock` into every
/// scanned folder.
#[cfg(unix)]
fn probe_lock(index_db: &Path) -> LockProbe {
    use std::os::unix::io::AsRawFd;

    let lock_path = index_db.with_extension("db.lock");
    let file = match std::fs::OpenOptions::new().read(true).open(&lock_path) {
        Ok(file) => file,
        // No lock file, no lock; an unreadable lock file is likewise treated
        // as unlocked rather than as a blocker.
        Err(_) => return LockProbe::Free(None),
    };
    // SAFETY: `as_raw_fd` is valid for the lifetime of `file`; flock only
    // manipulates kernel lock state for that fd and never the file itself,
    // so opening read-only is sufficient to detect and hold a lock.
    let ret = unsafe { libc_flock(file.as_raw_fd(), LOCK_EX | LOCK_NB) };
    if ret == 0 {
        LockProbe::Free(Some(file))
    } else if std::io::Error::last_os_error().kind() == std::io::ErrorKind::WouldBlock {
        LockProbe::Held
    } else {
        LockProbe::Free(None)
    }
}

/// Non-unix fallback: the exclusive-create lock file is the platform's lock
/// mechanism, so existence is the only probe available. An existing file may
/// or may not be held; `repo_lock::acquire` with zero wait settles it, at the
/// cost of rewriting the holder PID.
#[cfg(not(unix))]
fn probe_lock(index_db: &Path) -> LockProbe {
    let lock_path = index_db.with_extension("db.lock");
    if !lock_path.exists() {
        return LockProbe::Free(None);
    }
    match crate::repo_lock::acquire(index_db, Duration::ZERO) {
        Ok(guard) => LockProbe::Free(Some(guard)),
        Err(_) => LockProbe::Held,
    }
}

const LOCK_EX: std::os::raw::c_int = 2;
const LOCK_NB: std::os::raw::c_int = 4;

// Raw `flock` FFI (mirrors `crate::repo_lock`'s alias to avoid clashing with
// any libc re-export in the crate).
#[cfg(unix)]
unsafe extern "C" {
    #[link_name = "flock"]
    fn libc_flock(fd: std::os::raw::c_int, operation: std::os::raw::c_int) -> std::os::raw::c_int;
}

/// Total byte size of every file under `folder`.
fn folder_bytes(folder: &Path) -> u64 {
    let mut total = 0u64;
    let mut stack: Vec<PathBuf> = vec![folder.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            match entry.file_type() {
                Ok(file_type) if file_type.is_dir() => stack.push(entry.path()),
                Ok(_) => {
                    if let Ok(metadata) = entry.metadata() {
                        total = total.saturating_add(metadata.len());
                    }
                }
                Err(_) => {}
            }
        }
    }
    total
}
