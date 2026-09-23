//! `watchers.json` registry: source of truth for registered watchers.
//!
//! The registry is a JSON array of [`WatcherRegistration`] persisted at
//! `~/Library/Application Support/docwatch/watchers.json` (see
//! [`default_registry_path`]). All registry-mutating functions take an
//! explicit `registry_path: &Path` so tests can point them at a temp-dir
//! file instead of the real per-user path.

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WatcherRegistration {
    /// sha256(canonical folder path)[..12], stable per folder.
    pub id: String,
    /// Canonical, absolute path to the watched folder.
    pub folder: PathBuf,
    pub plist_path: PathBuf,
    pub log_dir: PathBuf,
    /// RFC3339 timestamp.
    pub added_at: String,
}

/// Default registry file location: `~/Library/Application Support/docwatch/watchers.json`.
pub fn default_registry_path() -> Result<PathBuf> {
    let home = std::env::var_os("HOME").context("HOME environment variable is not set")?;
    Ok(PathBuf::from(home)
        .join("Library")
        .join("Application Support")
        .join("docwatch")
        .join("watchers.json"))
}

/// sha256 of the canonicalized folder path, truncated to 12 hex chars.
pub fn compute_id(folder: &Path) -> String {
    let mut hasher = Sha256::new();
    hasher.update(folder.to_string_lossy().as_bytes());
    let digest = hasher.finalize();
    let hex = digest
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    hex[..12].to_string()
}

/// Best-effort RFC3339 (UTC) timestamp with no external time crate, since
/// docwatch only needs second-resolution display timestamps.
pub fn now_rfc3339() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format_rfc3339_utc(secs)
}

fn format_rfc3339_utc(total_secs: u64) -> String {
    const SECS_PER_DAY: u64 = 86_400;
    let days = total_secs / SECS_PER_DAY;
    let rem = total_secs % SECS_PER_DAY;
    let hour = rem / 3600;
    let minute = (rem % 3600) / 60;
    let second = rem % 60;

    // Civil-from-days algorithm (Howard Hinnant), days since 1970-01-01.
    let z = days as i64 + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };

    format!("{y:04}-{m:02}-{d:02}T{hour:02}:{minute:02}:{second:02}Z")
}

/// Load all registrations from `registry_path`. Returns an empty vec if the
/// file does not exist yet.
pub fn load(registry_path: &Path) -> Result<Vec<WatcherRegistration>> {
    if !registry_path.exists() {
        return Ok(Vec::new());
    }
    let contents = fs::read_to_string(registry_path)
        .with_context(|| format!("reading registry at {}", registry_path.display()))?;
    if contents.trim().is_empty() {
        return Ok(Vec::new());
    }
    let entries: Vec<WatcherRegistration> = serde_json::from_str(&contents)
        .with_context(|| format!("parsing registry at {}", registry_path.display()))?;
    Ok(entries)
}

/// Overwrite `registry_path` with `entries`, creating parent directories as
/// needed.
pub fn save(registry_path: &Path, entries: &[WatcherRegistration]) -> Result<()> {
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("creating registry directory {}", parent.display()))?;
    }
    let json = serde_json::to_string_pretty(entries).context("serializing registry")?;
    fs::write(registry_path, json)
        .with_context(|| format!("writing registry at {}", registry_path.display()))?;
    Ok(())
}

/// Find a registration by exact folder path or by id.
pub fn find<'a>(
    entries: &'a [WatcherRegistration],
    folder_or_id: &Path,
) -> Option<&'a WatcherRegistration> {
    let key_str = folder_or_id.to_string_lossy();
    entries
        .iter()
        .find(|e| e.folder == folder_or_id || e.id == key_str)
}

/// Register a new watcher for `folder`. Fails if `folder` is already
/// registered. Does not touch launchd/plist state — callers are expected to
/// write the plist/bootstrap the job around this call and roll back the
/// registry entry on failure.
pub fn add_entry(
    registry_path: &Path,
    folder: &Path,
    plist_path: PathBuf,
    log_dir: PathBuf,
) -> Result<WatcherRegistration> {
    let mut entries = load(registry_path)?;
    if entries.iter().any(|e| e.folder == folder) {
        bail!("{} is already registered", folder.display());
    }
    let id = compute_id(folder);
    if let Some(collision) = entries.iter().find(|e| e.id == id) {
        bail!(
            "id {id} for {} collides with existing registration {} — refusing to alias two folders to one launchd job",
            folder.display(),
            collision.folder.display()
        );
    }
    let entry = WatcherRegistration {
        id,
        folder: folder.to_path_buf(),
        plist_path,
        log_dir,
        added_at: now_rfc3339(),
    };
    entries.push(entry.clone());
    save(registry_path, &entries)?;
    Ok(entry)
}

/// Remove a registration matching `folder_or_id` (folder path or id).
/// Returns the removed entry, or an error if nothing matched.
pub fn remove_entry(registry_path: &Path, folder_or_id: &Path) -> Result<WatcherRegistration> {
    let mut entries = load(registry_path)?;
    let key_str = folder_or_id.to_string_lossy().into_owned();
    let idx = entries
        .iter()
        .position(|e| e.folder == folder_or_id || e.id == key_str)
        .with_context(|| format!("{} is not registered", folder_or_id.display()))?;
    let removed = entries.remove(idx);
    save(registry_path, &entries)?;
    Ok(removed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn reg_path(dir: &tempfile::TempDir) -> PathBuf {
        dir.path().join("watchers.json")
    }

    #[test]
    fn load_missing_file_returns_empty() {
        let dir = tempdir().unwrap();
        let entries = load(&reg_path(&dir)).unwrap();
        assert!(entries.is_empty());
    }

    #[test]
    fn add_then_load_round_trips() {
        let dir = tempdir().unwrap();
        let path = reg_path(&dir);
        let folder = dir.path().join("watched");
        fs::create_dir_all(&folder).unwrap();

        let entry = add_entry(
            &path,
            &folder,
            PathBuf::from("/plist"),
            PathBuf::from("/logs"),
        )
        .unwrap();

        let loaded = load(&path).unwrap();
        assert_eq!(loaded.len(), 1);
        assert_eq!(loaded[0], entry);
        assert_eq!(entry.id.len(), 12);
    }

    #[test]
    fn add_duplicate_folder_errors() {
        let dir = tempdir().unwrap();
        let path = reg_path(&dir);
        let folder = dir.path().join("watched");
        fs::create_dir_all(&folder).unwrap();

        add_entry(
            &path,
            &folder,
            PathBuf::from("/plist"),
            PathBuf::from("/logs"),
        )
        .unwrap();
        let err = add_entry(
            &path,
            &folder,
            PathBuf::from("/plist"),
            PathBuf::from("/logs"),
        )
        .unwrap_err();
        assert!(err.to_string().contains("already registered"));

        // No duplicate entry created.
        assert_eq!(load(&path).unwrap().len(), 1);
    }

    #[test]
    fn add_entry_rejects_id_collision_with_different_folder() {
        let dir = tempdir().unwrap();
        let path = reg_path(&dir);
        let folder_a = dir.path().join("a");
        let folder_b = dir.path().join("b");
        fs::create_dir_all(&folder_a).unwrap();
        fs::create_dir_all(&folder_b).unwrap();

        add_entry(&path, &folder_a, PathBuf::from("/pa"), PathBuf::from("/la")).unwrap();

        // Simulate a truncated-id collision: patch the just-added entry's id
        // to what folder_b's id would be, then try to add folder_b for real.
        let mut entries = load(&path).unwrap();
        entries[0].id = compute_id(&folder_b);
        save(&path, &entries).unwrap();

        let err =
            add_entry(&path, &folder_b, PathBuf::from("/pb"), PathBuf::from("/lb")).unwrap_err();
        assert!(err.to_string().contains("collides"), "got: {err}");

        // No new entry was added on top of the tampered one.
        assert_eq!(load(&path).unwrap().len(), 1);
    }

    #[test]
    fn remove_by_folder_removes_entry() {
        let dir = tempdir().unwrap();
        let path = reg_path(&dir);
        let folder = dir.path().join("watched");
        fs::create_dir_all(&folder).unwrap();

        add_entry(
            &path,
            &folder,
            PathBuf::from("/plist"),
            PathBuf::from("/logs"),
        )
        .unwrap();
        let removed = remove_entry(&path, &folder).unwrap();
        assert_eq!(removed.folder, folder);
        assert!(load(&path).unwrap().is_empty());
    }

    #[test]
    fn remove_by_id_removes_entry() {
        let dir = tempdir().unwrap();
        let path = reg_path(&dir);
        let folder = dir.path().join("watched");
        fs::create_dir_all(&folder).unwrap();

        let entry = add_entry(
            &path,
            &folder,
            PathBuf::from("/plist"),
            PathBuf::from("/logs"),
        )
        .unwrap();
        let removed = remove_entry(&path, Path::new(&entry.id)).unwrap();
        assert_eq!(removed.id, entry.id);
        assert!(load(&path).unwrap().is_empty());
    }

    #[test]
    fn remove_unregistered_errors() {
        let dir = tempdir().unwrap();
        let path = reg_path(&dir);
        let err = remove_entry(&path, Path::new("/nope")).unwrap_err();
        assert!(err.to_string().contains("not registered"));
    }

    #[test]
    fn list_returns_multiple_entries_in_order() {
        let dir = tempdir().unwrap();
        let path = reg_path(&dir);
        let folder_a = dir.path().join("a");
        let folder_b = dir.path().join("b");
        fs::create_dir_all(&folder_a).unwrap();
        fs::create_dir_all(&folder_b).unwrap();

        add_entry(&path, &folder_a, PathBuf::from("/pa"), PathBuf::from("/la")).unwrap();
        add_entry(&path, &folder_b, PathBuf::from("/pb"), PathBuf::from("/lb")).unwrap();

        let entries = load(&path).unwrap();
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].folder, folder_a);
        assert_eq!(entries[1].folder, folder_b);
    }

    #[test]
    fn compute_id_is_stable_and_distinct() {
        let a = compute_id(Path::new("/tmp/a"));
        let a2 = compute_id(Path::new("/tmp/a"));
        let b = compute_id(Path::new("/tmp/b"));
        assert_eq!(a, a2);
        assert_ne!(a, b);
        assert_eq!(a.len(), 12);
    }

    #[test]
    fn rfc3339_formats_known_epoch_seconds() {
        // 2024-01-01T00:00:00Z == 1704067200
        assert_eq!(format_rfc3339_utc(1_704_067_200), "2024-01-01T00:00:00Z");
        // 1970-01-01T00:00:00Z == 0
        assert_eq!(format_rfc3339_utc(0), "1970-01-01T00:00:00Z");
    }
}
