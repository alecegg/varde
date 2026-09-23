mod cli;

use clap::Parser;
use cli::{AddArgs, Cli, Command, ListArgs, LogsArgs, RemoveArgs, RunWatcherArgs, StatusArgs};
use docwatch::install::{InstallParams, LaunchdHooks};
use docwatch::watcher::RetryTracker;
use docwatch::{dispatcher, install, launchd, registry, state, watcher};
use serde_json::{Value, json};
use std::path::Path;
use std::process::ExitCode;

const ENVELOPE_SCHEMA_VERSION: u64 = 1;

fn main() -> ExitCode {
    let cli = Cli::parse();

    match cli.command {
        Command::Add(args) => cmd_add(args),
        Command::Remove(args) => cmd_remove(args),
        Command::List(args) => cmd_list(args),
        Command::Status(args) => cmd_status(args),
        Command::Logs(args) => cmd_logs(args),
        Command::RunWatcher(args) => cmd_run_watcher(args),
    }
}

fn registry_path() -> Result<std::path::PathBuf, ExitCode> {
    registry::default_registry_path().map_err(|e| {
        eprintln!("docwatch: {e:#}");
        ExitCode::FAILURE
    })
}

fn cmd_add(args: AddArgs) -> ExitCode {
    let Ok(reg_path) = registry_path() else {
        return ExitCode::FAILURE;
    };
    let Ok(folder) = add_folder(&args.path) else {
        return ExitCode::FAILURE;
    };
    let entries = match registry::load(&reg_path) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("docwatch add: {e:#}");
            return ExitCode::FAILURE;
        }
    };
    if let Some(existing) = registry::find(&entries, &folder) {
        eprintln!(
            "docwatch add: {} is already registered (id {})",
            folder.display(),
            existing.id
        );
        return ExitCode::FAILURE;
    }
    let Ok(params) = add_params(folder) else {
        return ExitCode::FAILURE;
    };
    match install::install_watcher(&reg_path, &params, &LaunchdHooks) {
        Ok(entry) => {
            println!("registered watcher {}", entry.id);
            println!("  folder: {}", entry.folder.display());
            println!("  log:    {}", entry.log_dir.join("watcher.log").display());
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("docwatch add: {e:#}");
            ExitCode::FAILURE
        }
    }
}

fn add_folder(path: &Path) -> Result<std::path::PathBuf, ExitCode> {
    match path.canonicalize() {
        Ok(folder) if folder.is_dir() => Ok(folder),
        Ok(_) => {
            eprintln!("docwatch add: {} is not a directory", path.display());
            Err(ExitCode::FAILURE)
        }
        Err(error) => {
            eprintln!("docwatch add: {} does not exist ({error})", path.display());
            Err(ExitCode::FAILURE)
        }
    }
}

fn add_params(folder: std::path::PathBuf) -> Result<InstallParams, ExitCode> {
    let id = registry::compute_id(&folder);
    let plist_path = add_path(launchd::default_plist_path(&id))?;
    let log_dir = add_path(launchd::default_log_dir(&id))?;
    let exe_path = std::env::current_exe().map_err(|error| {
        eprintln!(
            "docwatch add: could not resolve the running executable's path ({error}); refusing to register with an unresolvable plist path"
        );
        ExitCode::FAILURE
    })?;
    Ok(InstallParams {
        folder,
        id,
        plist_path,
        log_dir,
        exe_path,
    })
}

fn add_path<T>(result: anyhow::Result<T>) -> Result<T, ExitCode> {
    result.map_err(|error| {
        eprintln!("docwatch add: {error:#}");
        ExitCode::FAILURE
    })
}

fn print_json_success(data: Value) {
    println!("{}", success_envelope(data));
}

fn print_json_error(code: &str, message: impl Into<String>) {
    println!("{}", error_envelope(code, message));
}

fn success_envelope(data: Value) -> Value {
    json!({
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "ok": true,
        "outcome": "success",
        "data": data,
        "meta": {"compact": false, "truncated": false},
    })
}

fn error_envelope(code: &str, message: impl Into<String>) -> Value {
    json!({
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "ok": false,
        "outcome": "tool-error",
        "data": {"error": {"code": code, "message": message.into()}},
        "meta": {"compact": false, "truncated": false},
    })
}

fn cmd_remove(args: RemoveArgs) -> ExitCode {
    let Ok(reg_path) = registry_path() else {
        return ExitCode::FAILURE;
    };

    let key = resolve_key(&args.path);
    let (removed, bootout_warning) =
        match install::uninstall_watcher(&reg_path, &key, &LaunchdHooks) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("docwatch remove: {e:#}{}", not_registered_hint(&args.path));
                return ExitCode::FAILURE;
            }
        };

    if let Some(e) = bootout_warning {
        eprintln!("docwatch remove: warning: {e:#}");
    }

    println!(
        "removed watcher {} ({})",
        removed.id,
        removed.folder.display()
    );
    ExitCode::SUCCESS
}

fn cmd_list(args: ListArgs) -> ExitCode {
    let reg_path = match registry::default_registry_path() {
        Ok(path) => path,
        Err(error) => {
            if args.json {
                print_json_error("registry_error", format!("{error:#}"));
            } else {
                eprintln!("docwatch list: {error:#}");
            }
            return ExitCode::FAILURE;
        }
    };
    let entries = match registry::load(&reg_path) {
        Ok(e) => e,
        Err(e) => {
            if args.json {
                print_json_error("registry_error", format!("{e:#}"));
                return ExitCode::FAILURE;
            }
            eprintln!("docwatch list: {e:#}");
            return ExitCode::FAILURE;
        }
    };

    if args.json {
        let out: Vec<_> = entries
            .iter()
            .map(|entry| {
                let (running, pid) = match launchd::is_running(&entry.id) {
                    Ok(launchd::JobStatus::Running { pid }) => (Some(true), Some(pid)),
                    Ok(launchd::JobStatus::Stopped) => (Some(false), None),
                    Err(_) => (None, None),
                };
                serde_json::json!({
                    "id": entry.id,
                    "folder": entry.folder,
                    "running": running,
                    "pid": pid,
                    "added_at": entry.added_at,
                })
            })
            .collect();
        print_json_success(json!(out));
        return ExitCode::SUCCESS;
    }

    if entries.is_empty() {
        println!("no watchers registered");
        return ExitCode::SUCCESS;
    }

    println!("{:<14} {:<10} {:<40} ADDED_AT", "ID", "STATUS", "FOLDER");
    for entry in &entries {
        let status = match launchd::is_running(&entry.id) {
            Ok(launchd::JobStatus::Running { .. }) => "running",
            Ok(launchd::JobStatus::Stopped) => "stopped",
            Err(_) => "unknown",
        };
        println!(
            "{:<14} {:<10} {:<40} {}",
            entry.id,
            status,
            entry.folder.display(),
            entry.added_at
        );
    }
    ExitCode::SUCCESS
}

fn cmd_status(args: StatusArgs) -> ExitCode {
    let reg_path = match registry::default_registry_path() {
        Ok(path) => path,
        Err(error) => {
            if args.json {
                print_json_error("registry_error", format!("{error:#}"));
            } else {
                eprintln!("docwatch status: {error:#}");
            }
            return ExitCode::FAILURE;
        }
    };
    let entries = match registry::load(&reg_path) {
        Ok(e) => e,
        Err(e) => {
            if args.json {
                print_json_error("registry_error", format!("{e:#}"));
                return ExitCode::FAILURE;
            }
            eprintln!("docwatch status: {e:#}");
            return ExitCode::FAILURE;
        }
    };

    let key = resolve_key(&args.path);
    let Some(entry) = registry::find(&entries, &key) else {
        if args.json {
            print_json_error(
                "not_found",
                format!(
                    "{} is not registered{}",
                    args.path.display(),
                    not_registered_hint(&args.path)
                ),
            );
            return ExitCode::FAILURE;
        }
        eprintln!(
            "docwatch status: {} is not registered{}",
            args.path.display(),
            not_registered_hint(&args.path)
        );
        return ExitCode::FAILURE;
    };

    let (running, pid) = match launchd::is_running(&entry.id) {
        Ok(launchd::JobStatus::Running { pid }) => (Some(true), Some(pid)),
        Ok(launchd::JobStatus::Stopped) => (Some(false), None),
        Err(_) => (None, None),
    };

    let state_path = entry.log_dir.join("state.json");
    let now = state::now_unix();
    let heartbeat = state::read(&state_path);

    if args.json {
        print_status_json(entry, running, pid, heartbeat.as_ref(), now);
        return ExitCode::SUCCESS;
    }
    print_process_status(running, pid);
    print_queue_status(heartbeat.as_ref(), now);
    print_recent_log(&entry.log_dir.join("watcher.log"));
    ExitCode::SUCCESS
}

fn print_status_json(
    entry: &registry::WatcherRegistration,
    running: Option<bool>,
    pid: Option<u32>,
    heartbeat: Option<&state::WatcherState>,
    now: u64,
) {
    let heartbeat = heartbeat.map(|state| {
        json!({
            "last_tick_unix": state.last_tick_unix,
            "dispatching": state.dispatching,
            "pending_count": state.pending_count,
            "stale": state::is_stale(state, now),
            "last_dispatch_error": state.last_dispatch_error,
        })
    });
    let output = json!({
        "id": entry.id,
        "folder": entry.folder,
        "running": running,
        "pid": pid,
        "heartbeat": heartbeat,
    });
    print_json_success(output);
}

fn print_process_status(running: Option<bool>, pid: Option<u32>) {
    match (running, pid) {
        (Some(true), Some(pid)) => println!("running (pid {pid})"),
        (Some(false), _) => println!("stopped"),
        _ => println!("status unknown"),
    }
}

fn print_queue_status(heartbeat: Option<&state::WatcherState>, now: u64) {
    match heartbeat {
        Some(value) if value.dispatching && state::is_stale(value, now) => println!(
            "queue: dispatch stuck ({} pending, last tick {}s ago)",
            value.pending_count,
            now.saturating_sub(value.last_tick_unix)
        ),
        Some(value) if value.dispatching => {
            println!("queue: dispatching ({} pending)", value.pending_count)
        }
        Some(_) => println!("queue: idle"),
        None => println!("queue: unknown (no heartbeat yet)"),
    }
    if let Some(error) = heartbeat.and_then(|value| value.last_dispatch_error.as_deref()) {
        println!("last dispatch error: {error}");
    }
}

fn print_recent_log(log_path: &Path) {
    match launchd::tail_log(log_path, 20) {
        Ok(lines) if lines.is_empty() => println!("(no log output yet: {})", log_path.display()),
        Ok(lines) => {
            println!(
                "--- last {} line(s) of {} ---",
                lines.len(),
                log_path.display()
            );
            for line in lines {
                println!("{line}");
            }
        }
        Err(e) => eprintln!("docwatch status: {e:#}"),
    }
}

fn cmd_logs(args: LogsArgs) -> ExitCode {
    let Ok(reg_path) = registry_path() else {
        return ExitCode::FAILURE;
    };
    let entries = match registry::load(&reg_path) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("docwatch logs: {e:#}");
            return ExitCode::FAILURE;
        }
    };

    let key = resolve_key(&args.path);
    let Some(entry) = registry::find(&entries, &key) else {
        eprintln!(
            "docwatch logs: {} is not registered{}",
            args.path.display(),
            not_registered_hint(&args.path)
        );
        return ExitCode::FAILURE;
    };

    let log_path = entry.log_dir.join("watcher.log");
    match launchd::tail_log(&log_path, args.lines) {
        Ok(lines) if lines.is_empty() => {
            println!("(no log output yet: {})", log_path.display());
            ExitCode::SUCCESS
        }
        Ok(lines) => {
            for line in lines {
                println!("{line}");
            }
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("docwatch logs: {e:#}");
            ExitCode::FAILURE
        }
    }
}

/// `add`/`remove`/`status`/`logs` accept either a folder path or a bare id.
/// Registry lookups compare against canonicalized folder paths, so try to
/// canonicalize; if that fails (e.g. the folder was removed from disk, or
/// the argument is actually an id), fall back to the raw argument.
fn resolve_key(path: &Path) -> std::path::PathBuf {
    path.canonicalize().unwrap_or_else(|_| path.to_path_buf())
}

/// True if `path` failed to canonicalize, i.e. it doesn't exist on disk
/// (as opposed to being a bare registration id, which also won't
/// canonicalize but is expected not to exist as a path).
fn is_missing_path(path: &Path) -> bool {
    path.canonicalize().is_err() && path.components().count() > 1
}

/// Append a hint to use the registration id when `path` looks like a
/// folder that was deleted from disk rather than a bare id, so
/// `remove`/`status` on a deleted folder doesn't just say "not registered"
/// with no path forward. See `docwatch list` for ids.
fn not_registered_hint(path: &Path) -> &'static str {
    if is_missing_path(path) {
        " (folder no longer exists on disk — pass the registration id instead; see `docwatch list`)"
    } else {
        ""
    }
}

/// The actual long-running watch loop launchd execs via the generated
/// plist's `_run-watcher --folder <path> --id <id>` `ProgramArguments`.
/// Wires watcher::run (debounced fs watch -> trigger parse) into
/// watcher::dispatch_pending (agent dispatch -> change-scope guard ->
/// retry-cap), never returning under normal operation.
fn cmd_run_watcher(args: RunWatcherArgs) -> ExitCode {
    let Ok((folder, app_support_root, log_dir)) = watcher_paths(&args) else {
        return ExitCode::FAILURE;
    };
    let log_path = log_dir.join("watcher.log");
    let state_path = log_dir.join("state.json");

    let repo_root = dispatcher::resolve_repo_root(&folder);
    let mut tracker = RetryTracker::default();

    let result = watcher::run(&folder, &app_support_root, |path, tasks| {
        if tasks.is_empty() {
            tracker.reconcile_path(path, &tasks);
            state::write_tick(&state_path, false, 0);
            return;
        }
        state::write_tick(&state_path, true, tasks.len());
        let last_dispatch_error = watcher::dispatch_pending(
            &repo_root,
            path,
            tasks,
            &log_path,
            &mut tracker,
            &mut |agent, file, watched_folder| dispatcher::dispatch(agent, file, watched_folder),
        );
        state::write_tick_with_error(&state_path, false, 0, last_dispatch_error);
    });

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("docwatch _run-watcher: watch loop error: {e}");
            ExitCode::FAILURE
        }
    }
}

fn watcher_paths(
    args: &RunWatcherArgs,
) -> Result<(std::path::PathBuf, std::path::PathBuf, std::path::PathBuf), ExitCode> {
    let folder = args.folder.canonicalize().map_err(|error| {
        eprintln!(
            "docwatch _run-watcher: {} does not exist ({error})",
            args.folder.display()
        );
        ExitCode::FAILURE
    })?;
    let registry_path = registry::default_registry_path().map_err(watcher_path_error)?;
    let app_support_root = registry_path
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or(registry_path);
    let log_dir = launchd::default_log_dir(&args.id).map_err(watcher_path_error)?;
    Ok((folder, app_support_root, log_dir))
}

fn watcher_path_error(error: anyhow::Error) -> ExitCode {
    eprintln!("docwatch _run-watcher: {error:#}");
    ExitCode::FAILURE
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn success_envelope_wraps_legacy_payload() {
        let envelope = success_envelope(json!([{"id": "abc"}]));

        assert_eq!(envelope["schema_version"], 1);
        assert_eq!(envelope["ok"], true);
        assert_eq!(envelope["outcome"], "success");
        assert_eq!(envelope["data"][0]["id"], "abc");
        assert_eq!(envelope["meta"]["truncated"], false);
    }

    #[test]
    fn error_envelope_uses_shared_error_shape() {
        let envelope = error_envelope("not_found", "watcher missing");

        assert_eq!(envelope["schema_version"], 1);
        assert_eq!(envelope["ok"], false);
        assert_eq!(envelope["outcome"], "tool-error");
        assert_eq!(envelope["data"]["error"]["code"], "not_found");
        assert_eq!(envelope["data"]["error"]["message"], "watcher missing");
    }
}
