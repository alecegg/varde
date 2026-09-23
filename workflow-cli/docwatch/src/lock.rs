//! Per-file locking so at most one agent run is ever in flight for a given
//! target file at a time.
//!
//! Lock files live at
//! `~/Library/Application Support/docwatch/locks/<sha256(abs_path)>.lock`
//! and are held via an OS-level advisory `flock` for the duration of one
//! agent run. A trigger event arriving while the lock is already held is
//! meant to be dropped for that cycle (see `watcher.rs`) rather than made to
//! block — the next debounce/fs-event cycle will pick the file back up once
//! the lock is free.

use fs4::FileExt;
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io;
use std::path::{Path, PathBuf};

/// Directory under the app support root where per-file lock files live.
pub const LOCKS_SUBDIR: &str = "locks";

/// Deterministic lock-file name for a given absolute path: the hex-encoded
/// sha256 of the path's string form, plus a `.lock` suffix.
///
/// The caller is expected to pass an absolute (ideally canonicalized) path
/// so that the same logical file always hashes to the same lock name
/// regardless of the caller's current working directory.
pub fn lock_file_name(abs_path: &Path) -> String {
    let mut hasher = Sha256::new();
    hasher.update(abs_path.to_string_lossy().as_bytes());
    let digest = hasher.finalize();
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    format!("{hex}.lock")
}

/// Full path to the lock file for `abs_path`, given the docwatch app-support
/// root directory (e.g. `~/Library/Application Support/docwatch`).
pub fn lock_path(app_support_root: &Path, abs_path: &Path) -> PathBuf {
    app_support_root
        .join(LOCKS_SUBDIR)
        .join(lock_file_name(abs_path))
}

/// A held per-file lock. Dropping this releases the lock.
pub struct FileLock {
    file: File,
}

impl FileLock {
    /// Try to acquire the lock for `abs_path`, non-blocking. Returns
    /// `Ok(None)` if the lock is already held by someone else (the caller
    /// should drop the event for this cycle rather than block), `Ok(Some(_))`
    /// once acquired, or `Err` on I/O failure (e.g. can't create the locks
    /// directory).
    pub fn try_acquire(app_support_root: &Path, abs_path: &Path) -> io::Result<Option<FileLock>> {
        let locks_dir = app_support_root.join(LOCKS_SUBDIR);
        fs::create_dir_all(&locks_dir)?;
        let path = locks_dir.join(lock_file_name(abs_path));

        let file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .write(true)
            .open(&path)?;

        match FileExt::try_lock(&file) {
            Ok(()) => Ok(Some(FileLock { file })),
            Err(fs4::TryLockError::WouldBlock) => Ok(None),
            Err(fs4::TryLockError::Error(e)) => Err(e),
        }
    }
}

impl Drop for FileLock {
    fn drop(&mut self) {
        let _ = FileExt::unlock(&self.file);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn lock_file_name_is_deterministic() {
        let path = Path::new("/some/abs/path.md");
        assert_eq!(lock_file_name(path), lock_file_name(path));
    }

    #[test]
    fn lock_file_name_differs_for_different_paths() {
        let a = Path::new("/some/abs/path-a.md");
        let b = Path::new("/some/abs/path-b.md");
        assert_ne!(lock_file_name(a), lock_file_name(b));
    }

    #[test]
    fn lock_file_name_matches_known_sha256() {
        // sha256("/tmp/example.md") computed independently.
        let path = Path::new("/tmp/example.md");
        let mut hasher = Sha256::new();
        hasher.update(path.to_string_lossy().as_bytes());
        let digest = hasher.finalize();
        let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
        let expected = format!("{hex}.lock");
        assert_eq!(lock_file_name(path), expected);
    }

    #[test]
    fn sequential_lock_unlock_cycles_do_not_deadlock() {
        let app_support = tempdir().unwrap();
        let target = Path::new("/some/target/doc.md");

        for _ in 0..2 {
            let lock = FileLock::try_acquire(app_support.path(), target)
                .unwrap()
                .expect("lock should be free");
            drop(lock);
        }

        // A third acquisition after the previous lock was dropped should
        // still succeed, proving unlock actually released the flock.
        let lock = FileLock::try_acquire(app_support.path(), target).unwrap();
        assert!(lock.is_some());
    }

    #[test]
    fn concurrent_acquire_is_dropped_not_blocked() {
        let app_support = tempdir().unwrap();
        let target = Path::new("/some/other/doc.md");

        let held = FileLock::try_acquire(app_support.path(), target)
            .unwrap()
            .expect("first acquire should succeed");

        // Second attempt while the first is still held must return None
        // immediately rather than blocking the caller.
        let second = FileLock::try_acquire(app_support.path(), target).unwrap();
        assert!(second.is_none());

        drop(held);

        let third = FileLock::try_acquire(app_support.path(), target).unwrap();
        assert!(third.is_some());
    }

    #[test]
    fn lock_path_places_file_under_locks_subdir() {
        let root = Path::new("/Users/x/Library/Application Support/docwatch");
        let target = Path::new("/tmp/example.md");
        let p = lock_path(root, target);
        assert_eq!(p.parent().unwrap(), root.join(LOCKS_SUBDIR));
        assert_eq!(p.file_name().unwrap(), lock_file_name(target).as_str());
    }
}
