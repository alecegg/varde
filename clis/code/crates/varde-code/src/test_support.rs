//! Shared test-only support for process-global environment overrides.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};
use varde_contracts::{CaptureInput, OutputCapture};

/// Acquire a poisoned HOME lock after its prior holder unwound.
pub(crate) fn home_lock() -> MutexGuard<'static, ()> {
    recover_lock(&crate::HOME_TEST_LOCK)
}

fn recover_lock(lock: &Mutex<()>) -> MutexGuard<'_, ()> {
    lock.lock().unwrap_or_else(|poison| poison.into_inner())
}

/// Holds the shared HOME lock while an override is active.
pub(crate) struct HomeOverride {
    previous_home: Option<OsString>,
    previous_xdg_config_home: Option<OsString>,
    previous_varde_config_dir: Option<OsString>,
    _lock: Option<MutexGuard<'static, ()>>,
}

impl HomeOverride {
    /// Redirect HOME and both Varde config-root variables under `path` until dropped.
    pub(crate) fn new(path: &Path) -> Self {
        let lock = home_lock();
        let (previous_home, previous_xdg_config_home, previous_varde_config_dir) =
            Self::set_roots(path);
        Self {
            previous_home,
            previous_xdg_config_home,
            previous_varde_config_dir,
            _lock: Some(lock),
        }
    }

    /// Redirect HOME and Varde config roots while the caller holds
    /// [`crate::HOME_TEST_LOCK`].
    ///
    /// This supports existing tests that need one lock around several setup
    /// and assertion phases. The caller's lock must outlive this guard.
    pub(crate) fn while_locked(path: &Path) -> Self {
        let (previous_home, previous_xdg_config_home, previous_varde_config_dir) =
            Self::set_roots(path);
        Self {
            previous_home,
            previous_xdg_config_home,
            previous_varde_config_dir,
            _lock: None,
        }
    }

    fn set_roots(path: &Path) -> (Option<OsString>, Option<OsString>, Option<OsString>) {
        let previous_home = std::env::var_os("HOME");
        let previous_xdg_config_home = std::env::var_os("XDG_CONFIG_HOME");
        let previous_varde_config_dir = std::env::var_os("VARDE_CONFIG_DIR");
        let xdg_config_home = path.join(".config");
        let varde_config_dir = xdg_config_home.join("varde");
        unsafe {
            std::env::set_var("HOME", path);
            std::env::set_var("XDG_CONFIG_HOME", xdg_config_home);
            std::env::set_var("VARDE_CONFIG_DIR", varde_config_dir);
        }
        (
            previous_home,
            previous_xdg_config_home,
            previous_varde_config_dir,
        )
    }
}

impl Drop for HomeOverride {
    fn drop(&mut self) {
        restore_env("VARDE_CONFIG_DIR", self.previous_varde_config_dir.take());
        restore_env("XDG_CONFIG_HOME", self.previous_xdg_config_home.take());
        restore_env("HOME", self.previous_home.take());
    }
}

fn restore_env(key: &str, value: Option<OsString>) {
    match value {
        Some(value) => unsafe { std::env::set_var(key, value) },
        None => unsafe { std::env::remove_var(key) },
    }
}

/// Holds [`crate::TOZ_ENV_TEST_LOCK`] while a fake capture implementation is
/// installed in [`crate::toz`], and restores the previous capture and
/// `VARDE_CODE_TOZ` on drop. The lock serializes this crate's capture-faking
/// tests against each other.
pub(crate) struct CaptureOverride {
    previous_capture: Option<&'static dyn OutputCapture>,
    previous_toz_env: Option<OsString>,
    _lock: MutexGuard<'static, ()>,
}

struct FakeCapture<F>(F);

impl<F> OutputCapture for FakeCapture<F>
where
    F: Fn(CaptureInput<'_>, &str, &str) -> Option<String> + Send + Sync,
{
    fn capture(&self, input: CaptureInput<'_>, source: &str, label: &str) -> Option<String> {
        (self.0)(input, source, label)
    }
}

impl CaptureOverride {
    /// Install a fake capture that answers every request with `fake`.
    pub(crate) fn with<F>(fake: F) -> Self
    where
        F: Fn(CaptureInput<'_>, &str, &str) -> Option<String> + Send + Sync + 'static,
    {
        let fake: &'static dyn OutputCapture = Box::leak(Box::new(FakeCapture(fake)));
        Self::set(Some(fake))
    }

    /// No capture implementation installed at all.
    pub(crate) fn none() -> Self {
        Self::set(None)
    }

    fn set(capture: Option<&'static dyn OutputCapture>) -> Self {
        let lock = recover_lock(&crate::TOZ_ENV_TEST_LOCK);
        let previous_capture = crate::toz::installed();
        let previous_toz_env = std::env::var_os("VARDE_CODE_TOZ");
        crate::toz::install_capture(capture);
        Self {
            previous_capture,
            previous_toz_env,
            _lock: lock,
        }
    }
}

impl Drop for CaptureOverride {
    fn drop(&mut self) {
        crate::toz::install_capture(self.previous_capture);
        match self.previous_toz_env.take() {
            Some(value) => unsafe { std::env::set_var("VARDE_CODE_TOZ", value) },
            None => unsafe { std::env::remove_var("VARDE_CODE_TOZ") },
        }
    }
}

/// Holds [`crate::TOZ_ENV_TEST_LOCK`] while `PATH` is prepended with a
/// stub-binary directory, and restores `PATH` on drop. Prepending (rather than
/// replacing) keeps every other binary resolvable.
pub(crate) struct PathOverride {
    previous_path: Option<OsString>,
    _lock: MutexGuard<'static, ()>,
}

impl PathOverride {
    /// Put `dir` first on `PATH` until this guard is dropped.
    pub(crate) fn new(dir: &Path) -> Self {
        let lock = recover_lock(&crate::TOZ_ENV_TEST_LOCK);
        let previous_path = std::env::var_os("PATH");
        let mut paths = vec![dir.to_path_buf()];
        if let Some(existing) = &previous_path {
            paths.extend(std::env::split_paths(existing));
        }
        let joined = std::env::join_paths(paths).expect("PATH entries join");
        unsafe { std::env::set_var("PATH", joined) };
        Self {
            previous_path,
            _lock: lock,
        }
    }
}

impl Drop for PathOverride {
    fn drop(&mut self) {
        match self.previous_path.take() {
            Some(path) => unsafe { std::env::set_var("PATH", path) },
            None => unsafe { std::env::remove_var("PATH") },
        }
    }
}

/// Run a test with a unique, temporary HOME directory.
pub(crate) fn with_isolated_home<F: FnOnce()>(label: &str, f: F) {
    let home = unique_home(label);
    std::fs::create_dir_all(&home).expect("home creates");
    {
        let _override = HomeOverride::new(&home);
        f();
    }
    let _ = std::fs::remove_dir_all(&home);
}

fn unique_home(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "varde-test-home-{label}-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock is after epoch")
            .as_nanos()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn home_override_restores_the_prior_value_after_a_panic() {
        let _lock = home_lock();
        let original_home = std::env::var_os("HOME");
        let original_xdg_config_home = std::env::var_os("XDG_CONFIG_HOME");
        let original_varde_config_dir = std::env::var_os("VARDE_CONFIG_DIR");
        let replacement = std::env::temp_dir().join("varde-test-home-restore");
        let expected_xdg_config_home = replacement.join(".config");
        let expected_varde_config_dir = expected_xdg_config_home.join("varde");

        let outcome = std::panic::catch_unwind(|| {
            let _override = HomeOverride::while_locked(&replacement);
            assert_eq!(std::env::var_os("HOME"), Some(replacement.into_os_string()));
            assert_eq!(
                std::env::var_os("XDG_CONFIG_HOME"),
                Some(expected_xdg_config_home.into_os_string())
            );
            assert_eq!(
                std::env::var_os("VARDE_CONFIG_DIR"),
                Some(expected_varde_config_dir.into_os_string())
            );
            panic!("expected test panic");
        });

        assert!(outcome.is_err());
        assert_eq!(std::env::var_os("HOME"), original_home);
        assert_eq!(
            std::env::var_os("XDG_CONFIG_HOME"),
            original_xdg_config_home
        );
        assert_eq!(
            std::env::var_os("VARDE_CONFIG_DIR"),
            original_varde_config_dir
        );
    }

    #[test]
    fn recover_lock_acquires_a_poisoned_mutex() {
        let lock = Mutex::new(());
        let _ = std::panic::catch_unwind(|| {
            let _guard = lock.lock().expect("fresh lock");
            panic!("poison the lock");
        });

        let _guard = recover_lock(&lock);
    }
}
