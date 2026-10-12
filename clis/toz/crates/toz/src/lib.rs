#![cfg_attr(not(unix), allow(unused))]
#[cfg(not(unix))]
compile_error!("Toz supports macOS and Linux only (process groups, isatty, and hook plumbing are Unix-specific)");

mod cli;
mod commands;
mod diagnostics;
mod exec;
mod hook_input;
mod install;
mod machine;
mod sandbox;
mod worker;

use clap::Parser;
use std::ffi::OsString;
use std::process::ExitCode;

/// The clap command tree (hidden commands included), for tools that map it.
pub fn cli_command() -> clap::Command {
    <cli::Cli as clap::CommandFactory>::command()
}

/// Run the `varde-toz` CLI with `args` (including the program name) and
/// return its process exit code. The internal `__worker` mode is reachable
/// through the same entry.
pub fn run(args: Vec<OsString>, _io: &varde_contracts::Io<'_>) -> ExitCode {
    ExitCode::from(run_code(args) as u8)
}

pub use commands::{DoctorEntry, DoctorSection};

/// Like [`run`], with `section` added to the `doctor` report.
pub fn run_with_doctor_section(
    args: Vec<OsString>,
    io: &varde_contracts::Io<'_>,
    section: DoctorSection,
) -> ExitCode {
    let _ = commands::DOCTOR_SECTION.set(section);
    run(args, io)
}

/// Store `input` as a toz capture (as `toz capture --force --source <source>
/// --label <label>` would) and return the preview text, or `None` when nothing
/// was stored. `json` selects the `--json` preview shape; `defer_index`
/// mirrors `--defer-index`.
pub fn capture_forced(
    input: &mut impl std::io::Read,
    source: &str,
    label: &str,
    json: bool,
    defer_index: bool,
) -> anyhow::Result<Option<String>> {
    commands::capture_forced(input, source, label, json, defer_index)
}

/// Run `capture --hook --harness <harness>` on `payload` in-process and return the bytes to
/// print (empty when nothing is captured or on any error). `claude` means `claude-code`.
pub fn hook_capture(payload: &[u8], harness: &str) -> Vec<u8> {
    commands::hook_capture_bytes(payload, harness)
}

/// The text `note --harness <harness>` prints (a `SessionStart` JSON envelope for
/// `claude-code` and `codex`), without printing it.
pub fn note(harness: Option<&str>) -> String {
    commands::note_text(harness)
}

/// Remove the files `rels` under `dir` that the old per-feature Toz installer wrote, when
/// every existing one still matches its install manifest. Returns the files kept.
pub fn retire_legacy_files(
    dir: &std::path::Path,
    rels: &[&str],
) -> anyhow::Result<Vec<std::path::PathBuf>> {
    install::retire_owned_files(dir, rels)
}

/// Strip the old Toz hook entries and instruction block from a Codex home directory.
pub fn retire_legacy_codex(dir: &std::path::Path) -> anyhow::Result<()> {
    install::retire_codex_files(dir)
}

fn run_code(args: Vec<OsString>) -> i32 {
    if args.get(1).map(OsString::as_os_str) == Some(std::ffi::OsStr::new("__worker")) {
        match worker::worker_main() {
            Ok(code) => return code,
            Err(error) => {
                eprintln!("toz worker: {error:#}");
                return 2;
            }
        }
    }
    let args = cli::Cli::parse_from(args);
    // Hook mode must never fail the harness: a non-zero exit from a Claude Code PostToolUse hook
    // is reported to the model, which is worse than silently passing the original output through.
    let hook_mode = matches!(&args.cmd, cli::Command::Capture(a) if a.hook);
    let hook_harness = match &args.cmd {
        cli::Command::Capture(a) if a.hook => a.harness.clone(),
        _ => String::new(),
    };
    let result = if hook_mode {
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| commands::dispatch(args)))
            .unwrap_or_else(|_| Err(anyhow::anyhow!("panic inside hook")))
    } else {
        commands::dispatch(args)
    };
    match result {
        Ok(_) if hook_mode => 0,
        Ok(code) => code,
        Err(e) if hook_mode => {
            commands::log_hook_error(&e, &hook_harness);
            0
        }
        Err(e) => {
            eprintln!("varde-toz: {e:#}");
            2
        }
    }
}
