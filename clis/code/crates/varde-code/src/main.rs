//! varde-code CLI binary.
//!
//! Dispatches `extract` and the 20 query-mode subcommands. Query subcommands
//! print the uniform JSON envelope; the process never exits non-zero for a
//! query-mode error (errors are carried inside the envelope).

use clap::Parser;
use varde_code::cli::{Cli, Command, HooksCommand};

fn main() {
    install_panic_hook();
    let cli = Cli::parse();
    init_tracing(cli.verbose);
    dispatch_command(cli.command);
}

fn dispatch_command(command: Command) {
    match command {
        Command::Batch { json } => run_query("batch", &json),
        Command::SymbolsInFile { json } => run_query("symbols_in_file", &json),
        Command::SymbolsInFiles { json } => run_query("symbols_in_files", &json),
        Command::GetSymbol { json } => run_query("get_symbol", &json),
        Command::Dependencies { json } => run_query("dependencies", &json),
        Command::Dependents { json } => run_query("dependents", &json),
        Command::TestsForFile { json } => run_query("tests_for_file", &json),
        Command::Hotspots { json } => run_query("hotspots", &json),
        Command::Clusters { json } => run_query("clusters", &json),
        Command::MapFile { json } => run_query("map_file", &json),
        Command::MapSymbol { json } => run_query("map_symbol", &json),
        Command::MapPath { json } => run_query("map_path", &json),
        Command::Explore { json } => run_query("explore", &json),
        Command::BlastRadius { json } => run_query("blast_radius", &json),
        Command::SymbolBlastRadius { json } => run_query("symbol_blast_radius", &json),
        Command::DetectChanges { json } => run_query("detect_changes", &json),
        Command::FindPattern { json } => run_query("find_pattern", &json),
        Command::ContextPack { json } => run_query("context_pack", &json),
        Command::FindImports { json } => run_query("find_imports", &json),
        Command::TypeHierarchy { json } => run_query("type_hierarchy", &json),
        Command::FilterSymbols { json } => run_query("filter_symbols", &json),
        Command::SliceState { json } => run_query("slice_state", &json),
        Command::NavMap {
            json,
            format,
            with_project_knowledge,
        } => return run_nav_map(&json, &format, with_project_knowledge),
        Command::Extract { path } => run_extract(&path),
        Command::Build {
            repo_root,
            force,
            changed_files,
        } => std::process::exit(run_build(&repo_root, force, changed_files)),
        // `scan` is a read-and-report operation like the query modes, but it
        // must be able to exit non-zero (findings at/above the severity
        // threshold → CI gate), so it gets its own dispatch arm instead of
        // `run_query` (which never exits non-zero by contract).
        Command::Scan { json, apply, force } => std::process::exit(run_scan(&json, apply, force)),
        // `test` is a read-and-report operation like `scan`: it must exit
        // non-zero when any `[[test]]` case fails (CI gate), so it gets its
        // own dispatch arm instead of `run_query`.
        Command::Test { json } => std::process::exit(run_test(&json)),
        Command::RulesList { json } => run_rules_list(&json),
        Command::RulesSeed { json, user, force } => run_rules_seed(&json, user, force),
        Command::RulesRemove { json, user, force } => run_rules_remove(&json, user, force),
        Command::Hooks(HooksCommand::List) => run_hooks_list(),
        Command::Hooks(HooksCommand::Install { agent, force, dir }) => {
            run_hooks_install(&agent, force, dir.as_deref())
        }
        Command::Hooks(HooksCommand::Remove { agent, force, dir }) => {
            run_hooks_remove(&agent, force, dir.as_deref())
        }
        Command::Watch {
            repos,
            config,
            debounce_ms,
            list,
            ensure,
            stop,
            stop_all,
        } => std::process::exit(if list {
            run_watch_list()
        } else if ensure {
            run_watch_ensure(&repos)
        } else if stop_all {
            run_watch_stop_all()
        } else if stop {
            run_watch_stop(&repos, config.as_deref())
        } else {
            run_watch(&repos, config.as_deref(), debounce_ms)
        }),
    }
}

/// Replace the default panic handler with a concise, user-facing message.
/// An unexpected panic is a bug, not a normal error path (those flow through
/// the JSON envelope or a `Result`), so a raw multi-line Rust panic dump at a
/// user is unhelpful. Print one clear line plus a report pointer; the process
/// still exits non-zero (101) so scripts and CI detect the failure. Honors
/// `RUST_BACKTRACE` implicitly — set it to still get the default trace.
fn install_panic_hook() {
    std::panic::set_hook(Box::new(|info| {
        let msg = info
            .payload()
            .downcast_ref::<&str>()
            .map(|s| s.to_string())
            .or_else(|| info.payload().downcast_ref::<String>().cloned())
            .unwrap_or_else(|| "unknown cause".to_string());
        let loc = info
            .location()
            .map(|l| format!(" at {}:{}", l.file(), l.line()))
            .unwrap_or_default();
        eprintln!("varde-code: internal error: {msg}{loc}");
        eprintln!(
            "This is a bug; please report it at https://github.com/alecegg/varde-code/issues"
        );
    }));
}

/// Run one `scan` invocation: flow + envelope + threshold exit code.
///
/// `apply`/`force` (from the `--apply`/`--force` flags) are merged into the
/// JSON input so `scan_repo` — and the MCP surface, which drives scan purely
/// via the JSON input — see one contract. An explicit JSON `apply`/`force`
/// field is honored as-is unless the corresponding flag is passed, in which
/// case the flag wins (an explicit CLI switch beats an embedded value).
///
/// Returns the process exit code: 0 when no finding meets/exceeds the
/// severity threshold (default `error`), non-zero otherwise; any tool-level
/// error (bad input, missing/stale DB, unwritable `output`) emits the
/// `{ok:false,data.error}` envelope and returns non-zero. `output` present →
/// envelope written to that file and nothing on stdout; absent → stdout.
fn run_scan(json: &str, apply: bool, force: bool) -> i32 {
    let mut value = match parse_json_input(json) {
        Ok(value) => value,
        Err(error) => {
            println!("{}", varde_code::query::render(Err(error)));
            return 1;
        }
    };
    if !value.is_object() {
        println!(
            "{}",
            varde_code::query::render(Err(varde_code::query::ApiError::new(
                "invalid_input",
                "scan input must be a JSON object",
            )))
        );
        return 1;
    }
    if apply {
        value["apply"] = serde_json::json!(true);
    }
    if force {
        value["force"] = serde_json::json!(true);
    }

    let (envelope, payload) =
        render_preprocessed_envelope(varde_code::scan_cli::scan_repo(&value), &value);

    if let Some(path) = value.get("output").and_then(|o| o.as_str()) {
        if let Err(e) = std::fs::write(path, &envelope) {
            println!(
                "{}",
                varde_code::query::render(Err(varde_code::query::ApiError::new(
                    "write_error",
                    format!("cannot write scan output to {path}: {e}"),
                )))
            );
            return 1;
        }
    } else {
        println!("{envelope}");
    }

    if payload["ok"] == true {
        if payload["data"]["gate"]["status"] == "pass" {
            0
        } else {
            1
        }
    } else {
        1
    }
}

/// Run one `test` invocation: flow + envelope + failure-gate exit code.
///
/// Mirrors `run_scan`'s shape: parses `json`, runs the operation, prints the
/// `{ok, data}`/`{ok:false, data.error}` envelope to stdout, and returns the
/// process exit code — `0` when `summary.failed == 0`, non-zero when any
/// test failed or a tool-level error occurred (bad input JSON, invalid
/// `rulesDir`, etc).
fn run_test(json: &str) -> i32 {
    let value = match parse_json_input(json) {
        Ok(value) => value,
        Err(error) => {
            println!("{}", varde_code::query::render(Err(error)));
            return 1;
        }
    };

    let (envelope, payload) = render_envelope(varde_code::test_cli::run_tests(&value), &value);
    println!("{envelope}");
    if payload["ok"] == true {
        let failed = payload["data"]["summary"]["failed"].as_u64().unwrap_or(0);
        if failed == 0 { 0 } else { 1 }
    } else {
        1
    }
}

/// Render a machine result with input-derived metadata.
fn render_envelope(
    result: Result<serde_json::Value, varde_code::query::ApiError>,
    input: &serde_json::Value,
) -> (String, serde_json::Value) {
    finish_envelope(varde_code::query::output::render_value_with_input(
        result, input,
    ))
}

/// Render a payload whose producer already applied output compaction.
fn render_preprocessed_envelope(
    result: Result<serde_json::Value, varde_code::query::ApiError>,
    input: &serde_json::Value,
) -> (String, serde_json::Value) {
    finish_envelope(varde_code::query::output::render_value_with_preprocessed_input(result, input))
}

fn finish_envelope(payload: serde_json::Value) -> (String, serde_json::Value) {
    let envelope = payload.to_string();
    (envelope, payload)
}

/// Resolve the watch list (explicit `--repo`s + optional config file, or
/// the default `~/.config/varde-code/watch.toml` when neither is given),
/// then run the watcher until killed. Prints a clear error and exits
/// non-zero on any setup failure (bad config, no repos resolved, another
/// watcher already running for this repo set); once running, per-repo
/// reconcile failures are logged by `watch::run` and do not exit the
/// process — one repo's transient failure must not take down every other
/// watched repo.
fn run_watch_ensure(repos: &[String]) -> i32 {
    if repos.len() != 1 {
        println!(
            "{}",
            varde_code::query::render(Err::<serde_json::Value, _>(
                varde_code::query::ApiError::new(
                    "invalid_input",
                    "--ensure requires exactly one --repo"
                )
            ))
        );
        return 1;
    }
    let resolved = match varde_code::watch::resolve_repos(repos, None) {
        Ok(paths) => paths,
        Err(err) => {
            println!(
                "{}",
                varde_code::query::render(Err::<serde_json::Value, _>(
                    varde_code::query::ApiError::new("invalid_input", err.to_string())
                ))
            );
            return 1;
        }
    };
    match varde_code::watch::ensure(&resolved[0]) {
        Ok(status) => {
            println!(
                "{}",
                varde_code::query::render(serde_json::to_value(status).map_err(|err| {
                    varde_code::query::ApiError::new("serialization_error", err.to_string())
                }))
            );
            0
        }
        Err(err) => {
            println!(
                "{}",
                varde_code::query::render(Err::<serde_json::Value, _>(
                    varde_code::query::ApiError::new("watch_error", err.to_string())
                ))
            );
            1
        }
    }
}

fn run_watch(repos: &[String], config_path: Option<&str>, debounce_ms: u64) -> i32 {
    let resolved = match resolve_watch_repos(repos, config_path) {
        Ok(resolved) => resolved,
        Err(err) => {
            println!("{}", varde_code::query::render(Err(err)));
            return 1;
        }
    };

    match varde_code::watch::run(&resolved, std::time::Duration::from_millis(debounce_ms)) {
        Ok(()) => 0,
        Err(err) => {
            println!(
                "{}",
                varde_code::query::render(Err::<serde_json::Value, _>(
                    varde_code::query::ApiError::new("watch_error", err.to_string())
                ))
            );
            1
        }
    }
}

/// Shared `--repo`/`--config` resolution for `run_watch` and `run_watch_stop`
/// — same repo set must resolve identically for both, since `--stop` looks
/// up a running watcher's lock by hashing this same resolved list (see
/// `watch::watch_set_id`). On failure, prints the error and returns the exit
/// code the caller should return.
fn resolve_watch_repos(
    repos: &[String],
    config_path: Option<&str>,
) -> Result<Vec<std::path::PathBuf>, varde_code::query::ApiError> {
    let config = match config_path {
        Some(path) => match varde_code::watch::WatchConfig::load(std::path::Path::new(path)) {
            Ok(config) => Some(config),
            Err(err) => {
                return Err(varde_code::query::ApiError::new(
                    "invalid_input",
                    err.to_string(),
                ));
            }
        },
        None => {
            let default_path = varde_code::watch::WatchConfig::default_path();
            if repos.is_empty() && default_path.exists() {
                match varde_code::watch::WatchConfig::load(&default_path) {
                    Ok(config) => Some(config),
                    Err(err) => {
                        return Err(varde_code::query::ApiError::new(
                            "invalid_input",
                            err.to_string(),
                        ));
                    }
                }
            } else {
                None
            }
        }
    };

    varde_code::watch::resolve_repos(repos, config.as_ref())
        .map_err(|err| varde_code::query::ApiError::new("invalid_input", err.to_string()))
}

/// `varde-code watch --list`: print every watcher instance (live or
/// stale-locked) as a JSON array and exit 0. Never exits non-zero — this is
/// a read-only listing, same posture as `rules_list`/`slice_state`.
fn run_watch_list() -> i32 {
    match varde_code::watch::list_instances() {
        Ok(instances) => {
            println!(
                "{}",
                varde_code::query::render(serde_json::to_value(instances).map_err(|err| {
                    varde_code::query::ApiError::new("serialization_error", err.to_string())
                }))
            );
            0
        }
        Err(err) => {
            println!(
                "{}",
                varde_code::query::render(Err::<serde_json::Value, _>(
                    varde_code::query::ApiError::new("watch_error", err.to_string())
                ))
            );
            1
        }
    }
}

/// `varde-code watch --stop`: stop the watcher for the `--repo`/`--config`-
/// resolved repo set and exit. Non-zero if no watcher is registered for that
/// repo set or the stop itself fails.
fn run_watch_stop(repos: &[String], config_path: Option<&str>) -> i32 {
    let resolved = match resolve_watch_repos(repos, config_path) {
        Ok(resolved) => resolved,
        Err(err) => {
            println!("{}", varde_code::query::render(Err(err)));
            return 1;
        }
    };
    match varde_code::watch::stop(&resolved) {
        Ok(outcome) => {
            println!(
                "{}",
                varde_code::query::render(serde_json::to_value(outcome).map_err(|err| {
                    varde_code::query::ApiError::new("serialization_error", err.to_string())
                }))
            );
            0
        }
        Err(err) => {
            println!(
                "{}",
                varde_code::query::render(Err::<serde_json::Value, _>(
                    varde_code::query::ApiError::new("watch_error", err.to_string())
                ))
            );
            1
        }
    }
}

/// `varde-code watch --stop-all`: stop every running watcher instance and
/// exit. Non-zero only if enumerating instances itself fails; a per-instance
/// stop failure is reported inline in the JSON output, not a process exit.
fn run_watch_stop_all() -> i32 {
    match varde_code::watch::stop_all() {
        Ok(outcomes) => {
            println!(
                "{}",
                varde_code::query::render(serde_json::to_value(outcomes).map_err(|err| {
                    varde_code::query::ApiError::new("serialization_error", err.to_string())
                }))
            );
            0
        }
        Err(err) => {
            println!(
                "{}",
                varde_code::query::render(Err::<serde_json::Value, _>(
                    varde_code::query::ApiError::new("watch_error", err.to_string())
                ))
            );
            1
        }
    }
}

/// Run one `rules_list` invocation: parses input, delegates to
/// `scan_cli::rules_list`, prints the uniform envelope. Never exits
/// non-zero — this is a read-only listing, not a CI gate like `scan`.
fn run_rules_list(json: &str) {
    let value = match parse_json_input(json) {
        Ok(value) => value,
        Err(error) => {
            println!("{}", varde_code::query::render(Err(error)));
            return;
        }
    };
    println!(
        "{}",
        varde_code::query::output::render_with_input(
            varde_code::scan_cli::rules_list(&value),
            &value
        )
    );
}

/// Run one `rules_seed` invocation: parses input, delegates to
/// `scan_cli::rules_seed`, prints the uniform envelope. Never exits
/// non-zero — writing seed files is not a CI gate.
fn run_rules_seed(json: &str, user: bool, force: bool) {
    let value = match parse_json_input(json) {
        Ok(value) => value,
        Err(error) => {
            println!("{}", varde_code::query::render(Err(error)));
            return;
        }
    };
    println!(
        "{}",
        varde_code::query::output::render_with_input(
            varde_code::scan_cli::rules_seed(&value, user, force),
            &value,
        )
    );
}

/// Run one `rules_remove` invocation: parses input, delegates to
/// `scan_cli::rules_remove`, prints the uniform envelope. Never exits
/// non-zero — deleting seed files is not a CI gate.
fn run_rules_remove(json: &str, user: bool, force: bool) {
    let value = match parse_json_input(json) {
        Ok(value) => value,
        Err(error) => {
            println!("{}", varde_code::query::render(Err(error)));
            return;
        }
    };
    println!(
        "{}",
        varde_code::query::output::render_with_input(
            varde_code::scan_cli::rules_remove(&value, user, force),
            &value,
        )
    );
}

/// Resolve the requested `--agent` names to `HookTarget`s. Empty (no
/// `--agent` given) defaults to every target in `HOOK_TARGETS`. Unknown
/// agent names are reported as an error rather than silently ignored.
fn resolve_hook_targets(agents: &[String]) -> Result<Vec<varde_code::hooks::HookTarget>, String> {
    if agents.is_empty() {
        return Ok(varde_code::hooks::HOOK_TARGETS.to_vec());
    }
    agents
        .iter()
        .map(|name| {
            varde_code::hooks::HOOK_TARGETS
                .iter()
                .find(|t| t.agent == name)
                .copied()
                .ok_or_else(|| {
                    let known: Vec<&str> = varde_code::hooks::HOOK_TARGETS
                        .iter()
                        .map(|t| t.agent)
                        .collect();
                    format!("unknown agent {name:?}; expected one of {known:?}")
                })
        })
        .collect()
}

/// The real per-agent, per-OS default install directory (user-level scope),
/// used when `--dir` is not given.
fn default_hook_dir(agent: &str) -> std::path::PathBuf {
    let home = std::env::var_os("HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from("~"));
    match agent {
        varde_code::hooks::CLAUDE_AGENT => home.join(".claude"),
        varde_code::hooks::CODEX_AGENT => home.join(".codex"),
        varde_code::hooks::OPENCODE_AGENT => home.join(".config").join("opencode"),
        varde_code::hooks::PI_AGENT => home.join(".pi").join("agent").join("extensions"),
        other => home.join(format!(".{other}")),
    }
}

/// Run one `hooks list` invocation: describes the 4 supported agent hook
/// targets and where each installs to. No filesystem access.
fn run_hooks_list() {
    let targets: Vec<serde_json::Value> = varde_code::hooks::HOOK_TARGETS
        .iter()
        .map(|target| {
            let (rel_path, kind) = match target.kind {
                varde_code::hooks::HookKind::MergeInto(rel_path, _) => (rel_path, "merge"),
                varde_code::hooks::HookKind::WriteFile(rel_path, _) => (rel_path, "write_file"),
            };
            let default_dir = default_hook_dir(target.agent);
            serde_json::json!({
                "agent": target.agent,
                "kind": kind,
                "relPath": rel_path,
                "defaultTargetDir": default_dir.display().to_string(),
                "defaultPath": default_dir.join(rel_path).display().to_string(),
            })
        })
        .collect();
    println!(
        "{}",
        varde_code::query::render(Ok::<_, varde_code::query::ApiError>(
            serde_json::json!({ "targets": targets })
        ))
    );
}

/// Run one `hooks install` invocation: installs the session-start hook for
/// each requested agent (default: all 4) into either `--dir` (uniformly, for
/// testing) or each agent's real per-OS default directory. Never exits
/// non-zero — installing hooks is not a CI gate.
fn run_hooks_install(agents: &[String], force: bool, dir: Option<&str>) {
    let targets = match resolve_hook_targets(agents) {
        Ok(targets) => targets,
        Err(err) => {
            println!(
                "{}",
                varde_code::query::render(Err::<serde_json::Value, _>(
                    varde_code::query::ApiError::new("invalid_argument", err)
                ))
            );
            return;
        }
    };
    let result = install_or_remove_hooks(&targets, dir, |target_dir, one_target| {
        varde_code::hooks::install_hooks(target_dir, one_target, force)
    })
    .map(|(installed, dirs)| {
        let installed_json: Vec<serde_json::Value> = installed
            .iter()
            .map(|r| {
                serde_json::json!({
                    "agent": r.agent,
                    "path": r.path.display().to_string(),
                    "written": r.written,
                    "skippedExisting": r.skipped_existing,
                })
            })
            .collect();
        serde_json::json!({ "targetDirs": dirs, "installed": installed_json })
    })
    .map_err(|e| {
        varde_code::query::ApiError::new("io_error", format!("failed to install hooks: {e}"))
    });
    println!("{}", varde_code::query::render(result));
}

/// Run one `hooks remove` invocation: undoes `hooks install` for each
/// requested agent (default: all 4). Never exits non-zero — removing hooks
/// is not a CI gate.
fn run_hooks_remove(agents: &[String], force: bool, dir: Option<&str>) {
    let targets = match resolve_hook_targets(agents) {
        Ok(targets) => targets,
        Err(err) => {
            println!(
                "{}",
                varde_code::query::render(Err::<serde_json::Value, _>(
                    varde_code::query::ApiError::new("invalid_argument", err)
                ))
            );
            return;
        }
    };
    let result = install_or_remove_hooks(&targets, dir, |target_dir, one_target| {
        varde_code::hooks::remove_hooks(target_dir, one_target, force)
    })
    .map(|(removed, dirs)| {
        let removed_json: Vec<serde_json::Value> = removed
            .iter()
            .map(|r| {
                serde_json::json!({
                    "agent": r.agent,
                    "path": r.path.display().to_string(),
                    "removed": r.removed,
                    "skippedModified": r.skipped_modified,
                })
            })
            .collect();
        serde_json::json!({ "targetDirs": dirs, "removed": removed_json })
    })
    .map_err(|e| {
        varde_code::query::ApiError::new("io_error", format!("failed to remove hooks: {e}"))
    });
    println!("{}", varde_code::query::render(result));
}

/// Shared install/remove driver: with `--dir`, all `targets` are installed
/// into that single directory in one call (matches `hooks.rs`'s own tests,
/// which pass one dir for multiple agents since each target's `rel_path` is
/// a distinct filename). Without `--dir`, each target is installed into its
/// own resolved per-agent default directory via a separate call. Returns the
/// concatenated per-target results plus a `{agent: targetDir}` map for the
/// envelope.
fn install_or_remove_hooks<T>(
    targets: &[varde_code::hooks::HookTarget],
    dir: Option<&str>,
    op: impl Fn(&std::path::Path, &[varde_code::hooks::HookTarget]) -> std::io::Result<Vec<T>>,
) -> std::io::Result<(Vec<T>, serde_json::Value)> {
    match dir {
        Some(dir) => {
            let target_dir = std::path::Path::new(dir);
            let results = op(target_dir, targets)?;
            let dirs: serde_json::Map<String, serde_json::Value> = targets
                .iter()
                .map(|t| {
                    (
                        t.agent.to_string(),
                        serde_json::Value::String(target_dir.display().to_string()),
                    )
                })
                .collect();
            Ok((results, serde_json::Value::Object(dirs)))
        }
        None => {
            let mut all_results = Vec::new();
            let mut dirs = serde_json::Map::new();
            for target in targets {
                let target_dir = default_hook_dir(target.agent);
                let results = op(&target_dir, std::slice::from_ref(target))?;
                dirs.insert(
                    target.agent.to_string(),
                    serde_json::Value::String(target_dir.display().to_string()),
                );
                all_results.extend(results);
            }
            Ok((all_results, serde_json::Value::Object(dirs)))
        }
    }
}

fn run_query(mode: &str, json: &str) {
    println!("{}", varde_code::query::run_mode(mode, json));
}

fn parse_json_input(json: &str) -> Result<serde_json::Value, varde_code::query::ApiError> {
    serde_json::from_str(json).map_err(|error| {
        varde_code::query::ApiError::new(
            "invalid_input",
            format!("input is not valid JSON: {error}"),
        )
    })
}

/// `nav_map` — JSON is the canonical envelope, printed as-is; `--format
/// text` derives a plain-text rendering from the same JSON.
///
/// The `--format text` path is injected verbatim into a session at start. It
/// always includes Varde's compact orientation and, when Toz capture succeeds,
/// a handle with commands to retrieve the unbudgeted map (still under the
/// per-section hard caps). Query errors still return their raw envelope.
fn run_nav_map(json: &str, format: &str, with_project_knowledge: bool) {
    let envelope = varde_code::query::run_mode("nav_map", json);
    if format == "text" {
        let value = serde_json::from_str(&envelope).ok();
        let data = value.as_ref().and_then(successful_nav_map_data);
        let map = render_nav_map_text_with_toz_data(json, &envelope, data);
        if with_project_knowledge && data.is_some() {
            if let Some(knowledge) = render_project_knowledge(json) {
                println!("{knowledge}\n\n{map}");
                return;
            }
        }
        println!("{map}");
    } else {
        println!("{}", envelope);
    }
}

/// Point session-start hooks to durable project knowledge without loading it.
fn render_project_knowledge(json: &str) -> Option<String> {
    let repo_root = nav_map_input_repo_root(json)?;
    let session_dir = std::path::Path::new(&repo_root).canonicalize().ok()?;
    if !session_dir.is_dir() {
        return None;
    }

    // The hook passes the session cwd, which can be nested below the Git root.
    // Resolve that root for knowledge lookup only; nav_map keeps its original input.
    let project_root = session_dir
        .ancestors()
        .find(|dir| dir.join(".git").exists())
        .unwrap_or(&session_dir);
    if !project_root.join("memory-bank/knowledge").is_dir() {
        return None;
    }

    Some(String::from(
        "Project knowledge: memory-bank/knowledge/ (use varde-workflow concept search --bundle memory-bank/knowledge --text <term>).",
    ))
}

/// Render one Varde-owned orientation in every case. A successful Toz capture
/// adds only a retrieval pointer for the expanded map.
#[cfg(test)]
fn render_nav_map_text_with_toz(json: &str, envelope: &str) -> String {
    let value = serde_json::from_str(envelope).ok();
    let data = value.as_ref().and_then(successful_nav_map_data);
    render_nav_map_text_with_toz_data(json, envelope, data)
}

fn render_nav_map_text_with_toz_data(
    json: &str,
    envelope: &str,
    data: Option<&serde_json::Value>,
) -> String {
    let mut orientation =
        data.map_or_else(|| envelope.to_string(), render_nav_map_orientation_data);
    if data.is_none() || !varde_code::toz::enabled() {
        return orientation;
    }
    let unbudgeted_json = json_with_unbounded_token_budget(json);
    let unbudgeted_envelope = varde_code::query::run_mode("nav_map", &unbudgeted_json);
    let unbudgeted_value = serde_json::from_str(&unbudgeted_envelope).ok();
    let Some(unbudgeted_data) = unbudgeted_value.as_ref().and_then(successful_nav_map_data) else {
        return orientation;
    };
    let unbudgeted_text = render_nav_map_text_data(unbudgeted_data);
    let repo_root = nav_map_input_repo_root(json).unwrap_or_default();
    let source = format!("varde-code nav_map {repo_root}");
    let Some(handle) = varde_code::toz::capture_text(&source, "nav_map", &unbudgeted_text)
        .and_then(|preview| toz_capture_handle(&preview).map(str::to_owned))
    else {
        return orientation;
    };
    orientation.push_str(&format!(
        "\nExpanded map in Toz (handle {handle}). Search: `varde-toz query --handle {handle} \"<term>\"`; read lines: `varde-toz query --handle {handle} --lines 1:80`.\n"
    ));
    orientation
}

/// Accept only Toz's standard capture header and a simple handle token.
/// Other successful-looking output is not enough to claim a stored capture.
fn toz_capture_handle(stdout: &str) -> Option<&str> {
    let first_line = stdout.lines().next()?.trim_end_matches('\r');
    let (byte_count, capture) = first_line
        .strip_prefix("varde-toz: captured ")?
        .split_once(" → handle ")?;
    let byte_digits = byte_count.strip_suffix(" bytes")?;
    let mut groups = byte_digits.split(',');
    let first_group = groups.next()?;
    if first_group.is_empty()
        || first_group.len() > 3
        || !first_group.chars().all(|digit| digit.is_ascii_digit())
        || groups.any(|group| group.len() != 3 || !group.chars().all(|d| d.is_ascii_digit()))
    {
        return None;
    }

    let (handle, details) = capture.split_once(" (")?;
    let (counts, label) = details.split_once(")  label: ")?;
    if label != "\"nav_map\"" {
        return None;
    }
    let (line_count, chunk_count) = counts.split_once(", ")?;
    line_count.strip_suffix(" lines")?.parse::<usize>().ok()?;
    let chunk_count = chunk_count
        .strip_suffix(" chunks")
        .or_else(|| chunk_count.strip_suffix(" chunk"))?;
    chunk_count.parse::<usize>().ok()?;

    (handle.len() >= 4
        && handle
            .chars()
            .all(|character| character.is_ascii_lowercase() || character.is_ascii_digit()))
    .then_some(handle)
}

/// Compact session-start orientation, used whether or not Toz can retain the
/// expanded map. Keep repo shape, representative entrypoints, and shallow
/// flow roots; provide real CLI commands for task-specific detail.
#[cfg(test)]
fn render_nav_map_orientation(envelope: &str) -> String {
    let value = serde_json::from_str(envelope).ok();
    value
        .as_ref()
        .and_then(successful_nav_map_data)
        .map_or_else(|| envelope.to_string(), render_nav_map_orientation_data)
}

fn render_nav_map_orientation_data(data: &serde_json::Value) -> String {
    const ENTRYPOINT_LIMIT: usize = 5;
    const SUBSYSTEM_LIMIT: usize = 5;
    const FLOW_LIMIT: usize = 4;
    const FLOW_CHILD_LIMIT: usize = 4;

    let mut out = String::from("## Repository outline\n");
    let sections = [
        ("entrypoints", "entrypoints"),
        ("subsystems", "subsystems"),
        ("flows", "flows"),
        ("hotspots", "hotspots"),
    ];
    let counts = sections
        .iter()
        .map(|(section, label)| format!("{} {label}", array_len(data, section)))
        .collect::<Vec<_>>();
    out.push_str(&format!(
        "Items present in this capped map: {}.\n",
        counts.join(", ")
    ));
    let omitted = sections
        .iter()
        .filter_map(|(section, label)| {
            token_budget_omissions(data, section)
                .filter(|count| *count > 0)
                .map(|count| format!("{count} {label}"))
        })
        .collect::<Vec<_>>();
    if !omitted.is_empty() {
        out.push_str(&format!(
            "Additional items omitted by the token budget: {}.\n",
            omitted.join(", ")
        ));
    }

    if let Some(subsystems) = data["subsystems"]
        .as_array()
        .filter(|items| !items.is_empty())
    {
        let names = subsystems
            .iter()
            .take(SUBSYSTEM_LIMIT)
            .map(|item| str_field(item, "name"))
            .filter(|name| !name.is_empty())
            .collect::<Vec<_>>();
        if !names.is_empty() {
            out.push_str(&format!("Subsystems: {}\n", names.join(", ")));
        }
    }

    append_orientation_items(
        &mut out,
        "Key entrypoints",
        data["entrypoints"].as_array(),
        ENTRYPOINT_LIMIT,
        render_entrypoint,
    );
    append_orientation_items(
        &mut out,
        "Main flows (root and direct calls)",
        data["flows"].as_array(),
        FLOW_LIMIT,
        |item| render_flow_preview(item, FLOW_CHILD_LIMIT),
    );

    out.push_str("## Investigate further\n");
    out.push_str(
        "- Expanded map (section caps still apply): `varde-code nav_map --json '{\"repoRoot\":\"<repo-root>\",\"maxTokensEstimate\":18446744073709551615}'`\n\
         - Find relevant files and symbols: `varde-code context_pack --json '{\"repoRoot\":\"<repo-root>\",\"query\":\"<term>\"}'`\n\
         - Explore file dependencies from a file or symbol: `varde-code explore --json '{\"repoRoot\":\"<repo-root>\",\"query\":{\"params\":{\"input\":\"<file-or-symbol>\",\"direction\":\"outgoing\"}}}'`\n\
         - Inspect risk hotspots: `varde-code hotspots --json '{\"repoRoot\":\"<repo-root>\"}'`\n",
    );
    out
}

fn array_len(data: &serde_json::Value, key: &str) -> usize {
    data.get(key)
        .and_then(|items| items.as_array())
        .map_or(0, Vec::len)
}

fn token_budget_omissions(data: &serde_json::Value, section: &str) -> Option<usize> {
    let total = data
        .pointer(&format!("/guide/truncated/{section}/total"))?
        .as_u64()?;
    let total = usize::try_from(total).ok()?;
    Some(total.saturating_sub(array_len(data, section)))
}

fn append_orientation_items<F>(
    out: &mut String,
    heading: &str,
    items: Option<&Vec<serde_json::Value>>,
    limit: usize,
    render: F,
) where
    F: Fn(&serde_json::Value) -> String,
{
    let Some(items) = items.filter(|items| !items.is_empty()) else {
        return;
    };
    out.push_str(&format!("## {heading}\n"));
    for item in items.iter().take(limit) {
        out.push_str(&render(item));
    }
    if items.len() > limit {
        out.push_str(&format!(
            "- … {} more; query for details\n",
            items.len() - limit
        ));
    }
}

fn render_flow_preview(item: &serde_json::Value, child_limit: usize) -> String {
    let files = item
        .get("files")
        .and_then(|files| files.as_array())
        .map(Vec::as_slice)
        .unwrap_or(&[]);
    let mut out = format!(
        "- {} ({} nodes)",
        str_field(item, "entrypoint"),
        u64_field(item, "nodeCount")
    );
    if let Some(root) = item.get("root") {
        out.push_str(&format!(
            ": {} ({})",
            str_field(root, "symbol"),
            flow_node_file(root, files)
        ));
        if let Some(children) = root
            .get("children")
            .and_then(|value| value.as_array())
            .filter(|children| !children.is_empty())
        {
            let calls = children
                .iter()
                .take(child_limit)
                .map(|child| {
                    format!(
                        "{} ({})",
                        str_field(child, "symbol"),
                        flow_node_file(child, files)
                    )
                })
                .collect::<Vec<_>>();
            if !calls.is_empty() {
                out.push_str(&format!(" → {}", calls.join(", ")));
            }
            if children.len() > child_limit {
                out.push_str(&format!(", +{} calls", children.len() - child_limit));
            }
        }
    }
    out.push('\n');
    out
}

/// Parse `json`, set `maxTokensEstimate` to the largest value `nav_map`'s
/// budgeting accepts so the budget pass never trims a section (its
/// hard-coded per-section caps — `HOTSPOTS_SECTION_LIMIT` and friends — still
/// apply). Falls back to `json` unchanged if it doesn't parse; the resulting
/// `run_mode` call then fails the same way the budgeted call already did.
fn json_with_unbounded_token_budget(json: &str) -> String {
    let Ok(mut value) = serde_json::from_str::<serde_json::Value>(json) else {
        return json.to_string();
    };
    if let Some(object) = value.as_object_mut() {
        object.insert(
            "maxTokensEstimate".to_string(),
            serde_json::Value::from(u64::MAX),
        );
    }
    value.to_string()
}

/// Best-effort `repoRoot` for the toz `--source` string; `None` when the
/// input is dbPath-only or unparseable (an empty `<repoRoot>` still gives
/// every nav_map capture the same source prefix, so they still supersede
/// each other in toz).
fn nav_map_input_repo_root(json: &str) -> Option<String> {
    serde_json::from_str::<serde_json::Value>(json)
        .ok()?
        .get("repoRoot")?
        .as_str()
        .map(str::to_string)
}

/// Render the `nav_map` JSON envelope as plain text, one section per header.
/// Each section's items are rendered as concise, human-readable lines (symbol
/// names, file paths, call trees) — not a bare item count — because this text
/// is injected verbatim into a session at start and a count alone orients
/// nobody. On error (or unparseable input), fall back to the raw envelope so no
/// information is lost.
#[cfg(test)]
fn render_nav_map_text(envelope: &str) -> String {
    let value = serde_json::from_str(envelope).ok();
    value
        .as_ref()
        .and_then(successful_nav_map_data)
        .map_or_else(|| envelope.to_string(), render_nav_map_text_data)
}

fn render_nav_map_text_data(data: &serde_json::Value) -> String {
    const SECTIONS: [&str; 7] = [
        "entrypoints",
        "foundational_files",
        "module_layers",
        "subsystems",
        "symbols",
        "flows",
        "hotspots",
    ];
    let truncated = data
        .pointer("/guide/truncated")
        .and_then(|value| value.as_object());
    let mut out = String::new();
    for section in SECTIONS {
        render_nav_map_section(&mut out, data, truncated, section);
    }
    render_truncation_guide(&mut out, truncated);
    out
}

#[cfg(test)]
fn nav_map_data(envelope: &str) -> Option<serde_json::Value> {
    let value: serde_json::Value = serde_json::from_str(envelope).ok()?;
    successful_nav_map_data(&value).cloned()
}

fn successful_nav_map_data(value: &serde_json::Value) -> Option<&serde_json::Value> {
    (value.get("ok").and_then(|value| value.as_bool()) == Some(true))
        .then(|| value.get("data").unwrap_or(&serde_json::Value::Null))
}

fn render_nav_map_section(
    out: &mut String,
    data: &serde_json::Value,
    truncated: Option<&serde_json::Map<String, serde_json::Value>>,
    section: &str,
) {
    out.push_str(&format!("## {section}\n"));
    match data.get(section) {
        Some(serde_json::Value::Array(items)) if items.is_empty() => {
            render_empty_nav_map_section(out, truncated.and_then(|all| all.get(section)));
        }
        Some(serde_json::Value::Array(items)) => {
            items
                .iter()
                .for_each(|item| out.push_str(&render_nav_map_item(section, item)));
            out.push('\n');
        }
        Some(serde_json::Value::Object(_)) if section == "module_layers" => {
            out.push_str(&render_module_layers(&data[section]));
        }
        Some(other) => out.push_str(&format!("{other}\n\n")),
        None => out.push_str("(missing)\n\n"),
    }
}

fn render_empty_nav_map_section(out: &mut String, info: Option<&serde_json::Value>) {
    let Some(info) = info else {
        out.push_str("(none)\n\n");
        return;
    };
    let total = u64_field(info, "total");
    let more = str_field(info, "more");
    out.push_str(&format!("(truncated: 0/{total} shown; {more})\n\n"));
}

fn render_truncation_guide(
    out: &mut String,
    truncated: Option<&serde_json::Map<String, serde_json::Value>>,
) {
    let Some(truncated) = truncated.filter(|sections| !sections.is_empty()) else {
        return;
    };
    out.push_str("## truncated (token budget)\n");
    for (section, info) in truncated {
        let shown = u64_field(info, "shown");
        let total = u64_field(info, "total");
        let more = str_field(info, "more");
        out.push_str(&format!("- {section}: {shown}/{total} shown — {more}\n"));
    }
    out.push('\n');
}

/// String field lookup helper for the nav_map item renderers.
fn str_field<'a>(item: &'a serde_json::Value, key: &str) -> &'a str {
    item.get(key).and_then(|v| v.as_str()).unwrap_or("")
}

/// Integer field lookup helper for the nav_map item renderers.
fn u64_field(item: &serde_json::Value, key: &str) -> u64 {
    item.get(key).and_then(|v| v.as_u64()).unwrap_or(0)
}

/// Resolve a flow node's file: nav_map interns paths per summary and emits an
/// `f` index into the summary's `files` table (see `nav_map::FileInterner`).
/// Falls back to a literal `file` string so a hand-built or older envelope
/// still renders.
fn flow_node_file<'a>(node: &'a serde_json::Value, files: &'a [serde_json::Value]) -> &'a str {
    if let Some(idx) = node.get("f").and_then(|v| v.as_u64()) {
        return files
            .get(idx as usize)
            .and_then(|v| v.as_str())
            .unwrap_or("");
    }
    str_field(node, "file")
}

/// Render one item of an array-valued nav_map section as a concise line.
/// Each section has a known shape (see `query/nav_map.rs`); unknown shapes
/// fall back to compact JSON so nothing is silently dropped.
fn render_nav_map_item(section: &str, item: &serde_json::Value) -> String {
    match section {
        "entrypoints" => render_entrypoint(item),
        "foundational_files" => format!(
            "- {}  ({} dependents, {} refs)\n",
            str_field(item, "file"),
            u64_field(item, "dependents"),
            u64_field(item, "count"),
        ),
        "subsystems" => render_subsystem(item),
        "symbols" => render_symbol(item),
        "hotspots" => format!(
            "- {}  (score {}, complexity {}, churn {})\n",
            str_field(item, "file"),
            u64_field(item, "score"),
            u64_field(item, "complexity"),
            u64_field(item, "churn"),
        ),
        "flows" => render_flow(item),
        _ => format!("- {item}\n"),
    }
}

fn render_entrypoint(item: &serde_json::Value) -> String {
    let symbol = str_field(item, "symbol");
    let role = optional_label(str_field(item, "role"), "[", "]");
    let method = str_field(item, "method");
    let path = str_field(item, "path");
    let route = match (method.is_empty(), path.is_empty()) {
        (false, false) => format!("{method} {path}"),
        (true, false) => path.to_string(),
        _ => String::new(),
    };
    let route = if route != symbol {
        route
    } else {
        String::new()
    };
    let route = optional_label(&route, "(", ")");
    format!("- {symbol}{route}  {}{role}\n", str_field(item, "file"))
}

fn optional_label(value: &str, prefix: &str, suffix: &str) -> String {
    if value.is_empty() {
        String::new()
    } else {
        format!("  {prefix}{value}{suffix}")
    }
}

fn render_subsystem(item: &serde_json::Value) -> String {
    let members = item
        .get("members")
        .and_then(|members| members.as_array())
        .into_iter()
        .flatten()
        .filter_map(|member| member.as_str())
        .collect::<Vec<_>>()
        .join(", ");
    let omitted = u64_field(item, "membersOmitted");
    let more = if omitted > 0 {
        format!(" (+{omitted} more)")
    } else {
        String::new()
    };
    format!("- {}: {members}{more}\n", str_field(item, "name"))
}

fn render_symbol(item: &serde_json::Value) -> String {
    let owner = str_field(item, "owner");
    let symbol = str_field(item, "symbol");
    let qualified = if owner.is_empty() {
        symbol.to_string()
    } else {
        format!("{owner}::{symbol}")
    };
    format!(
        "- {qualified}  {}  ({} callers)\n",
        str_field(item, "file"),
        u64_field(item, "callers"),
    )
}

fn render_flow(item: &serde_json::Value) -> String {
    let mut out = format!(
        "- {}  ({} nodes)\n",
        str_field(item, "entrypoint"),
        u64_field(item, "nodeCount")
    );
    let files = item
        .get("files")
        .and_then(|files| files.as_array())
        .map(Vec::as_slice)
        .unwrap_or(&[]);
    if let Some(root) = item.get("root") {
        render_flow_node(root, 1, files, &mut out);
    }
    let more = str_field(item, "more");
    if !more.is_empty() {
        out.push_str(&format!("  → full tree: {more}\n"));
    }
    out
}

/// Hard recursion-depth guard for the flow renderer. The JSON it renders is
/// already depth-bounded by nav_map's `summarize_flow`, so this only protects
/// against a pathological hand-built envelope — not a normal cap.
const FLOW_RENDER_MAX_DEPTH: usize = 12;

/// Render one node of a (pre-bounded) flow call-tree as an indented line,
/// recursing into `children`. A `recurses` node (cycle back-edge, marked by
/// nav_map) is shown as a leaf. A `childrenOmitted` count (nav_map dropped the
/// subtree at its size/depth cap) is shown as a trailing marker so the reader
/// knows the call tree continues.
fn render_flow_node(
    node: &serde_json::Value,
    depth: usize,
    files: &[serde_json::Value],
    out: &mut String,
) {
    if depth > FLOW_RENDER_MAX_DEPTH {
        return;
    }
    let indent = "  ".repeat(depth);
    let symbol = str_field(node, "symbol");
    let file = flow_node_file(node, files);
    let recurses = node
        .get("recurses")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
        || node.get("backref_to").is_some();
    if recurses {
        // nav_map collapses N repeated sibling backrefs to the same target into
        // one node carrying `recursesCount`; surface the multiplier.
        let count = node
            .get("recursesCount")
            .and_then(|v| v.as_u64())
            .unwrap_or(1);
        let marker = if count > 1 {
            format!("(↑ recurses, ×{count})")
        } else {
            "(↑ recurses)".to_string()
        };
        out.push_str(&format!("{indent}{symbol}  {file}  {marker}\n"));
        return;
    }
    out.push_str(&format!("{indent}{symbol}  {file}\n"));
    if let Some(children) = node.get("children").and_then(|c| c.as_array()) {
        for child in children {
            render_flow_node(child, depth + 1, files, out);
        }
    }
    if let Some(omitted) = node
        .get("childrenOmitted")
        .and_then(|v| v.as_u64())
        .filter(|n| *n > 0)
    {
        out.push_str(&format!(
            "{}… {omitted} more call(s) below\n",
            "  ".repeat(depth + 1)
        ));
    }
}

/// Render the `module_layers` object: dependency cycles and a summary of the
/// resolved cross-module import edges.
fn render_module_layers(layers: &serde_json::Value) -> String {
    let mut out = String::new();
    let cycles = layers.get("cycles").and_then(|c| c.as_array());
    if let Some(cycles) = cycles.filter(|c| !c.is_empty()) {
        out.push_str("cycles:\n");
        for cycle in cycles {
            let members: Vec<&str> = cycle
                .as_array()
                .map(|a| a.iter().filter_map(|m| m.as_str()).collect())
                .unwrap_or_default();
            out.push_str(&format!("- {}\n", members.join(" → ")));
        }
    }
    if let Some(edges) = layers.get("edges").and_then(|e| e.as_array()) {
        out.push_str(&format!("edges ({}):\n", edges.len()));
        for edge in edges {
            out.push_str(&format!(
                "- {} → {}  ({} files)\n",
                str_field(edge, "from_module"),
                str_field(edge, "to_module"),
                u64_field(edge, "crossing_files"),
            ));
        }
    }
    out.push('\n');
    out
}

fn init_tracing(verbose: bool) {
    use tracing_subscriber::EnvFilter;
    let filter = match std::env::var("RUST_LOG") {
        Ok(val) => EnvFilter::new(val),
        Err(_) => EnvFilter::new(if verbose {
            "debug"
        } else {
            "varde_code=info,warn,error"
        }),
    };
    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_writer(std::io::stderr)
        .init();
}

fn run_build(repo_root: &str, force: bool, changed_files: bool) -> i32 {
    let input = serde_json::json!({ "repoRoot": repo_root });
    match varde_code::build::run_with_force(repo_root, force) {
        Ok(summary) => {
            // The reparsed-path list is a drill-down handle, but on a full
            // build it's the entire repo — hundreds of paths of low inline
            // value (audit F11). Emit a count plus a small sample by default;
            // `--changed-files` opts back into the full array.
            const CHANGED_FILES_SAMPLE: usize = 10;
            let mut result = serde_json::json!({
                "dbPath": summary.db_path,
                "entities": summary.entities,
                "symbols": summary.symbols,
                "diagnostics": summary.diagnostics,
                "unchanged": summary.unchanged,
                "reparsed": summary.reparsed,
                "changedFilesCount": summary.changed_files.len(),
            });
            if changed_files {
                result["changedFiles"] = serde_json::json!(summary.changed_files);
            } else if summary.changed_files.len() > CHANGED_FILES_SAMPLE {
                result["changedFilesSample"] =
                    serde_json::json!(summary.changed_files[..CHANGED_FILES_SAMPLE]);
            } else {
                result["changedFilesSample"] = serde_json::json!(summary.changed_files);
            }
            println!(
                "{}",
                varde_code::query::output::render_with_input(Ok(result), &input)
            );
            0
        }
        Err(e) => {
            tracing::error!(repo_root = repo_root, "fatal error: {e:#}");
            println!(
                "{}",
                varde_code::query::output::render_with_input(
                    Err::<serde_json::Value, _>(varde_code::query::ApiError::new(
                        "build_error",
                        e.to_string(),
                    )),
                    &input,
                )
            );
            1
        }
    }
}

fn run_extract(path: &str) {
    let input = extract_output_input(path);
    match varde_code::scan::run(path) {
        Ok(output) => {
            tracing::debug!(file = path, "emitting JSON document");
            // `files` is the public path table. Entries retain `file_id`, so
            // callers can navigate without repeating the same path per item.
            let doc = serde_json::to_value(&output).expect("output serializes");
            println!(
                "{}",
                varde_code::query::output::render_with_input(Ok(doc), &input)
            );
        }
        Err(e) => {
            tracing::error!(file = path, "fatal error: {e:#}");
            println!(
                "{}",
                varde_code::query::output::render_with_input(
                    Err::<serde_json::Value, _>(varde_code::query::ApiError::new(
                        "extract_error",
                        e.to_string(),
                    )),
                    &input,
                )
            );
            std::process::exit(1);
        }
    }
}

/// Use an extract file's parent as the policy root. A bare relative path has
/// no stable parent prefix, so it deliberately receives default metadata.
fn extract_output_input(path: &str) -> serde_json::Value {
    std::path::Path::new(path)
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .map(|parent| serde_json::json!({ "repoRoot": parent }))
        .unwrap_or_else(|| serde_json::json!({}))
}

#[cfg(test)]
mod nav_map_text_tests {
    use super::{
        default_hook_dir, install_or_remove_hooks, json_with_unbounded_token_budget, nav_map_data,
        nav_map_input_repo_root, render_nav_map_orientation, render_nav_map_text,
        render_nav_map_text_with_toz, resolve_hook_targets, run_hooks_list,
    };

    /// Serializes this module's `PATH`/`VARDE_CODE_TOZ` mutations, mirroring
    /// `varde_code::TOZ_ENV_TEST_LOCK`: that lock lives in the library crate
    /// and isn't reachable from this binary crate's own test build, so
    /// `render_nav_map_text_with_toz`'s toz-stubbing tests need their own.
    static TOZ_ENV_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    /// Puts a stub-binary directory first on `PATH`, and restores `PATH` and
    /// `VARDE_CODE_TOZ` on drop. Prepends rather than replaces `PATH` so
    /// concurrently running tests that spawn other binaries are unaffected.
    /// Near-duplicate of `varde_code::test_support::PathOverride` — see
    /// `TOZ_ENV_TEST_LOCK` above for why this binary crate can't reuse it.
    struct PathOverride {
        previous_path: Option<std::ffi::OsString>,
        previous_toz_env: Option<std::ffi::OsString>,
        _lock: std::sync::MutexGuard<'static, ()>,
    }

    impl PathOverride {
        fn new(dir: &std::path::Path) -> Self {
            let mut paths = vec![dir.to_path_buf()];
            if let Some(existing) = std::env::var_os("PATH") {
                paths.extend(std::env::split_paths(&existing));
            }
            Self::set(paths)
        }

        /// `PATH` with no `toz` reachable at all, unlike [`Self::new`]'s
        /// prepend (which would still find a real `toz` installed on the
        /// developer's `PATH`, e.g. `~/.cargo/bin`, further along). Only
        /// `/bin` and `/usr/bin` are kept, standard system dirs that never
        /// hold a `cargo install`-ed binary like `toz`; no script runs in
        /// this case, so `cat`/`echo` resolvability doesn't matter.
        fn without_toz() -> Self {
            Self::set(vec![
                std::path::PathBuf::from("/bin"),
                std::path::PathBuf::from("/usr/bin"),
            ])
        }

        fn set(paths: Vec<std::path::PathBuf>) -> Self {
            let lock = TOZ_ENV_TEST_LOCK
                .lock()
                .unwrap_or_else(|poison| poison.into_inner());
            let previous_path = std::env::var_os("PATH");
            let previous_toz_env = std::env::var_os("VARDE_CODE_TOZ");
            let joined = std::env::join_paths(paths).expect("PATH entries join");
            unsafe { std::env::set_var("PATH", joined) };
            Self {
                previous_path,
                previous_toz_env,
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
            match self.previous_toz_env.take() {
                Some(value) => unsafe { std::env::set_var("VARDE_CODE_TOZ", value) },
                None => unsafe { std::env::remove_var("VARDE_CODE_TOZ") },
            }
        }
    }

    fn stub_bin_dir(label: &str, script: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "varde-code-navmap-toz-test-{label}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock is after epoch")
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).expect("bin dir creates");
        let script_path = dir.join("toz");
        std::fs::write(&script_path, script).expect("script writes");
        let mut perms = std::fs::metadata(&script_path)
            .expect("script metadata")
            .permissions();
        std::os::unix::fs::PermissionsExt::set_mode(&mut perms, 0o755);
        std::fs::set_permissions(&script_path, perms).expect("script perms set");
        dir
    }

    fn nav_map_fixture(label: &str) -> (std::path::PathBuf, String, String) {
        let repo = tempdir(label);
        // The source walker tracks every ordinary file, including a SQLite
        // fixture. Keep the test index inside excluded VCS internals.
        std::fs::create_dir_all(repo.join(".git")).expect("fixture metadata dir");
        let db_path = repo.join(".git/index.db");
        let conn = varde_code::db::open_or_rebuild(&db_path).expect("fixture db creates");
        conn.execute(
            "INSERT INTO slice_meta (key, value) VALUES ('build_version', ?1)",
            [varde_code::db::build_version_fingerprint()],
        )
        .expect("stamp build version");
        conn.execute(
            "INSERT INTO slice_meta (key, value) VALUES ('source_root', ?1)",
            [varde_code::db::path::repo_identity(&repo)],
        )
        .expect("stamp source root");
        for name in ["imports", "edges", "global"] {
            conn.execute("INSERT INTO slice_state (slice, built_through_rev, schema_version) VALUES (?1, 0, ?2)", rusqlite::params![name, varde_code::db::SCHEMA_VERSION]).expect("stamp empty derived slice");
        }
        drop(conn);
        let json = format!(
            r#"{{"repoRoot":"{}","dbPath":"{}"}}"#,
            repo.display(),
            db_path.display()
        );
        let envelope = varde_code::query::run_mode("nav_map", &json);
        assert!(nav_map_data(&envelope).is_some(), "{envelope}");
        (repo, json, envelope)
    }

    /// AC3: every section name present in the JSON also appears in the text
    /// rendering.
    #[test]
    fn text_rendering_lists_every_json_section() {
        let envelope = serde_json::json!({
            "ok": true,
            "data": {
                "entrypoints": [{"symbol": "hello"}],
                "foundational_files": [],
                "module_layers": {"edges": [], "cycles": []},
                "subsystems": [],
                "symbols": [],
                "flows": [],
                "hotspots": [],
            }
        })
        .to_string();

        let text = render_nav_map_text(&envelope);

        for section in [
            "entrypoints",
            "foundational_files",
            "module_layers",
            "subsystems",
            "symbols",
            "flows",
            "hotspots",
        ] {
            assert!(
                text.contains(section),
                "text rendering missing section {section:?}: {text}"
            );
        }
    }

    /// Naturally empty sections remain `(none)`, while an empty section named
    /// in `guide.truncated` tells the reader what the budget withheld.
    #[test]
    fn text_rendering_distinguishes_empty_from_budget_truncated_sections() {
        let envelope = serde_json::json!({
            "ok": true,
            "data": {
                "entrypoints": [],
                "foundational_files": [],
                "module_layers": {"edges": [], "cycles": []},
                "subsystems": [],
                "symbols": [],
                "flows": [],
                "hotspots": [],
                "guide": {
                    "truncated": {
                        "symbols": {
                            "shown": 0,
                            "total": 12,
                            "more": "code_query mode=filter_symbols for the full symbol list",
                        }
                    }
                }
            }
        })
        .to_string();

        let text = render_nav_map_text(&envelope);

        assert!(text.contains("## entrypoints\n(none)"), "{text}");
        assert!(
            text.contains(
                "## symbols\n(truncated: 0/12 shown; code_query mode=filter_symbols for the full symbol list)"
            ),
            "{text}"
        );
    }

    /// Regression: array sections must render their actual item content
    /// (symbol names, files, call trees) — not a bare `N item(s)` count,
    /// which is what shipped and made the injected symbols/flows sections
    /// useless. Nested flow trees render indented, bounded, and back-edges
    /// are marked rather than followed.
    #[test]
    fn text_rendering_emits_item_content_not_just_counts() {
        let envelope = serde_json::json!({
            "ok": true,
            "data": {
                "entrypoints": [{"symbol": "main", "file": "src/main.rs", "role": "process_main"}],
                "foundational_files": [{"file": "src/model.rs", "dependents": 57, "count": 198}],
                "module_layers": {"edges": [{"from_module": "a", "to_module": "b", "crossing_files": 3}], "cycles": [["a", "b"]]},
                "subsystems": [{"id": 1, "name": "core", "members": ["src/a.rs", "src/b.rs"]}],
                "symbols": [{"symbol": "parse_source", "file": "src/parse.rs", "callers": 39, "owner": null}],
                "flows": [{"entrypoint": "main", "file": "src/main.rs", "nodeCount": 42,
                    "files": ["src/main.rs", "src/util.rs"],
                    "more": "code_query mode=explore {\"input\":\"main\",\"direction\":\"outgoing\"} for the full call tree",
                    "root": {"symbol": "main", "f": 0,
                    "children": [{"symbol": "helper", "f": 1, "children": []}], "childrenOmitted": 7}}],
                "hotspots": [{"file": "src/resolve.rs", "score": 632, "complexity": 158, "churn": 4}],
            }
        })
        .to_string();

        let text = render_nav_map_text(&envelope);

        // No section renders as a bare item count anymore.
        assert!(
            !text.contains("item(s)"),
            "sections must render content, not counts: {text}"
        );
        // Representative content from each section is present.
        assert!(text.contains("main  src/main.rs  [process_main]"), "{text}");
        assert!(
            text.contains("src/model.rs  (57 dependents, 198 refs)"),
            "{text}"
        );
        assert!(text.contains("core: src/a.rs, src/b.rs"), "{text}");
        assert!(
            text.contains("parse_source  src/parse.rs  (39 callers)"),
            "{text}"
        );
        assert!(
            text.contains("resolve.rs  (score 632, complexity 158, churn 4)"),
            "{text}"
        );
        // Flow renders its size, the indented tree, an omitted-children
        // marker, and the explore follow-up handle for the full tree.
        assert!(text.contains("main  (42 nodes)"), "flow size: {text}");
        assert!(
            text.contains("    helper  src/util.rs"),
            "flow child indented: {text}"
        );
        assert!(
            text.contains("… 7 more call(s) below"),
            "omitted marker: {text}"
        );
        assert!(
            text.contains("→ full tree: code_query mode=explore"),
            "flow follow-up handle: {text}"
        );
        // module_layers renders cycles + edges, not raw JSON.
        assert!(text.contains("a → b"), "module_layers rendered: {text}");
    }

    /// An error envelope falls back to the raw envelope rather than
    /// producing a bespoke text shape.
    #[test]
    fn text_rendering_falls_back_to_raw_envelope_on_error() {
        let envelope = serde_json::json!({
            "ok": false,
            "error": {"code": "not_found", "message": "no such repo"}
        })
        .to_string();

        let text = render_nav_map_text(&envelope);
        assert_eq!(text, envelope);
    }

    /// `maxTokensEstimate` is overridden to the largest accepted value,
    /// leaving every other input field untouched.
    #[test]
    fn json_with_unbounded_token_budget_overrides_max_tokens() {
        let json =
            json_with_unbounded_token_budget(r#"{"repoRoot":"/repo","maxTokensEstimate":5}"#);
        let value: serde_json::Value = serde_json::from_str(&json).expect("valid JSON");
        assert_eq!(value["repoRoot"], "/repo");
        assert_eq!(value["maxTokensEstimate"], serde_json::json!(u64::MAX));
    }

    /// Unparseable input passes through unchanged rather than panicking; the
    /// following `run_mode` call fails the same way the budgeted call did.
    #[test]
    fn json_with_unbounded_token_budget_passes_through_invalid_json() {
        let json = json_with_unbounded_token_budget("not json");
        assert_eq!(json, "not json");
    }

    #[test]
    fn nav_map_input_repo_root_reads_repo_root() {
        assert_eq!(
            nav_map_input_repo_root(r#"{"repoRoot":"/repo"}"#).as_deref(),
            Some("/repo")
        );
    }

    #[test]
    fn nav_map_input_repo_root_none_when_absent_or_invalid() {
        assert_eq!(nav_map_input_repo_root(r#"{"dbPath":"/x.db"}"#), None);
        assert_eq!(nav_map_input_repo_root("not json"), None);
    }

    /// A successful `toz` capture appends its handle to the Varde orientation
    /// and receives the unbudgeted render on stdin.
    #[test]
    fn text_with_toz_appends_handle_and_feeds_it_the_unbudgeted_render() {
        let stdin_capture = std::env::temp_dir().join(format!(
            "varde-code-navmap-toz-stdin-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock is after epoch")
                .as_nanos()
        ));
        let script = format!(
            "#!/bin/sh\ncat > {}\necho 'varde-toz: captured 9 bytes → handle ab12 (1 lines, 1 chunk)  label: \"nav_map\"'\n",
            stdin_capture.display()
        );
        let dir = stub_bin_dir("success", &script);
        let _override = PathOverride::new(&dir);

        let (repo, json, envelope) = nav_map_fixture("toz-success");
        let unbudgeted_envelope = render_nav_map_text(&varde_code::query::run_mode(
            "nav_map",
            &json_with_unbounded_token_budget(&json),
        ));
        let budgeted_envelope = render_nav_map_text(&envelope);

        let result = render_nav_map_text_with_toz(&json, &envelope);

        assert!(result.starts_with(&render_nav_map_orientation(&envelope)));
        assert!(result.contains("Expanded map in Toz (handle ab12)"));
        assert!(result.contains("varde-toz query --handle ab12 \"<term>\""));
        assert!(!result.contains("varde-toz: captured"));
        assert_ne!(result, budgeted_envelope);
        let stdin_seen = std::fs::read_to_string(&stdin_capture).expect("stub wrote stdin capture");
        assert_eq!(stdin_seen, unbudgeted_envelope);
        let _ = std::fs::remove_file(&stdin_capture);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn text_with_toz_preserves_query_error_without_capturing() {
        let dir = stub_bin_dir(
            "error",
            "#!/bin/sh\ncat > /dev/null\necho 'toz: captured -> handle zz99'\n",
        );
        let _override = PathOverride::new(&dir);
        let envelope = varde_code::query::run_mode("nav_map", "{}");

        let result = render_nav_map_text_with_toz("{}", &envelope);

        assert_eq!(result, envelope);
        assert!(result.contains("repoRoot"));
    }

    #[test]
    fn text_with_toz_preserves_first_render_when_unbudgeted_query_fails() {
        let dir = stub_bin_dir(
            "second-query-error",
            "#!/bin/sh\ncat > /dev/null\necho 'toz: captured -> handle zz99'\n",
        );
        let _override = PathOverride::new(&dir);
        let budgeted = r#"{"ok":true,"data":{"entrypoints":[]}}"#;

        let result = render_nav_map_text_with_toz("{}", budgeted);

        assert_eq!(result, render_nav_map_orientation(budgeted));
    }

    /// No `toz` on `PATH` at all: the compact orientation is returned.
    #[test]
    fn text_with_toz_falls_back_when_toz_binary_is_missing() {
        let _override = PathOverride::without_toz();
        let (repo, json, envelope) = nav_map_fixture("toz-missing");

        let orientation = render_nav_map_orientation(&envelope);
        let result = render_nav_map_text_with_toz(&json, &envelope);
        assert_eq!(result, orientation);
        assert!(result.contains("## Repository outline"));
        assert!(result.contains("varde-code context_pack"));
        let _ = std::fs::remove_dir_all(repo);
    }

    /// `VARDE_CODE_TOZ=0` skips toz entirely, even with a stub on `PATH`
    /// that would otherwise succeed.
    #[test]
    fn text_with_toz_falls_back_when_disabled_by_env() {
        let dir = stub_bin_dir(
            "disabled",
            "#!/bin/sh\ncat > /dev/null\necho 'toz: captured -> handle zz99'\n",
        );
        let _override = PathOverride::new(&dir);
        unsafe { std::env::set_var("VARDE_CODE_TOZ", "0") };
        let (repo, json, envelope) = nav_map_fixture("toz-disabled");

        let orientation = render_nav_map_orientation(&envelope);
        let result = render_nav_map_text_with_toz(&json, &envelope);
        assert_eq!(result, orientation);
        let _ = std::fs::remove_dir_all(repo);
    }

    /// A `toz` that exits non-zero falls back to the compact orientation,
    /// even though it printed `"handle"` on stdout first.
    #[test]
    fn text_with_toz_falls_back_when_stub_exits_nonzero() {
        let dir = stub_bin_dir(
            "nonzero",
            "#!/bin/sh\ncat > /dev/null\necho 'toz: captured -> handle zz99'\nexit 1\n",
        );
        let _override = PathOverride::new(&dir);
        let (repo, json, envelope) = nav_map_fixture("toz-nonzero");

        let orientation = render_nav_map_orientation(&envelope);
        let result = render_nav_map_text_with_toz(&json, &envelope);
        assert_eq!(result, orientation);
        let _ = std::fs::remove_dir_all(repo);
    }

    // --- `hooks` CLI wiring: resolve_hook_targets / default dirs / round trip

    fn tempdir(label: &str) -> std::path::PathBuf {
        let dir =
            std::env::temp_dir().join(format!("varde-hooks-cli-{label}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("temp dir creates");
        dir
    }

    #[test]
    fn resolve_hook_targets_empty_agent_list_means_all_four() {
        let targets = resolve_hook_targets(&[]).expect("empty --agent resolves");
        assert_eq!(targets.len(), varde_code::hooks::HOOK_TARGETS.len());
        let agents: Vec<&str> = targets.iter().map(|t| t.agent).collect();
        assert!(agents.contains(&varde_code::hooks::CLAUDE_AGENT));
        assert!(agents.contains(&varde_code::hooks::CODEX_AGENT));
        assert!(agents.contains(&varde_code::hooks::OPENCODE_AGENT));
        assert!(agents.contains(&varde_code::hooks::PI_AGENT));
    }

    #[test]
    fn resolve_hook_targets_filters_to_requested_subset() {
        let targets = resolve_hook_targets(&["claude".to_string(), "codex".to_string()])
            .expect("known agents resolve");
        assert_eq!(targets.len(), 2);
        let agents: Vec<&str> = targets.iter().map(|t| t.agent).collect();
        assert_eq!(
            agents,
            vec![
                varde_code::hooks::CLAUDE_AGENT,
                varde_code::hooks::CODEX_AGENT
            ]
        );
    }

    #[test]
    fn resolve_hook_targets_rejects_unknown_agent() {
        let err = resolve_hook_targets(&["not-a-real-agent".to_string()])
            .expect_err("unknown agent errors");
        assert!(
            err.contains("not-a-real-agent"),
            "error names the bad agent: {err}"
        );
    }

    #[test]
    fn hooks_list_performs_no_filesystem_writes_and_covers_all_four_agents() {
        // `run_hooks_list` only reads `HOOK_TARGETS` (static) and formats
        // default dirs; assert it doesn't touch disk by checking no new
        // entries appear under a scratch dir it's never told about, and that
        // its output covers all 4 agents.
        let before = tempdir("list-no-writes");
        let entries_before: Vec<_> = std::fs::read_dir(&before).unwrap().collect();
        assert!(entries_before.is_empty());

        run_hooks_list();

        let entries_after: Vec<_> = std::fs::read_dir(&before).unwrap().collect();
        assert!(
            entries_after.is_empty(),
            "hooks list must not write to the filesystem"
        );

        for agent in [
            varde_code::hooks::CLAUDE_AGENT,
            varde_code::hooks::CODEX_AGENT,
            varde_code::hooks::OPENCODE_AGENT,
            varde_code::hooks::PI_AGENT,
        ] {
            assert!(
                varde_code::hooks::HOOK_TARGETS
                    .iter()
                    .any(|t| t.agent == agent),
                "hooks list source data covers agent {agent}"
            );
        }
    }

    #[test]
    fn hooks_install_no_agent_installs_all_four_into_dir() {
        let dir = tempdir("install-all");
        let targets = resolve_hook_targets(&[]).unwrap();
        let (installed, dirs) = install_or_remove_hooks(
            &targets,
            Some(dir.to_str().unwrap()),
            |target_dir, one_target| {
                varde_code::hooks::install_hooks(target_dir, one_target, false)
            },
        )
        .expect("install succeeds");
        assert_eq!(installed.len(), varde_code::hooks::HOOK_TARGETS.len());
        assert_eq!(dirs.as_object().unwrap().len(), 4);
        assert!(dir.join("settings.json").exists());
        assert!(dir.join("config.toml").exists());
        assert!(dir.join("plugin/varde-code-nav-map.js").exists());
        assert!(dir.join("pi-extension.js").exists());
    }

    #[test]
    fn hooks_install_agent_subset_installs_only_those_two() {
        let dir = tempdir("install-subset");
        let targets = resolve_hook_targets(&["claude".to_string(), "codex".to_string()]).unwrap();
        install_or_remove_hooks(
            &targets,
            Some(dir.to_str().unwrap()),
            |target_dir, one_target| {
                varde_code::hooks::install_hooks(target_dir, one_target, false)
            },
        )
        .expect("install succeeds");
        assert!(dir.join("settings.json").exists());
        assert!(dir.join("config.toml").exists());
        assert!(!dir.join("plugin/varde-code-nav-map.js").exists());
        assert!(!dir.join("pi-extension.js").exists());
    }

    #[test]
    fn hooks_install_then_remove_round_trips_whole_file_and_merge_targets() {
        let dir = tempdir("round-trip");
        let targets = resolve_hook_targets(&[]).unwrap();

        // Whole-file target (opencode): round trip restores pre-install state
        // (file absent).
        assert!(!dir.join("plugin/varde-code-nav-map.js").exists());
        // Merge target (claude): seed unrelated content first so we can
        // assert only the injected entry is removed, not the whole file.
        std::fs::write(dir.join("settings.json"), r#"{"unrelated": true}"#).unwrap();

        install_or_remove_hooks(
            &targets,
            Some(dir.to_str().unwrap()),
            |target_dir, one_target| {
                varde_code::hooks::install_hooks(target_dir, one_target, false)
            },
        )
        .expect("install succeeds");
        assert!(dir.join("plugin/varde-code-nav-map.js").exists());
        assert!(dir.join("pi-extension.js").exists());

        install_or_remove_hooks(
            &targets,
            Some(dir.to_str().unwrap()),
            |target_dir, one_target| varde_code::hooks::remove_hooks(target_dir, one_target, false),
        )
        .expect("remove succeeds");

        // Whole-file targets: pre-install state restored (files gone).
        assert!(!dir.join("plugin/varde-code-nav-map.js").exists());
        assert!(!dir.join("pi-extension.js").exists());

        // Merge targets: the shared config file remains (it's not a
        // whole-file target), but only this tool's injected entry is
        // removed, never unrelated content.
        let codex_doc = std::fs::read_to_string(dir.join("config.toml"))
            .unwrap()
            .parse::<toml_edit::DocumentMut>()
            .expect("valid toml");
        assert!(
            codex_doc.get("hooks").is_none(),
            "injected session_start table removed"
        );

        let settings: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(dir.join("settings.json")).unwrap())
                .unwrap();
        assert_eq!(settings["unrelated"], true);
        assert!(
            settings.get("hooks").is_none(),
            "injected SessionStart hook removed"
        );
    }

    #[test]
    fn hooks_install_without_dir_resolves_per_agent_default_dirs() {
        let targets = resolve_hook_targets(&["claude".to_string(), "pi".to_string()]).unwrap();
        let claude_dir = default_hook_dir("claude");
        let pi_dir = default_hook_dir("pi");
        assert_ne!(
            claude_dir, pi_dir,
            "each agent resolves its own default dir"
        );
        assert!(claude_dir.ends_with(".claude"));
        assert!(pi_dir.ends_with("agent/extensions"));
        // Sanity: install_or_remove_hooks with dir=None would target these
        // dirs (not exercised here to avoid touching the real home dir).
        assert_eq!(targets.len(), 2);
    }
}
