//! Watcher install/uninstall lifecycle: the multi-step registry <-> launchd
//! sequence (canonicalize -> derive paths -> write plist -> bootstrap ->
//! register, with ordered rollback on any failed step) extracted out of
//! `main.rs` so its ordering and rollback behavior are unit-testable with
//! injected hooks instead of living untested in the binary.
//!
//! This is deliberately not a general-purpose transaction abstraction —
//! there are only two operations, and each rollback step is best-effort
//! (logged by the caller, never itself propagated as the operation's error).

use crate::registry::{self, WatcherRegistration};
use anyhow::Result;
use std::path::{Path, PathBuf};

/// The side-effecting steps [`install_watcher`]/[`uninstall_watcher`] need,
/// injectable so tests can stub out real filesystem/launchd calls and assert
/// on step ordering and rollback instead.
pub trait InstallHooks {
    fn create_log_dir(&self, log_dir: &Path) -> Result<()>;
    fn write_plist(&self, plist_path: &Path, contents: &str) -> Result<()>;
    fn bootstrap(&self, plist_path: &Path) -> Result<()>;
    fn remove_plist(&self, plist_path: &Path) -> Result<()>;
    fn bootout(&self, id: &str, plist_path: &Path) -> Result<()>;
}

/// [`InstallHooks`] backed by the real filesystem and `launchctl`.
pub struct LaunchdHooks;

impl InstallHooks for LaunchdHooks {
    fn create_log_dir(&self, log_dir: &Path) -> Result<()> {
        std::fs::create_dir_all(log_dir)
            .map_err(|e| anyhow::anyhow!("creating log dir {}: {e}", log_dir.display()))
    }

    fn write_plist(&self, plist_path: &Path, contents: &str) -> Result<()> {
        crate::launchd::write_plist(plist_path, contents)
    }

    fn bootstrap(&self, plist_path: &Path) -> Result<()> {
        crate::launchd::bootstrap(plist_path)
    }

    fn remove_plist(&self, plist_path: &Path) -> Result<()> {
        crate::launchd::remove_plist(plist_path)
    }

    fn bootout(&self, id: &str, plist_path: &Path) -> Result<()> {
        crate::launchd::bootout(id, plist_path)
    }
}

/// The already-resolved paths/ids `install_watcher` needs. Callers derive
/// these first (canonicalize the folder, check for an existing registration,
/// compute the id, resolve `plist_path`/`log_dir`/`exe_path`) since those
/// steps are cheap, side-effect-free, and better validated before any
/// filesystem/launchd mutation starts.
pub struct InstallParams {
    pub folder: PathBuf,
    pub id: String,
    pub plist_path: PathBuf,
    pub log_dir: PathBuf,
    pub exe_path: PathBuf,
}

/// Install a watcher: create the log dir, write the plist, bootstrap it with
/// launchd, then persist the registry entry. Each step that fails after a
/// prior step succeeded triggers rollback of exactly what was already done
/// (in reverse order), so a failure never leaves an orphaned launchd job or
/// registry entry with no plist behind it.
pub fn install_watcher(
    registry_path: &Path,
    params: &InstallParams,
    hooks: &dyn InstallHooks,
) -> Result<WatcherRegistration> {
    hooks.create_log_dir(&params.log_dir)?;

    let plist_xml = crate::launchd::generate_plist(
        &params.id,
        &params.exe_path,
        &params.folder,
        &params.log_dir,
    );
    hooks.write_plist(&params.plist_path, &plist_xml)?;

    if let Err(e) = hooks.bootstrap(&params.plist_path) {
        let _ = hooks.remove_plist(&params.plist_path);
        return Err(e);
    }

    match registry::add_entry(
        registry_path,
        &params.folder,
        params.plist_path.clone(),
        params.log_dir.clone(),
    ) {
        Ok(entry) => Ok(entry),
        Err(e) => {
            let _ = hooks.bootout(&params.id, &params.plist_path);
            let _ = hooks.remove_plist(&params.plist_path);
            Err(e)
        }
    }
}

/// Uninstall a watcher: remove the registry entry, then tear down its
/// launchd job and plist. Bootout failure is non-fatal (best-effort — the
/// job may already be gone) but is returned to the caller to log as a
/// warning; plist removal failure is fatal, matching the prior `main.rs`
/// behavior (a leftover plist next to a bootstrapped-out job is worth
/// surfacing as an error, not silently swallowing).
pub fn uninstall_watcher(
    registry_path: &Path,
    folder_or_id: &Path,
    hooks: &dyn InstallHooks,
) -> Result<(WatcherRegistration, Option<anyhow::Error>)> {
    let removed = registry::remove_entry(registry_path, folder_or_id)?;

    let bootout_warning = hooks.bootout(&removed.id, &removed.plist_path).err();
    hooks.remove_plist(&removed.plist_path)?;

    Ok((removed, bootout_warning))
}

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::anyhow;
    use std::cell::RefCell;
    use tempfile::tempdir;

    #[derive(Default)]
    struct StubHooks {
        calls: RefCell<Vec<String>>,
        fail_bootstrap: bool,
    }

    impl InstallHooks for StubHooks {
        fn create_log_dir(&self, _log_dir: &Path) -> Result<()> {
            self.calls.borrow_mut().push("create_log_dir".into());
            Ok(())
        }
        fn write_plist(&self, _plist_path: &Path, _contents: &str) -> Result<()> {
            self.calls.borrow_mut().push("write_plist".into());
            Ok(())
        }
        fn bootstrap(&self, _plist_path: &Path) -> Result<()> {
            self.calls.borrow_mut().push("bootstrap".into());
            if self.fail_bootstrap {
                return Err(anyhow!("bootstrap failed"));
            }
            Ok(())
        }
        fn remove_plist(&self, _plist_path: &Path) -> Result<()> {
            self.calls.borrow_mut().push("remove_plist".into());
            Ok(())
        }
        fn bootout(&self, _id: &str, _plist_path: &Path) -> Result<()> {
            self.calls.borrow_mut().push("bootout".into());
            Ok(())
        }
    }

    fn params(folder: PathBuf) -> InstallParams {
        InstallParams {
            id: registry::compute_id(&folder),
            plist_path: folder.join("watcher.plist"),
            log_dir: folder.join("logs"),
            exe_path: folder.join("docwatch"),
            folder,
        }
    }

    #[test]
    fn install_runs_steps_in_order_and_persists_registry_entry() {
        let dir = tempdir().unwrap();
        let folder = dir.path().to_path_buf();
        let reg_path = folder.join("watchers.json");
        let hooks = StubHooks::default();

        let entry = install_watcher(&reg_path, &params(folder.clone()), &hooks).unwrap();

        assert_eq!(entry.folder, folder);
        assert_eq!(
            *hooks.calls.borrow(),
            vec!["create_log_dir", "write_plist", "bootstrap"]
        );
        let saved = registry::load(&reg_path).unwrap();
        assert_eq!(saved.len(), 1);
        assert_eq!(saved[0].id, entry.id);
    }

    #[test]
    fn install_rolls_back_plist_on_bootstrap_failure_without_touching_registry() {
        let dir = tempdir().unwrap();
        let folder = dir.path().to_path_buf();
        let reg_path = folder.join("watchers.json");
        let hooks = StubHooks {
            fail_bootstrap: true,
            ..Default::default()
        };

        let err = install_watcher(&reg_path, &params(folder.clone()), &hooks).unwrap_err();
        assert!(err.to_string().contains("bootstrap failed"));

        assert_eq!(
            *hooks.calls.borrow(),
            vec!["create_log_dir", "write_plist", "bootstrap", "remove_plist"]
        );
        // registry was never touched — add_entry is only reached after a
        // successful bootstrap.
        assert!(registry::load(&reg_path).unwrap().is_empty());
    }

    #[test]
    fn install_rolls_back_launchd_state_on_registry_add_failure() {
        let dir = tempdir().unwrap();
        let folder = dir.path().to_path_buf();
        let reg_path = folder.join("watchers.json");
        let hooks = StubHooks::default();
        let p = params(folder.clone());

        // Pre-register the same folder so `registry::add_entry` fails inside
        // `install_watcher`, exercising the bootout+remove_plist rollback
        // path (as opposed to the earlier bootstrap-failure rollback).
        registry::add_entry(
            &reg_path,
            &folder,
            folder.join("other.plist"),
            folder.join("other-logs"),
        )
        .unwrap();

        let err = install_watcher(&reg_path, &p, &hooks).unwrap_err();
        assert!(err.to_string().contains("already registered"));

        assert_eq!(
            *hooks.calls.borrow(),
            vec![
                "create_log_dir",
                "write_plist",
                "bootstrap",
                "bootout",
                "remove_plist"
            ]
        );
    }

    #[test]
    fn uninstall_removes_registry_entry_then_tears_down_launchd() {
        let dir = tempdir().unwrap();
        let folder = dir.path().to_path_buf();
        let reg_path = folder.join("watchers.json");
        let hooks = StubHooks::default();
        let entry = install_watcher(&reg_path, &params(folder.clone()), &hooks).unwrap();

        let (removed, bootout_warning) =
            uninstall_watcher(&reg_path, &entry.folder, &hooks).unwrap();

        assert_eq!(removed.id, entry.id);
        assert!(bootout_warning.is_none());
        assert!(registry::load(&reg_path).unwrap().is_empty());
        assert_eq!(
            hooks
                .calls
                .borrow()
                .iter()
                .skip(3)
                .cloned()
                .collect::<Vec<_>>(),
            vec!["bootout", "remove_plist"]
        );
    }
}
