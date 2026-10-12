//! App crate: the only crate that depends on every module crate. It builds
//! the `Io` that module entry points receive and hosts the CLI binaries.

mod autosave;
mod contracts;
pub mod edit;
mod hook;
mod hooks_install;
pub mod migrate;
pub mod router;
pub mod search;
pub mod session_notes;
mod setup_session_notes;
pub mod sync;

pub use contracts::io;

/// Exit 0 quietly when printing to a closed stdout (for example `| head`).
/// Every other panic reaches the previous hook unchanged. `SIGPIPE` stays
/// ignored because child-process pipe handling depends on it.
pub fn install_closed_stdout_hook() {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let message = info
            .payload()
            .downcast_ref::<String>()
            .map(String::as_str)
            .or_else(|| info.payload().downcast_ref::<&str>().copied())
            .unwrap_or_default();
        if message.starts_with("failed printing to stdout") && message.contains("Broken pipe") {
            std::process::exit(0);
        }
        previous(info);
    }));
}
