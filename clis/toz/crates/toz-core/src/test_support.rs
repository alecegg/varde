//! Test-only helpers shared across toz-core test modules.

use std::sync::{Mutex, MutexGuard};

/// Serializes tests that mutate process-wide environment variables.
///
/// `cargo test` runs tests in parallel threads, and the config roots (`TOZ_CONFIG_DIR`,
/// `VARDE_TOZ_CONFIG_DIR`, `XDG_CONFIG_HOME`, `TOZ_FALLBACK_DIR`) are process-wide. Every test
/// that sets one must hold this lock; it lives here rather than in each module so the `fetch`
/// and `project` tests cannot race each other.
pub(crate) static ENV_LOCK: Mutex<()> = Mutex::new(());

/// Locks [`ENV_LOCK`], ignoring poison so one failing test does not fail every later one.
pub(crate) fn env_lock() -> MutexGuard<'static, ()> {
    ENV_LOCK
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}
