//! Best-effort watcher heartbeat, written by `_run-watcher` on every debounce
//! tick and read by `docwatch status --json`. Advisory only: a write failure
//! must never interrupt the watch loop, and a missing/stale file just means
//! "unknown health" to a reader, not an error condition.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WatcherState {
    pub last_tick_unix: u64,
    pub dispatching: bool,
    pub pending_count: usize,
}

/// A heartbeat older than this many seconds (relative to "now") is treated
/// as stale — the watcher likely died between ticks without cleaning up —
/// so a reader shouldn't trust a frozen `dispatching` flag past this point.
pub const STALE_AFTER_SECS: u64 = 120;

pub fn now_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

/// Best-effort write; callers swallow the error rather than let a heartbeat
/// failure take down the watch loop. Writes to a sibling `.tmp` and renames
/// over the target so a concurrent reader never sees a half-written file:
/// rename is atomic within a filesystem, so a reader gets either the old
/// state or the new one, never an empty/truncated one.
pub fn write(state_path: &Path, state: &WatcherState) -> std::io::Result<()> {
    if let Some(parent) = state_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let json = serde_json::to_string(state).unwrap_or_default();
    let tmp_path = state_path.with_extension("json.tmp");
    fs::write(&tmp_path, json)?;
    fs::rename(&tmp_path, state_path)
}

/// Stamp `now_unix()` and best-effort write a single heartbeat tick. Errors
/// are swallowed here so the debounce loop never has to care about them.
pub fn write_tick(state_path: &Path, dispatching: bool, pending_count: usize) {
    let _ = write(
        state_path,
        &WatcherState {
            last_tick_unix: now_unix(),
            dispatching,
            pending_count,
        },
    );
}

/// Read and parse `state_path`, returning `None` if it's missing or
/// unreadable/unparseable rather than erroring — a reader treats "no state"
/// the same as "unknown health".
pub fn read(state_path: &Path) -> Option<WatcherState> {
    let contents = fs::read_to_string(state_path).ok()?;
    serde_json::from_str(&contents).ok()
}

pub fn is_stale(state: &WatcherState, now: u64) -> bool {
    now.saturating_sub(state.last_tick_unix) > STALE_AFTER_SECS
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn write_then_read_round_trips() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("nested").join("state.json");
        let state = WatcherState {
            last_tick_unix: 1_704_067_200,
            dispatching: true,
            pending_count: 2,
        };
        write(&path, &state).unwrap();
        assert_eq!(read(&path), Some(state));
    }

    #[test]
    fn read_missing_file_returns_none() {
        let dir = tempdir().unwrap();
        assert_eq!(read(&dir.path().join("state.json")), None);
    }

    #[test]
    fn read_garbage_returns_none() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("state.json");
        fs::write(&path, "not json").unwrap();
        assert_eq!(read(&path), None);
    }

    #[test]
    fn is_stale_true_past_threshold() {
        let state = WatcherState {
            last_tick_unix: 1000,
            dispatching: false,
            pending_count: 0,
        };
        assert!(!is_stale(&state, 1000 + STALE_AFTER_SECS));
        assert!(is_stale(&state, 1000 + STALE_AFTER_SECS + 1));
    }
}
