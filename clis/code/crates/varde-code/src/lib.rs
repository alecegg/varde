//! varde-code: code-intelligence core.
//!
//! Multi-language tree-sitter parsing and entity/symbol extraction, exposed
//! as a library and a small CLI (`varde-code extract <path>`).

pub mod ast_edit;
pub mod build;
pub mod certified;
pub mod churn;
pub mod cli;
pub mod complexity;
pub mod db;
pub mod extract;
pub mod git;
pub mod hooks;
pub mod index_prune;
pub mod model;
pub mod parse;
pub mod persist;
pub mod query;
pub mod repo_lock;
pub mod resolve;
pub mod rules;
pub mod scan;
pub mod scan_cli;
pub mod scan_setup;
pub mod slice;
pub mod test_cli;
pub mod toz;
pub mod watch;

#[cfg(test)]
mod test_support;

/// Shared guard for tests that mutate the process-global `HOME` (which drives
/// [`crate::db::path::repo_db_path`]). Every test that redirects `HOME` must
/// hold this lock so concurrent test threads don't interleave set/restore.
///
/// Not `#[cfg(test)]`-gated: `rules::test_runner::run_sql_rule_tests` (a
/// non-test, library-facing entry point used by the `test` CLI subcommand)
/// also takes this lock while it builds+indexes a fixture, so that its
/// `HOME` reads can't land mid-swap against a `#[test]` in the same binary
/// that's temporarily redirecting `HOME`. The mutex is a no-op outside of
/// test binaries (nothing else ever contends it), so this costs nothing in
/// production.
pub(crate) static HOME_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// Test-only pin for the Cost A git-status changed_files fast path
/// ([`crate::slice::git_fast_path_enabled`]): tests ignore the
/// `VARDE_CODE_GIT_FAST_PATH` env var entirely and decide via this flag, so CI is
/// deterministic regardless of the developer's shell. All slice tests
/// serialize on [`HOME_TEST_LOCK`], so it cannot race another slice test.
#[cfg(test)]
pub(crate) static GIT_FAST_PATH_TEST_OVERRIDE: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

/// Shared guard for tests that swap the installed toz capture (or set
/// `VARDE_CODE_TOZ`, to disable [`crate::toz::capture_text`] outright). Every
/// such test acquires this lock via [`crate::test_support::CaptureOverride`]
/// so concurrent test threads don't interleave capture/env swaps.
#[cfg(test)]
pub(crate) static TOZ_ENV_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// Test-only call counter for [`crate::slice::run_scoped_edge_refresh`]
/// (CORE-GRAPH-CACHE-001's shared scoped edge engine), incremented on every
/// invocation regardless of caller (`slice::freshen_edges` or
/// `build::run_incremental`). Lets a test prove the scoped path — as opposed
/// to a full re-derivation — actually ran, since neither `rev` numbering nor
/// row counts alone distinguish the two paths in every fixture shape. Reads
/// racily against any other test that also drives the scoped path, so
/// callers should compare a before/after delta and run under a module-scoped
/// filter (e.g. `cargo test build::`) rather than the whole suite at once.
#[cfg(test)]
pub(crate) static SCOPED_EDGE_REFRESH_CALLS: std::sync::atomic::AtomicUsize =
    std::sync::atomic::AtomicUsize::new(0);

/// Serializes every `build::` test that reads [`SCOPED_EDGE_REFRESH_CALLS`]
/// (directly, or indirectly by driving `run_incremental` down a path that
/// calls the shared scoped edge engine) so cargo's default parallel test
/// threads can't interleave increments from one test into another's
/// before/after delta.
#[cfg(test)]
pub(crate) static SCOPED_EDGE_REFRESH_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// Test-only call counter for the `graph_cache` fast path in
/// [`crate::query::graph::Graph::load`] (wire-graph-load-cache-first),
/// incremented every time `Graph::load` returns a cache hit (fresh-rev row,
/// decoded successfully) instead of running the full SQL-scan rebuild. Lets a
/// test prove the cache path — as opposed to the full rebuild — actually ran.
/// Reads racily against any other test that also drives `Graph::load`, so
/// callers should compare a before/after delta.
#[cfg(test)]
pub(crate) static GRAPH_CACHE_HIT_CALLS: std::sync::atomic::AtomicUsize =
    std::sync::atomic::AtomicUsize::new(0);

use crate::cli::{Cli, Command};
use clap::Parser;
use std::ffi::OsString;
use std::process::ExitCode;

/// The clap command tree (hidden commands included), for tools that map it.
pub fn cli_command() -> clap::Command {
    <cli::Cli as clap::CommandFactory>::command()
}

/// Run the `varde-code` CLI with `args` (including the program name) and
/// return its process exit code. Query-mode errors never produce a non-zero
/// exit (they are carried inside the JSON envelope).
pub fn run(args: Vec<OsString>, io: &varde_contracts::Io<'static>) -> ExitCode {
    if io.capture.is_some() {
        toz::install_capture(io.capture);
    }
    install_panic_hook();
    let cli = Cli::parse_from(args);
    init_tracing(cli.verbose);
    dispatch_command(cli.command)
}

fn exit_code(code: i32) -> ExitCode {
    ExitCode::from(code as u8)
}

fn dispatch_command(command: Command) -> ExitCode {
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
        } => run_nav_map(&json, &format, with_project_knowledge),
        Command::Extract { path } => return exit_code(run_extract(&path)),
        Command::Build {
            repo_root,
            force,
            changed_files,
        } => return exit_code(run_build(&repo_root, force, changed_files)),
        // `scan` is a read-and-report operation like the query modes, but it
        // must be able to exit non-zero (findings at/above the severity
        // threshold → CI gate), so it gets its own dispatch arm instead of
        // `run_query` (which never exits non-zero by contract).
        Command::Scan { json, apply, force } => return exit_code(run_scan(&json, apply, force)),
        // `prune` is not a query mode: it reads the config root, not a repo
        // index, so it dispatches through the envelope directly.
        Command::Prune { json } => run_prune(&json),
        // `test` is a read-and-report operation like `scan`: it must exit
        // non-zero when any `[[test]]` case fails (CI gate), so it gets its
        // own dispatch arm instead of `run_query`.
        Command::Test { json } => return exit_code(run_test(&json)),
        Command::RulesList { json } => run_rules_list(&json),
        Command::RulesSeed { json, user, force } => run_rules_seed(&json, user, force),
        Command::RulesRemove { json, user, force } => run_rules_remove(&json, user, force),
        Command::Watch {
            repos,
            config,
            debounce_ms,
            list,
            ensure,
            stop,
            remove_index,
            stop_all,
        } => {
            return exit_code(if list {
                run_watch_list()
            } else if ensure {
                run_watch_ensure(&repos)
            } else if stop_all {
                run_watch_stop_all()
            } else if stop && remove_index {
                run_watch_stop_and_remove_index(&repos, config.as_deref())
            } else if stop {
                run_watch_stop(&repos, config.as_deref())
            } else if remove_index {
                run_watch_invalid("--remove-index requires --stop")
            } else {
                run_watch(&repos, config.as_deref(), debounce_ms)
            });
        }
    }
    ExitCode::SUCCESS
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
            println!("{}", crate::query::render(Err(error)));
            return 1;
        }
    };
    if !value.is_object() {
        println!(
            "{}",
            crate::query::render(Err(crate::query::ApiError::new(
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
        render_preprocessed_envelope(crate::scan_cli::scan_repo(&value), &value);

    if let Some(path) = value.get("output").and_then(|o| o.as_str()) {
        if let Err(e) = std::fs::write(path, &envelope) {
            println!(
                "{}",
                crate::query::render(Err(crate::query::ApiError::new(
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
            println!("{}", crate::query::render(Err(error)));
            return 1;
        }
    };

    let (envelope, payload) = render_envelope(crate::test_cli::run_tests(&value), &value);
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
    result: Result<serde_json::Value, crate::query::ApiError>,
    input: &serde_json::Value,
) -> (String, serde_json::Value) {
    finish_envelope(crate::query::output::render_value_with_input(result, input))
}

/// Render a payload whose producer already applied output compaction.
fn render_preprocessed_envelope(
    result: Result<serde_json::Value, crate::query::ApiError>,
    input: &serde_json::Value,
) -> (String, serde_json::Value) {
    finish_envelope(crate::query::output::render_value_with_preprocessed_input(
        result, input,
    ))
}

fn finish_envelope(payload: serde_json::Value) -> (String, serde_json::Value) {
    let envelope = payload.to_string();
    (envelope, payload)
}

/// Resolve the watch list (explicit `--repo`s + optional config file, or
/// the default `<varde config root>/code/watch.toml` (usually
/// `~/.config/varde/code/watch.toml`) when neither is given),
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
            crate::query::render(Err::<serde_json::Value, _>(crate::query::ApiError::new(
                "invalid_input",
                "--ensure requires exactly one --repo"
            )))
        );
        return 1;
    }
    let resolved = match crate::watch::resolve_repos(repos, None) {
        Ok(paths) => paths,
        Err(err) => {
            println!(
                "{}",
                crate::query::render(Err::<serde_json::Value, _>(crate::query::ApiError::new(
                    "invalid_input",
                    err.to_string()
                )))
            );
            return 1;
        }
    };
    match crate::watch::ensure(&resolved[0]) {
        Ok(status) => {
            println!(
                "{}",
                crate::query::render(serde_json::to_value(status).map_err(|err| {
                    crate::query::ApiError::new("serialization_error", err.to_string())
                }))
            );
            0
        }
        Err(err) => {
            println!(
                "{}",
                crate::query::render(Err::<serde_json::Value, _>(crate::query::ApiError::new(
                    "watch_error",
                    err.to_string()
                )))
            );
            1
        }
    }
}

fn run_watch(repos: &[String], config_path: Option<&str>, debounce_ms: u64) -> i32 {
    // A registered watcher whose repo is gone unregisters itself and exits 0
    // so host supervision does not restart it.
    if crate::watch::should_retire(repos, config_path.is_some()) {
        return match crate::watch::retire(std::path::Path::new(&repos[0])) {
            Ok(()) => 0,
            Err(err) => {
                println!(
                    "{}",
                    crate::query::render(Err::<serde_json::Value, _>(crate::query::ApiError::new(
                        "watch_error",
                        err.to_string()
                    )))
                );
                1
            }
        };
    }
    let resolved = match resolve_watch_repos(repos, config_path) {
        Ok(resolved) => resolved,
        Err(err) => {
            println!("{}", crate::query::render(Err(err)));
            return 1;
        }
    };

    match crate::watch::run(&resolved, std::time::Duration::from_millis(debounce_ms)) {
        Ok(()) => 0,
        Err(err) => {
            println!(
                "{}",
                crate::query::render(Err::<serde_json::Value, _>(crate::query::ApiError::new(
                    "watch_error",
                    err.to_string()
                )))
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
) -> Result<Vec<std::path::PathBuf>, crate::query::ApiError> {
    let config = match config_path {
        Some(path) => match crate::watch::WatchConfig::load(std::path::Path::new(path)) {
            Ok(config) => Some(config),
            Err(err) => {
                return Err(crate::query::ApiError::new(
                    "invalid_input",
                    err.to_string(),
                ));
            }
        },
        None => {
            let default_path = crate::watch::WatchConfig::default_path();
            if repos.is_empty() && default_path.exists() {
                match crate::watch::WatchConfig::load(&default_path) {
                    Ok(config) => Some(config),
                    Err(err) => {
                        return Err(crate::query::ApiError::new(
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

    crate::watch::resolve_repos(repos, config.as_ref())
        .map_err(|err| crate::query::ApiError::new("invalid_input", err.to_string()))
}

/// `varde-code watch --list`: print every watcher instance (live or
/// stale-locked) as a JSON array and exit 0. Never exits non-zero — this is
/// a read-only listing, same posture as `rules_list`/`slice_state`.
fn run_watch_list() -> i32 {
    match crate::watch::list_instances() {
        Ok(instances) => {
            println!(
                "{}",
                crate::query::render(serde_json::to_value(instances).map_err(|err| {
                    crate::query::ApiError::new("serialization_error", err.to_string())
                }))
            );
            0
        }
        Err(err) => {
            println!(
                "{}",
                crate::query::render(Err::<serde_json::Value, _>(crate::query::ApiError::new(
                    "watch_error",
                    err.to_string()
                )))
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
            println!("{}", crate::query::render(Err(err)));
            return 1;
        }
    };
    match crate::watch::stop(&resolved) {
        Ok(outcome) => {
            println!(
                "{}",
                crate::query::render(serde_json::to_value(outcome).map_err(|err| {
                    crate::query::ApiError::new("serialization_error", err.to_string())
                }))
            );
            0
        }
        Err(err) => {
            println!(
                "{}",
                crate::query::render(Err::<serde_json::Value, _>(crate::query::ApiError::new(
                    "watch_error",
                    err.to_string()
                )))
            );
            1
        }
    }
}

/// Stop one repo watcher, then remove the repo's derived code index.
fn run_watch_stop_and_remove_index(repos: &[String], config_path: Option<&str>) -> i32 {
    if config_path.is_some() || repos.len() != 1 {
        return run_watch_invalid(
            "--stop --remove-index requires exactly one --repo and no --config",
        );
    }
    let resolved = match resolve_watch_repos(repos, None) {
        Ok(resolved) => resolved,
        Err(err) => {
            println!("{}", crate::query::render(Err(err)));
            return 1;
        }
    };
    match crate::watch::stop_and_remove_index(&resolved[0]) {
        Ok((watcher, index_removed)) => {
            println!(
                "{}",
                crate::query::render(Ok::<_, crate::query::ApiError>(serde_json::json!({
                    "watcher": watcher,
                    "indexRemoved": index_removed,
                })))
            );
            0
        }
        Err(err) => {
            println!(
                "{}",
                crate::query::render(Err::<serde_json::Value, _>(crate::query::ApiError::new(
                    "watch_error",
                    err.to_string()
                )))
            );
            1
        }
    }
}

fn run_watch_invalid(message: &str) -> i32 {
    println!(
        "{}",
        crate::query::render(Err::<serde_json::Value, _>(crate::query::ApiError::new(
            "invalid_input",
            message
        )))
    );
    1
}

/// `varde-code watch --stop-all`: stop every running watcher instance and
/// exit. Non-zero only if enumerating instances itself fails; a per-instance
/// stop failure is reported inline in the JSON output, not a process exit.
fn run_watch_stop_all() -> i32 {
    match crate::watch::stop_all() {
        Ok(outcomes) => {
            println!(
                "{}",
                crate::query::render(serde_json::to_value(outcomes).map_err(|err| {
                    crate::query::ApiError::new("serialization_error", err.to_string())
                }))
            );
            0
        }
        Err(err) => {
            println!(
                "{}",
                crate::query::render(Err::<serde_json::Value, _>(crate::query::ApiError::new(
                    "watch_error",
                    err.to_string()
                )))
            );
            1
        }
    }
}

/// Run one `prune` invocation: parses input, delegates to
/// `index_prune::run`, prints the uniform envelope. Never exits non-zero —
/// pruning index caches is not a CI gate.
fn run_prune(json: &str) {
    let value = match parse_json_input(json) {
        Ok(value) => value,
        Err(error) => {
            println!("{}", crate::query::render(Err(error)));
            return;
        }
    };
    let (envelope, _) = render_envelope(crate::index_prune::run(&value), &value);
    println!("{envelope}");
}

/// Run one `rules_list` invocation: parses input, delegates to
/// `scan_cli::rules_list`, prints the uniform envelope. Never exits
/// non-zero — this is a read-only listing, not a CI gate like `scan`.
fn run_rules_list(json: &str) {
    let value = match parse_json_input(json) {
        Ok(value) => value,
        Err(error) => {
            println!("{}", crate::query::render(Err(error)));
            return;
        }
    };
    println!(
        "{}",
        crate::query::output::render_with_input(crate::scan_cli::rules_list(&value), &value)
    );
}

/// Run one `rules_seed` invocation: parses input, delegates to
/// `scan_cli::rules_seed`, prints the uniform envelope. Never exits
/// non-zero — writing seed files is not a CI gate.
fn run_rules_seed(json: &str, user: bool, force: bool) {
    let value = match parse_json_input(json) {
        Ok(value) => value,
        Err(error) => {
            println!("{}", crate::query::render(Err(error)));
            return;
        }
    };
    println!(
        "{}",
        crate::query::output::render_with_input(
            crate::scan_cli::rules_seed(&value, user, force),
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
            println!("{}", crate::query::render(Err(error)));
            return;
        }
    };
    println!(
        "{}",
        crate::query::output::render_with_input(
            crate::scan_cli::rules_remove(&value, user, force),
            &value,
        )
    );
}

fn run_query(mode: &str, json: &str) {
    println!("{}", crate::query::run_mode(mode, json));
}

fn parse_json_input(json: &str) -> Result<serde_json::Value, crate::query::ApiError> {
    serde_json::from_str(json).map_err(|error| {
        crate::query::ApiError::new("invalid_input", format!("input is not valid JSON: {error}"))
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
    if format == "text" {
        println!("{}", nav_map_text(json, with_project_knowledge));
    } else {
        println!("{}", crate::query::run_mode("nav_map", json));
    }
}

/// Build a full index of `repo_root` at an explicit `db_path`, for callers
/// (such as test fixtures) that must not depend on the `HOME`-derived path.
pub fn build_index_at(repo_root: &str, db_path: &std::path::Path) -> anyhow::Result<()> {
    let _lock = repo_lock::acquire(db_path, std::time::Duration::from_secs(30))?;
    // An explicit `db_path` still yields an index folder `prune` may scan, so
    // record its source root like every other build; this path never goes
    // through `build::run_with_force`.
    crate::db::path::record_source_root(db_path, std::path::Path::new(repo_root))?;
    build::run_full_while_locked(repo_root, db_path).map(|_| ())
}

/// The `--format text` rendering of `nav_map` that [`run_nav_map`] prints.
/// A query error comes back as its raw envelope text.
pub fn nav_map_text(json: &str, with_project_knowledge: bool) -> String {
    let envelope = crate::query::run_mode("nav_map", json);
    let value = serde_json::from_str(&envelope).ok();
    let data = value.as_ref().and_then(successful_nav_map_data);
    let map = render_nav_map_text_with_toz_data(json, &envelope, data);
    if with_project_knowledge
        && data.is_some()
        && let Some(knowledge) = render_project_knowledge(json)
    {
        return format!("{knowledge}\n\n{map}");
    }
    map
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
        "Project knowledge: memory-bank/knowledge/ (use varde knowledge concept search --bundle memory-bank/knowledge --text <term>).",
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
    if data.is_none() || !crate::toz::enabled() {
        return orientation;
    }
    let unbudgeted_json = json_with_unbounded_token_budget(json);
    let unbudgeted_envelope = crate::query::run_mode("nav_map", &unbudgeted_json);
    let unbudgeted_value = serde_json::from_str(&unbudgeted_envelope).ok();
    let Some(unbudgeted_data) = unbudgeted_value.as_ref().and_then(successful_nav_map_data) else {
        return orientation;
    };
    let unbudgeted_text = render_nav_map_text_data(unbudgeted_data);
    let repo_root = nav_map_input_repo_root(json).unwrap_or_default();
    let source = format!("varde map nav_map {repo_root}");
    let Some(handle) = crate::toz::capture_text(&source, "nav_map", &unbudgeted_text)
        .and_then(|preview| toz_capture_handle(&preview).map(str::to_owned))
    else {
        return orientation;
    };
    orientation.push_str(&format!(
        "\nExpanded map in Toz (handle {handle}). Search: `varde run query --handle {handle} \"<term>\"`; read lines: `varde run query --handle {handle} --lines 1:80`.\n"
    ));
    orientation
}

/// Accept only Toz's standard capture header and a simple handle token.
/// Other successful-looking output is not enough to claim a stored capture.
fn toz_capture_handle(stdout: &str) -> Option<&str> {
    let first_line = stdout.lines().next()?.trim_end_matches('\r');
    let (byte_count, capture) = first_line
        .strip_prefix("varde: captured ")?
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
        "- Find a declaration by name: `varde map get_symbol --json '{\"repoRoot\":\"<repo-root>\",\"name\":\"<name>\"}'`\n\
         - Find call sites (no index needed): `varde map find_pattern --json '{\"repoRoot\":\"<repo-root>\",\"language\":\"<lang>\",\"pattern\":\"<name>($$$ARGS)\"}'`; methods use `$RECV.<name>($$$ARGS)`; qualified calls need the full path\n\
         - Expanded map (section caps still apply): `varde map nav_map --json '{\"repoRoot\":\"<repo-root>\",\"maxTokensEstimate\":18446744073709551615}'`\n\
         - Find relevant files and symbols: `varde map context_pack --json '{\"repoRoot\":\"<repo-root>\",\"query\":\"<term>\"}'`\n\
         - Explore file dependencies from a file or symbol: `varde map explore --json '{\"repoRoot\":\"<repo-root>\",\"query\":{\"params\":{\"input\":\"<file-or-symbol>\",\"direction\":\"outgoing\"}}}'`\n\
         - Inspect risk hotspots: `varde map hotspots --json '{\"repoRoot\":\"<repo-root>\"}'`\n",
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
    match crate::build::run_with_force(repo_root, force) {
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
                crate::query::output::render_with_input(Ok(result), &input)
            );
            0
        }
        Err(e) => {
            tracing::error!(repo_root = repo_root, "fatal error: {e:#}");
            println!(
                "{}",
                crate::query::output::render_with_input(
                    Err::<serde_json::Value, _>(crate::query::ApiError::new(
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

fn run_extract(path: &str) -> i32 {
    let input = extract_output_input(path);
    match crate::scan::run(path) {
        Ok(output) => {
            tracing::debug!(file = path, "emitting JSON document");
            // `files` is the public path table. Entries retain `file_id`, so
            // callers can navigate without repeating the same path per item.
            let doc = serde_json::to_value(&output).expect("output serializes");
            println!(
                "{}",
                crate::query::output::render_with_input(Ok(doc), &input)
            );
            0
        }
        Err(e) => {
            tracing::error!(file = path, "fatal error: {e:#}");
            println!(
                "{}",
                crate::query::output::render_with_input(
                    Err::<serde_json::Value, _>(crate::query::ApiError::new(
                        "extract_error",
                        e.to_string(),
                    )),
                    &input,
                )
            );
            1
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
        json_with_unbounded_token_budget, nav_map_data, nav_map_input_repo_root,
        render_nav_map_orientation, render_nav_map_text, render_nav_map_text_with_toz,
    };
    use crate::test_support::CaptureOverride;

    fn nav_map_fixture(label: &str) -> (std::path::PathBuf, String, String) {
        let repo = tempdir(label);
        // The source walker tracks every ordinary file, including a SQLite
        // fixture. Keep the test index inside excluded VCS internals.
        std::fs::create_dir_all(repo.join(".git")).expect("fixture metadata dir");
        let db_path = repo.join(".git/index.db");
        let conn = crate::db::open_or_rebuild(&db_path).expect("fixture db creates");
        conn.execute(
            "INSERT INTO slice_meta (key, value) VALUES ('build_version', ?1)",
            [crate::db::build_version_fingerprint()],
        )
        .expect("stamp build version");
        conn.execute(
            "INSERT INTO slice_meta (key, value) VALUES ('source_root', ?1)",
            [crate::db::path::repo_identity(&repo)],
        )
        .expect("stamp source root");
        for name in ["imports", "edges", "global"] {
            conn.execute("INSERT INTO slice_state (slice, built_through_rev, schema_version) VALUES (?1, 0, ?2)", rusqlite::params![name, crate::db::SCHEMA_VERSION]).expect("stamp empty derived slice");
        }
        drop(conn);
        let json = format!(
            r#"{{"repoRoot":"{}","dbPath":"{}"}}"#,
            repo.display(),
            db_path.display()
        );
        let envelope = crate::query::run_mode("nav_map", &json);
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
    /// and receives the unbudgeted render as its text.
    #[test]
    fn text_with_toz_appends_handle_and_feeds_it_the_unbudgeted_render() {
        let seen = std::sync::Arc::new(std::sync::Mutex::new(String::new()));
        let sink = std::sync::Arc::clone(&seen);
        let _override = CaptureOverride::with(move |input, _, _| {
            if let varde_contracts::CaptureInput::Text(text) = input {
                *sink.lock().unwrap() = text.to_string();
            }
            Some(
                "varde: captured 9 bytes → handle ab12 (1 lines, 1 chunk)  label: \"nav_map\"\n"
                    .to_string(),
            )
        });

        let (repo, json, envelope) = nav_map_fixture("toz-success");
        let unbudgeted_envelope = render_nav_map_text(&crate::query::run_mode(
            "nav_map",
            &json_with_unbounded_token_budget(&json),
        ));
        let budgeted_envelope = render_nav_map_text(&envelope);

        let result = render_nav_map_text_with_toz(&json, &envelope);

        assert!(result.starts_with(&render_nav_map_orientation(&envelope)));
        assert!(result.contains("Expanded map in Toz (handle ab12)"));
        assert!(result.contains("varde run query --handle ab12 \"<term>\""));
        assert!(!result.contains("varde: captured"));
        assert_ne!(result, budgeted_envelope);
        assert_eq!(*seen.lock().unwrap(), unbudgeted_envelope);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn text_with_toz_preserves_query_error_without_capturing() {
        let _override =
            CaptureOverride::with(|_, _, _| Some("toz: captured -> handle zz99\n".to_string()));
        let envelope = crate::query::run_mode("nav_map", "{}");

        let result = render_nav_map_text_with_toz("{}", &envelope);

        assert_eq!(result, envelope);
        assert!(result.contains("repoRoot"));
    }

    #[test]
    fn text_with_toz_preserves_first_render_when_unbudgeted_query_fails() {
        let _override =
            CaptureOverride::with(|_, _, _| Some("toz: captured -> handle zz99\n".to_string()));
        let budgeted = r#"{"ok":true,"data":{"entrypoints":[]}}"#;

        let result = render_nav_map_text_with_toz("{}", budgeted);

        assert_eq!(result, render_nav_map_orientation(budgeted));
    }

    #[test]
    fn orientation_routes_declarations_and_call_sites() {
        let (repo, _json, envelope) = nav_map_fixture("call-sites");
        let orientation = render_nav_map_orientation(&envelope);
        assert!(orientation.contains("varde map get_symbol"));
        assert!(orientation.contains("varde map find_pattern"));
        assert!(orientation.contains("$RECV.<name>($$$ARGS)"));
        let _ = std::fs::remove_dir_all(repo);
    }

    /// No capture installed at all: the compact orientation is returned.
    #[test]
    fn text_with_toz_falls_back_when_no_capture_is_installed() {
        let _override = CaptureOverride::none();
        let (repo, json, envelope) = nav_map_fixture("toz-missing");

        let orientation = render_nav_map_orientation(&envelope);
        let result = render_nav_map_text_with_toz(&json, &envelope);
        assert_eq!(result, orientation);
        assert!(result.contains("## Repository outline"));
        assert!(result.contains("varde map context_pack"));
        let _ = std::fs::remove_dir_all(repo);
    }

    /// `VARDE_CODE_TOZ=0` skips toz entirely, even with a capture installed
    /// that would otherwise succeed.
    #[test]
    fn text_with_toz_falls_back_when_disabled_by_env() {
        let _override =
            CaptureOverride::with(|_, _, _| Some("toz: captured -> handle zz99\n".to_string()));
        unsafe { std::env::set_var("VARDE_CODE_TOZ", "0") };
        let (repo, json, envelope) = nav_map_fixture("toz-disabled");

        let orientation = render_nav_map_orientation(&envelope);
        let result = render_nav_map_text_with_toz(&json, &envelope);
        assert_eq!(result, orientation);
        let _ = std::fs::remove_dir_all(repo);
    }

    /// A failed capture falls back to the compact orientation.
    #[test]
    fn text_with_toz_falls_back_when_capture_fails() {
        let _override = CaptureOverride::with(|_, _, _| None);
        let (repo, json, envelope) = nav_map_fixture("toz-nonzero");

        let orientation = render_nav_map_orientation(&envelope);
        let result = render_nav_map_text_with_toz(&json, &envelope);
        assert_eq!(result, orientation);
        let _ = std::fs::remove_dir_all(repo);
    }

    fn tempdir(label: &str) -> std::path::PathBuf {
        let dir =
            std::env::temp_dir().join(format!("varde-hooks-cli-{label}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("temp dir creates");
        dir
    }
}
