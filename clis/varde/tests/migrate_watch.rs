use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use tempfile::TempDir;
use varde::migrate::watch::{self, StopOutcome, WatchHost, WatchInstance, WatchMoveState};
use varde::migrate::{MigrateEnv, Report};

struct FakeWatch {
    instances: Vec<WatchInstance>,
    instances_error: Option<String>,
    stop_outcomes: Vec<StopOutcome>,
    stop_error: Option<String>,
    lock_held: bool,
    lock_error: Option<String>,
    ensure_results: HashMap<PathBuf, Result<bool, String>>,
    ensure_failures: HashMap<PathBuf, (usize, String)>,
    calls: Vec<String>,
}

impl FakeWatch {
    fn new(instances: Vec<WatchInstance>) -> Self {
        Self {
            instances,
            instances_error: None,
            stop_outcomes: Vec::new(),
            stop_error: None,
            lock_held: false,
            lock_error: None,
            ensure_results: HashMap::new(),
            ensure_failures: HashMap::new(),
            calls: Vec::new(),
        }
    }
}

impl WatchHost for FakeWatch {
    fn instances(&mut self) -> Result<Vec<WatchInstance>, String> {
        self.calls.push("instances".to_owned());
        match &self.instances_error {
            Some(error) => Err(error.clone()),
            None => Ok(self.instances.clone()),
        }
    }

    fn stop_all(&mut self) -> Result<Vec<StopOutcome>, String> {
        self.calls.push("stop_all".to_owned());
        match &self.stop_error {
            Some(error) => Err(error.clone()),
            None => Ok(self.stop_outcomes.clone()),
        }
    }

    fn lock_held(&mut self) -> Result<bool, String> {
        self.calls.push("lock_held".to_owned());
        match &self.lock_error {
            Some(error) => Err(error.clone()),
            None => Ok(self.lock_held),
        }
    }

    fn ensure(&mut self, repo: &Path) -> Result<bool, String> {
        self.calls.push(format!("ensure:{}", repo.display()));
        if let Some((remaining, error)) = self.ensure_failures.get_mut(repo)
            && *remaining > 0
        {
            *remaining -= 1;
            return Err(error.clone());
        }
        self.ensure_results.get(repo).cloned().unwrap_or(Ok(true))
    }
}

fn fixture() -> (TempDir, MigrateEnv) {
    let temp = tempfile::tempdir().expect("temporary root");
    let home = temp.path().join("home");
    let config_dir = temp.path().join("config/varde");
    fs::create_dir_all(&home).unwrap();
    fs::create_dir_all(&config_dir).unwrap();
    let env = MigrateEnv {
        home,
        config_dir,
        xdg_config_home: Some(temp.path().join("config")),
        path: std::env::var_os("PATH").unwrap_or_default(),
        cargo_install_root: temp.path().join("cargo"),
        exe: PathBuf::from(env!("CARGO_BIN_EXE_varde")),
        toz_config_override: None,
        dry_run: false,
    };
    (temp, env)
}

fn instance(repo: &Path, registered: bool, alive: Option<bool>) -> WatchInstance {
    WatchInstance {
        repos: vec![repo.to_path_buf()],
        registered,
        alive,
    }
}

fn outcome(repo: &Path, error: Option<&str>) -> StopOutcome {
    StopOutcome {
        repos: vec![repo.to_path_buf()],
        error: error.map(str::to_owned),
    }
}

fn stop(env: &MigrateEnv, host: &mut FakeWatch, report: &mut Report) -> WatchMoveState {
    watch::stop_for_move(env, host, report)
}

#[test]
fn stops_then_restarts_registered_repos_in_order() {
    let (temp, env) = fixture();
    let first = temp.path().join("repo-first");
    let second = temp.path().join("repo-second");
    let foreground = temp.path().join("repo-foreground");
    let mut host = FakeWatch::new(vec![
        instance(&first, true, Some(true)),
        instance(&second, true, Some(false)),
        instance(&foreground, false, Some(true)),
    ]);
    host.stop_outcomes = vec![
        outcome(&first, None),
        outcome(&second, None),
        outcome(&foreground, None),
    ];
    let mut report = Report::default();

    let state = stop(&env, &mut host, &mut report);
    assert!(state.code_store_movable);
    assert_eq!(state.registered_repos, [first.clone(), second.clone()]);
    watch::restart_after_move(&env, &mut host, &state.registered_repos, &mut report);

    assert_eq!(
        host.calls,
        [
            "instances".to_owned(),
            "stop_all".to_owned(),
            "lock_held".to_owned(),
            format!("ensure:{}", first.display()),
            format!("ensure:{}", second.display()),
        ]
    );
    assert_eq!(report.unrewritable.len(), 0);
}

#[test]
fn stops_live_unregistered_watchers_without_restarting_them() {
    let (temp, env) = fixture();
    let foreground = temp.path().join("repo-foreground");
    let mut host = FakeWatch::new(vec![instance(&foreground, false, Some(true))]);
    host.stop_outcomes = vec![outcome(&foreground, None)];
    let mut report = Report::default();

    let state = stop(&env, &mut host, &mut report);
    watch::restart_after_move(&env, &mut host, &state.registered_repos, &mut report);

    assert!(state.code_store_movable);
    assert!(state.registered_repos.is_empty());
    assert_eq!(host.calls, ["instances", "stop_all", "lock_held"]);
}

#[test]
fn stop_failure_prevents_moving_the_code_store() {
    let (temp, env) = fixture();
    let repo = temp.path().join("repo");
    let mut host = FakeWatch::new(vec![instance(&repo, true, Some(true))]);
    host.stop_outcomes = vec![outcome(&repo, Some("service stop failed"))];
    let mut report = Report::default();

    let state = stop(&env, &mut host, &mut report);

    assert!(!state.code_store_movable);
    assert!(
        report
            .unrewritable
            .iter()
            .any(|entry| { entry.path == repo && entry.reason.contains("service stop failed") })
    );
}

#[test]
fn held_lock_prevents_moving_the_code_store() {
    let (temp, env) = fixture();
    let repo = temp.path().join("repo");
    let mut host = FakeWatch::new(vec![instance(&repo, true, Some(true))]);
    host.stop_outcomes = vec![outcome(&repo, None)];
    host.lock_held = true;
    let mut report = Report::default();

    let state = stop(&env, &mut host, &mut report);

    assert!(!state.code_store_movable);
    assert!(report.unrewritable.iter().any(|entry| {
        entry.path == env.config_dir.join("code") && entry.reason.contains("lock remains held")
    }));
}

#[test]
fn failed_ensure_reports_unregistered_repo_and_recovery_command() {
    let (temp, env) = fixture();
    let repo = temp.path().join("repo");
    let mut host = FakeWatch::new(vec![instance(&repo, true, Some(true))]);
    host.stop_outcomes = vec![outcome(&repo, None)];
    host.ensure_failures
        .insert(repo.clone(), (2, "service could not start".to_owned()));
    let mut report = Report::default();

    let state = stop(&env, &mut host, &mut report);
    watch::restart_after_move(&env, &mut host, &state.registered_repos, &mut report);

    let failure = report
        .unrewritable
        .iter()
        .find(|entry| entry.path == repo)
        .expect("failed registration is reported against the repo");
    assert!(failure.reason.contains("unregistered"));
    assert_eq!(
        failure.command.as_deref(),
        Some(format!("varde setup watch --ensure --repo {}", repo.display()).as_str())
    );
    assert!(!failure.reason.contains("ExecStart"));
    assert_eq!(
        host.calls
            .iter()
            .filter(|call| *call == &format!("ensure:{}", repo.display()))
            .count(),
        2
    );
}

#[test]
fn transient_ensure_failure_retries_and_registers_repo() {
    let (temp, env) = fixture();
    let repo = temp.path().join("repo");
    let mut host = FakeWatch::new(vec![instance(&repo, true, Some(true))]);
    host.stop_outcomes = vec![outcome(&repo, None)];
    host.ensure_failures
        .insert(repo.clone(), (1, "temporary service error".to_owned()));
    let mut report = Report::default();

    let state = stop(&env, &mut host, &mut report);
    watch::restart_after_move(&env, &mut host, &state.registered_repos, &mut report);

    assert!(report.unrewritable.is_empty());
    assert_eq!(
        host.calls
            .iter()
            .filter(|call| *call == &format!("ensure:{}", repo.display()))
            .count(),
        2
    );
}

#[test]
fn dry_run_predicts_stops_and_restarts_without_mutation_or_host_actions() {
    let (temp, mut env) = fixture();
    let repo = temp.path().join("repo");
    let unit = temp.path().join("watch-unit/service");
    fs::create_dir_all(unit.parent().unwrap()).unwrap();
    fs::write(&unit, "legacy unit definition").unwrap();
    let before = fs::read(&unit).unwrap();
    env.dry_run = true;
    let mut host = FakeWatch::new(vec![instance(&repo, true, Some(true))]);
    host.lock_held = true;
    let mut report = Report::default();

    let state = stop(&env, &mut host, &mut report);
    watch::restart_after_move(&env, &mut host, &state.registered_repos, &mut report);

    assert!(
        state.code_store_movable,
        "dry-run predicts the watcher can stop"
    );
    assert_eq!(host.calls, ["instances", "lock_held"]);
    assert_eq!(fs::read(&unit).unwrap(), before);
    assert_eq!(report.would.len(), 2);
    assert!(
        report
            .would
            .iter()
            .all(|entry| entry.reason.contains("prediction"))
    );
}
