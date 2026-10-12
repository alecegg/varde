use std::sync::{Mutex, MutexGuard};

static PROCESS_ENV_LOCK: Mutex<()> = Mutex::new(());

fn process_env_guard() -> MutexGuard<'static, ()> {
    PROCESS_ENV_LOCK
        .lock()
        .unwrap_or_else(|error| error.into_inner())
}

#[path = "migrate_bins.rs"]
mod migrate_bins;
#[path = "migrate_config.rs"]
mod migrate_config;
#[path = "migrate_harness.rs"]
mod migrate_harness;
#[path = "migrate_watch.rs"]
mod migrate_watch;
#[path = "setup_autosave.rs"]
mod setup_autosave;
#[path = "setup_doctor_hooks.rs"]
mod setup_doctor_hooks;
#[path = "setup_hooks.rs"]
mod setup_hooks;
#[path = "session_notes_migrate.rs"]
mod session_notes_migrate;
