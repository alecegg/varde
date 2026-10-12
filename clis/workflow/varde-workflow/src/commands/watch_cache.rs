//! Versioned per-watcher cache of the last emitted plan states.
//!
//! Each watcher keys its cache by its own `--notes` path so two sessions
//! watching one working store each emit a transition exactly once. A missing,
//! unparsable, or older-version file reads as absent: the next tick emits the
//! current states once and rewrites the file.

use super::watch::PlanState;
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use sha1::{Digest, Sha1};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

/// Schema version. Bump when the cache layout changes.
pub(super) const VERSION: u32 = 2;

/// The last state a watcher emitted for one plan.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct CachedPlan {
    pub(super) state: PlanState,
    /// `floor(idle / threshold)` for stale, `floor(idle / 3 * threshold)` for
    /// merge-ready, `0` otherwise. A new bucket re-emits the event.
    pub(super) bucket: u64,
    /// Task ids already announced as blocked, so a re-tick stays quiet.
    #[serde(default)]
    pub(super) blocked: BTreeSet<String>,
    /// Whether the plan was idle without a later owner message.
    #[serde(default)]
    pub(super) idle_no_handback: bool,
}

/// Every plan a watcher emitted, keyed by plan id.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct WatchCache {
    pub(super) version: u32,
    pub(super) plans: BTreeMap<String, CachedPlan>,
}

impl WatchCache {
    pub(super) fn new() -> Self {
        Self {
            version: VERSION,
            plans: BTreeMap::new(),
        }
    }
}

/// The cache file for one watcher: `<working>/.cache/plan-watch-<hash>.json`,
/// where `<hash>` is a short hash of the canonical `--notes` path or repo path.
#[cfg(test)]
pub(super) fn cache_path(working: &Path, notes: Option<&Path>) -> PathBuf {
    cache_path_for_repo(working, notes, &std::env::current_dir().unwrap_or_default())
}

pub(super) fn cache_path_for_repo(working: &Path, notes: Option<&Path>, repo: &Path) -> PathBuf {
    let key = match notes {
        Some(notes) => {
            // Resolve symlinks first so two names for one file share a cache.
            // When the file does not exist yet, canonicalize its parent so the
            // key cannot flip once watch creates the file.
            let resolved = match fs::canonicalize(notes) {
                Ok(real) => real,
                Err(_) => match (notes.parent(), notes.file_name()) {
                    (Some(parent), Some(name)) => fs::canonicalize(parent)
                        .map(|real_parent| real_parent.join(name))
                        .unwrap_or_else(|_| notes.to_path_buf()),
                    _ => notes.to_path_buf(),
                },
            };
            short_hash(resolved.as_os_str().to_string_lossy().as_bytes())
        }
        None => short_hash(
            &fs::canonicalize(repo)
                .unwrap_or_else(|_| repo.to_path_buf())
                .as_os_str()
                .to_string_lossy()
                .as_bytes(),
        ),
    };
    working
        .join(".cache")
        .join(format!("plan-watch-{key}.json"))
}

fn short_hash(bytes: &[u8]) -> String {
    let digest = Sha1::digest(bytes);
    format!("{digest:x}").chars().take(12).collect()
}

/// Read the cache. A missing, unparsable, or older-version file reads as
/// absent, which means "emit the current states once".
#[cfg(test)]
pub(super) fn read(working: &Path, notes: Option<&Path>) -> Option<WatchCache> {
    read_for_repo(working, notes, &std::env::current_dir().unwrap_or_default())
}

pub(super) fn read_for_repo(
    working: &Path,
    notes: Option<&Path>,
    repo: &Path,
) -> Option<WatchCache> {
    let bytes = fs::read(cache_path_for_repo(working, notes, repo)).ok()?;
    let cache: WatchCache = serde_json::from_slice(&bytes).ok()?;
    (cache.version == VERSION).then_some(cache)
}

/// Write the cache atomically, only when its bytes changed. Returns whether a
/// write happened.
#[cfg(test)]
pub(super) fn write_if_changed(
    working: &Path,
    notes: Option<&Path>,
    cache: &WatchCache,
) -> Result<bool> {
    write_if_changed_for_repo(
        working,
        notes,
        &std::env::current_dir().unwrap_or_default(),
        cache,
    )
}

pub(super) fn write_if_changed_for_repo(
    working: &Path,
    notes: Option<&Path>,
    repo: &Path,
    cache: &WatchCache,
) -> Result<bool> {
    let path = cache_path_for_repo(working, notes, repo);
    let mut bytes =
        serde_json::to_vec_pretty(cache).context("could not serialize the watch cache")?;
    bytes.push(b'\n');
    if fs::read(&path).is_ok_and(|current| current == bytes) {
        return Ok(false);
    }
    let parent = path.parent().context("watch cache path has no parent")?;
    fs::create_dir_all(parent).with_context(|| {
        format!(
            "could not create watch cache directory {}",
            parent.display()
        )
    })?;
    let filename = path
        .file_name()
        .and_then(|name| name.to_str())
        .context("watch cache path has an invalid filename")?;
    let temporary = parent.join(format!(".{filename}.{}.tmp", std::process::id()));
    let result = (|| {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(&temporary)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        fs::rename(&temporary, &path)
    })();
    if let Err(error) = result {
        let _ = fs::remove_file(&temporary);
        return Err(error).with_context(|| format!("could not write {}", path.display()));
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};
    use varde_workflow_core::memory::{
        LEGACY_HANDOFF_FILE, LEGACY_HANDOFFS_DIR, NOTES_FILE, SESSION_NOTES_DIR,
    };

    fn temp_dir(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "varde-watch-cache-{label}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    fn cache_for(state: PlanState, bucket: u64) -> WatchCache {
        let mut cache = WatchCache::new();
        cache.plans.insert(
            "plan-a".to_string(),
            CachedPlan {
                state,
                bucket,
                blocked: BTreeSet::from(["t1".to_string()]),
                idle_no_handback: false,
            },
        );
        cache
    }

    #[test]
    fn cache_path_uses_a_notes_hash_or_canonical_repo_hash() {
        let root = temp_dir("paths");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let other_repo = root.join("other-repo");
        fs::create_dir_all(&other_repo).unwrap();
        let default = cache_path_for_repo(&root, None, &repo);
        assert_ne!(default, cache_path_for_repo(&root, None, &other_repo));
        assert!(!default.to_string_lossy().contains("default"));

        let notes = root.join("notes.md");
        fs::write(&notes, "").unwrap();
        let first = cache_path(&root, Some(&notes));
        let second = cache_path(&root, Some(&notes));
        assert_eq!(first, second);
        assert_ne!(first, default);

        let other = root.join("other.md");
        assert_ne!(cache_path(&root, Some(&other)), first);

        // A path with an unresolved `.` component still keys to one cache.
        let dotted = root.join(".").join("notes.md");
        assert_eq!(cache_path(&root, Some(&dotted)), first);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn cache_key_is_stable_before_and_after_the_notes_file_exists() {
        let root = temp_dir("missing-notes");
        let notes = root.join("notes.md");
        assert!(!notes.exists());

        let before = cache_path(&root, Some(&notes));
        fs::write(&notes, "").unwrap();
        let after = cache_path(&root, Some(&notes));

        assert_eq!(before, after);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_missing_corrupt_or_old_cache_reads_as_absent() {
        let root = temp_dir("absent");
        let notes = root.join("notes.md");
        assert!(read(&root, Some(&notes)).is_none());

        let path = cache_path(&root, Some(&notes));
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, b"{not json").unwrap();
        assert!(read(&root, Some(&notes)).is_none());

        let mut old = cache_for(PlanState::Stale, 2);
        old.version = VERSION + 1;
        fs::write(&path, serde_json::to_vec(&old).unwrap()).unwrap();
        assert!(read(&root, Some(&notes)).is_none());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn the_cache_round_trips_and_is_written_only_when_changed() {
        let root = temp_dir("round-trip");
        let notes = root.join("notes.md");
        assert!(read(&root, Some(&notes)).is_none());

        let cache = cache_for(PlanState::MergeReady, 1);
        assert!(write_if_changed(&root, Some(&notes), &cache).unwrap());
        assert_eq!(read(&root, Some(&notes)), Some(cache.clone()));

        let before = fs::metadata(cache_path(&root, Some(&notes)))
            .unwrap()
            .modified()
            .unwrap();
        assert!(!write_if_changed(&root, Some(&notes), &cache).unwrap());
        let after = fs::metadata(cache_path(&root, Some(&notes)))
            .unwrap()
            .modified()
            .unwrap();
        assert_eq!(before, after);

        let changed = cache_for(PlanState::Stale, 3);
        assert!(write_if_changed(&root, Some(&notes), &changed).unwrap());
        assert_eq!(read(&root, Some(&notes)), Some(changed));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn two_notes_paths_write_two_caches() {
        let root = temp_dir("two-watchers");
        let first = root.join("one.md");
        let second = root.join("two.md");
        assert!(write_if_changed(&root, Some(&first), &cache_for(PlanState::Stale, 1)).unwrap());
        assert!(
            write_if_changed(&root, Some(&second), &cache_for(PlanState::MergeReady, 0)).unwrap()
        );
        assert_eq!(
            read(&root, Some(&first)).unwrap().plans["plan-a"].state,
            PlanState::Stale
        );
        assert_eq!(
            read(&root, Some(&second)).unwrap().plans["plan-a"].state,
            PlanState::MergeReady
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn changing_from_a_legacy_handoff_path_to_session_notes_starts_a_fresh_cache() {
        let root = temp_dir("session-notes-migration");
        let legacy = root
            .join(LEGACY_HANDOFFS_DIR)
            .join("session")
            .join(LEGACY_HANDOFF_FILE);
        let notes = root
            .join(SESSION_NOTES_DIR)
            .join("session")
            .join(NOTES_FILE);
        fs::create_dir_all(legacy.parent().unwrap()).unwrap();
        fs::create_dir_all(notes.parent().unwrap()).unwrap();
        fs::write(&legacy, "legacy").unwrap();
        fs::write(&notes, "migrated").unwrap();

        let cached = cache_for(PlanState::Stale, 1);
        assert!(write_if_changed(&root, Some(&legacy), &cached).unwrap());
        assert_eq!(read(&root, Some(&legacy)), Some(cached));

        assert_ne!(
            cache_path(&root, Some(&legacy)),
            cache_path(&root, Some(&notes))
        );
        assert!(read(&root, Some(&notes)).is_none());
        let regenerated = cache_for(PlanState::MergeReady, 0);
        assert!(write_if_changed(&root, Some(&notes), &regenerated).unwrap());
        assert_eq!(read(&root, Some(&notes)), Some(regenerated));
        fs::remove_dir_all(root).unwrap();
    }
}
