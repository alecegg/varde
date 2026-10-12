//! Stop existing code watchers before moving their store, then re-register
//! only repos that had a registered user service.

use super::{MigrateEnv, Report, ReportEntry};
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WatchInstance {
    pub repos: Vec<PathBuf>,
    pub registered: bool,
    pub alive: Option<bool>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StopOutcome {
    pub repos: Vec<PathBuf>,
    pub error: Option<String>,
}

/// Narrow seam for stopping and ensuring watchers without host services in tests.
pub trait WatchHost {
    fn instances(&mut self) -> Result<Vec<WatchInstance>, String>;
    fn stop_all(&mut self) -> Result<Vec<StopOutcome>, String>;
    fn lock_held(&mut self) -> Result<bool, String>;
    fn ensure(&mut self, repo: &Path) -> Result<bool, String>;
}

/// Operations backed by the code module's existing watcher implementation.
#[derive(Default)]
pub struct CodeWatchHost;

impl WatchHost for CodeWatchHost {
    fn instances(&mut self) -> Result<Vec<WatchInstance>, String> {
        varde_code::watch::list_instances()
            .map(|instances| {
                instances
                    .into_iter()
                    .map(|instance| WatchInstance {
                        repos: instance.repos.into_iter().map(PathBuf::from).collect(),
                        registered: instance.registered,
                        alive: instance.alive,
                    })
                    .collect()
            })
            .map_err(|error| format!("{error:#}"))
    }

    fn stop_all(&mut self) -> Result<Vec<StopOutcome>, String> {
        varde_code::watch::stop_all()
            .map(|outcomes| {
                outcomes
                    .into_iter()
                    .map(|outcome| StopOutcome {
                        repos: outcome.repos.into_iter().map(PathBuf::from).collect(),
                        error: outcome.error,
                    })
                    .collect()
            })
            .map_err(|error| format!("{error:#}"))
    }

    fn lock_held(&mut self) -> Result<bool, String> {
        let instances = self.instances()?;
        Ok(instances
            .iter()
            .any(|instance| instance.alive != Some(false)))
    }

    fn ensure(&mut self, repo: &Path) -> Result<bool, String> {
        varde_code::watch::ensure(repo)
            .map(|status| status.registered)
            .map_err(|error| format!("{error:#}"))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WatchMoveState {
    pub code_store_movable: bool,
    pub registered_repos: Vec<PathBuf>,
}

/// Stop all current instances before moving the code store and remember only
/// repos whose user services should be re-registered afterward.
pub fn stop_for_move(
    env: &MigrateEnv,
    host: &mut impl WatchHost,
    report: &mut Report,
) -> WatchMoveState {
    let mut safe = true;
    let instances = match host.instances() {
        Ok(instances) => Some(instances),
        Err(error) => {
            safe = false;
            report.unrewritable.push(ReportEntry::new(
                env.config_dir.join("code/watch-locks"),
                format!("could not list code watchers before the config move: {error}"),
            ));
            None
        }
    };
    let registered_repos = instances
        .as_deref()
        .map(registered_repos)
        .unwrap_or_default();
    let stoppable_instances = instances.as_deref().is_some_and(|items| {
        items
            .iter()
            .any(|item| item.registered || item.alive != Some(false))
    });

    if env.dry_run {
        if let Some(instances) = &instances {
            report_predicted_stops(env, instances, report);
        }
    } else {
        match host.stop_all() {
            Ok(outcomes) => {
                for outcome in outcomes {
                    if let Some(error) = outcome.error {
                        safe = false;
                        report_stop_error(env, report, &outcome.repos, error);
                    }
                }
            }
            Err(error) => {
                safe = false;
                report.unrewritable.push(ReportEntry::new(
                    env.config_dir.join("code/watch-locks"),
                    format!("could not stop all code watchers before the config move: {error}"),
                ));
            }
        }
    }

    match host.lock_held() {
        Ok(true) if !env.dry_run || !stoppable_instances => {
            safe = false;
            report.unrewritable.push(ReportEntry::new(
                env.config_dir.join("code"),
                if env.dry_run {
                    "watcher lock is held without a stoppable watcher; code store move is not predicted safe"
                } else {
                    "watcher lock remains held after stopping code watchers; code store move is unsafe"
                },
            ));
        }
        Ok(_) => {}
        Err(error) => {
            safe = false;
            report.unrewritable.push(ReportEntry::new(
                env.config_dir.join("code"),
                format!("could not verify the code watcher lock state: {error}"),
            ));
        }
    }

    WatchMoveState {
        code_store_movable: safe,
        registered_repos,
    }
}

/// Re-register the previously registered repos after the config move.
pub fn restart_after_move(
    env: &MigrateEnv,
    host: &mut impl WatchHost,
    repos: &[PathBuf],
    report: &mut Report,
) {
    for repo in repos {
        let command = format!("varde setup watch --ensure --repo {}", repo.display());
        if env.dry_run {
            report.would.push(
                ReportEntry::new(
                    repo,
                    "prediction: re-register this code watcher after the config move",
                )
                .with_command(command),
            );
            continue;
        }

        let result = match host.ensure(repo) {
            Ok(true) => continue,
            Ok(false) | Err(_) => host.ensure(repo),
        };
        let problem = match result {
            Ok(true) => continue,
            Ok(false) => "ensure completed but the repo remains unregistered".to_owned(),
            Err(error) => format!("ensure failed and the repo remains unregistered: {error}"),
        };
        report
            .unrewritable
            .push(ReportEntry::new(repo, problem).with_command(command));
    }
}

fn registered_repos(instances: &[WatchInstance]) -> Vec<PathBuf> {
    let mut repos = Vec::new();
    for instance in instances.iter().filter(|instance| instance.registered) {
        for repo in &instance.repos {
            if !repo.as_os_str().is_empty() && !repos.contains(repo) {
                repos.push(repo.clone());
            }
        }
    }
    repos
}

fn report_predicted_stops(env: &MigrateEnv, instances: &[WatchInstance], report: &mut Report) {
    for instance in instances
        .iter()
        .filter(|instance| instance.registered || instance.alive != Some(false))
    {
        if instance.repos.is_empty() {
            report.would.push(ReportEntry::new(
                env.config_dir.join("code/watch-locks"),
                "prediction: stop a code watcher with unknown repo coverage",
            ));
            continue;
        }
        for repo in &instance.repos {
            report.would.push(ReportEntry::new(
                repo,
                if instance.registered {
                    "prediction: stop and later re-register this code watcher"
                } else {
                    "prediction: stop this live unregistered code watcher"
                },
            ));
        }
    }
}

fn report_stop_error(env: &MigrateEnv, report: &mut Report, repos: &[PathBuf], error: String) {
    if repos.is_empty() {
        report.unrewritable.push(ReportEntry::new(
            env.config_dir.join("code/watch-locks"),
            format!("failed to stop a code watcher: {error}"),
        ));
        return;
    }
    for repo in repos {
        report.unrewritable.push(ReportEntry::new(
            repo,
            format!("failed to stop the code watcher before the config move: {error}"),
        ));
    }
}
