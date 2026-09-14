mod cli;

use clap::Parser;
use cli::{AddArgs, Cli, Command, ListArgs, LogsArgs, RemoveArgs, RunWatcherArgs, StatusArgs};
use docwatch::install::{InstallParams, LaunchdHooks};
use docwatch::watcher::RetryTracker;
use docwatch::{dispatcher, install, launchd, registry, state, watcher};
use std::path::Path;
use std::process::ExitCode;

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

    let folder = match args.path.canonicalize() {
        Ok(p) if p.is_dir() => p,
        Ok(_) => {
            eprintln!("docwatch add: {} is not a directory", args.path.display());
            return ExitCode::FAILURE;
        }
        Err(e) => {
            eprintln!("docwatch add: {} does not exist ({e})", args.path.display());
            return ExitCode::FAILURE;
        }
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

    let id = registry::compute_id(&folder);
    let plist_path = match launchd::default_plist_path(&id) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("docwatch add: {e:#}");
            return ExitCode::FAILURE;
        }
    };
    let log_dir = match launchd::default_log_dir(&id) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("docwatch add: {e:#}");
            return ExitCode::FAILURE;
        }
    };
    // A bare "docwatch" fallback would be baked into the plist's
    // ProgramArguments and silently fail to resolve under launchd's minimal
    // PATH (KeepAlive=true then retries forever with no diagnostic), so
    // refuse to register rather than write an unresolvable path.
    let exe_path = match std::env::current_exe() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("docwatch add: could not resolve the running executable's path ({e}); refusing to register with an unresolvable plist path");
            return ExitCode::FAILURE;
        }
    };

    let params = InstallParams {
        folder,
        id,
        plist_path,
        log_dir,
        exe_path,
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

fn cmd_remove(args: RemoveArgs) -> ExitCode {
    let Ok(reg_path) = registry_path() else {
        return ExitCode::FAILURE;
    };

    let key = resolve_key(&args.path);
    let (removed, bootout_warning) = match install::uninstall_watcher(&reg_path, &key, &LaunchdHooks) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("docwatch remove: {e:#}{}", not_registered_hint(&args.path));
            return ExitCode::FAILURE;
        }
    };

    if let Some(e) = bootout_warning {
        eprintln!("docwatch remove: warning: {e:#}");
    }

    println!("removed watcher {} ({})", removed.id, removed.folder.display());
    ExitCode::SUCCESS
}

fn cmd_list(args: ListArgs) -> ExitCode {
    let Ok(reg_path) = registry_path() else {
        return ExitCode::FAILURE;
    };
    let entries = match registry::load(&reg_path) {
        Ok(e) => e,
        Err(e) => {
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
        println!("{}", serde_json::to_string_pretty(&out).unwrap_or_default());
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
    let Ok(reg_path) = registry_path() else {
        return ExitCode::FAILURE;
    };
    let entries = match registry::load(&reg_path) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("docwatch status: {e:#}");
            return ExitCode::FAILURE;
        }
    };

    let key = resolve_key(&args.path);
    let Some(entry) = registry::find(&entries, &key) else {
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
        let heartbeat_json = heartbeat.as_ref().map(|s| {
            serde_json::json!({
                "last_tick_unix": s.last_tick_unix,
                "dispatching": s.dispatching,
                "pending_count": s.pending_count,
                "stale": state::is_stale(s, now),
            })
        });
        let out = serde_json::json!({
            "id": entry.id,
            "folder": entry.folder,
            "running": running,
            "pid": pid,
            "heartbeat": heartbeat_json,
        });
        println!("{}", serde_json::to_string_pretty(&out).unwrap_or_default());
        return ExitCode::SUCCESS;
    }

    match (running, pid) {
        (Some(true), Some(pid)) => println!("running (pid {pid})"),
        (Some(false), _) => println!("stopped"),
        _ => println!("status unknown"),
    }

    // Staleness only signals trouble mid-dispatch: a dispatch that started
    // but hasn't refreshed the heartbeat past the threshold is likely stuck.
    // An idle watcher legitimately stops ticking (the debounce loop only
    // writes on fs events), so a stale-but-not-dispatching heartbeat just
    // means idle, not dead — liveness is answered by launchd above.
    match &heartbeat {
        Some(s) if s.dispatching && state::is_stale(s, now) => println!(
            "queue: dispatch stuck ({} pending, last tick {}s ago)",
            s.pending_count,
            now.saturating_sub(s.last_tick_unix)
        ),
        Some(s) if s.dispatching => println!("queue: dispatching ({} pending)", s.pending_count),
        Some(_) => println!("queue: idle"),
        None => println!("queue: unknown (no heartbeat yet)"),
    }

    let log_path = entry.log_dir.join("watcher.log");
    match launchd::tail_log(&log_path, 20) {
        Ok(lines) if lines.is_empty() => println!("(no log output yet: {})", log_path.display()),
        Ok(lines) => {
            println!("--- last {} line(s) of {} ---", lines.len(), log_path.display());
            for line in lines {
                println!("{line}");
            }
        }
        Err(e) => eprintln!("docwatch status: {e:#}"),
    }

    ExitCode::SUCCESS
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
    let folder = match args.folder.canonicalize() {
        Ok(p) => p,
        Err(e) => {
            eprintln!(
                "docwatch _run-watcher: {} does not exist ({e})",
                args.folder.display()
            );
            return ExitCode::FAILURE;
        }
    };

    let app_support_root = match registry::default_registry_path() {
        Ok(p) => p
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| p.clone()),
        Err(e) => {
            eprintln!("docwatch _run-watcher: {e:#}");
            return ExitCode::FAILURE;
        }
    };

    let log_dir = match launchd::default_log_dir(&args.id) {
        Ok(dir) => dir,
        Err(e) => {
            eprintln!("docwatch _run-watcher: {e:#}");
            return ExitCode::FAILURE;
        }
    };
    let log_path = log_dir.join("watcher.log");
    let state_path = log_dir.join("state.json");

    let repo_root = dispatcher::resolve_repo_root(&folder);
    let mut tracker = RetryTracker::default();

    let result = watcher::run(&folder, &app_support_root, |path, tasks| {
        if tasks.is_empty() {
            // A rename/delete produces a change event whose path no longer
            // exists; scan_file finds nothing to read and returns an empty
            // vec. Prune any tracked retry counters for this path so they
            // don't leak forever — see RetryTracker::prune_path.
            if !path.exists() {
                tracker.prune_path(path);
            }
            state::write_tick(&state_path, false, 0);
            return;
        }
        state::write_tick(&state_path, true, tasks.len());
        watcher::dispatch_pending(
            &repo_root,
            path,
            tasks,
            &log_path,
            &mut tracker,
            &mut |agent, file, watched_folder| dispatcher::dispatch(agent, file, watched_folder),
        );
        state::write_tick(&state_path, false, 0);
    });

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("docwatch _run-watcher: watch loop error: {e}");
            ExitCode::FAILURE
        }
    }
}
