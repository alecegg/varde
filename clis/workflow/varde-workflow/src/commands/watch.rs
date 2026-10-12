//! Activity collection, classification, and event diffing for `plan watch`.
//!
//! A plan is watched when its status is neither terminal nor backlog. Its
//! newest activity comes from the plan directory, its `plan-now` line, and
//! the commits, uncommitted paths and build-output directories of every local
//! branch bound to it. Classification turns that activity into one state per
//! plan; [`diff`] compares it with the watcher's [`WatchCache`] and emits only
//! what changed. Everything takes an injected `now`, so tests backdate mtimes
//! and commits and never sleep.

use crate::commands::status::{self, StatusBucket};
use crate::commands::watch_cache::{CachedPlan, WatchCache};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

/// How often merge-ready and waiting re-emit, in multiples of the threshold.
const LONG_THRESHOLD: u64 = 3;

/// The state shown for one watched plan.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub(super) enum PlanState {
    Active,
    Blocked,
    NeedsDecision,
    MergeReady,
    Stale,
    Waiting,
    Finished,
}

/// Which source produced a plan's newest activity, for the event detail.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum Source {
    PlanFiles,
    NowLine,
    BuildOutput,
    DirtyFile,
    Commit,
}

impl Source {
    fn label(self) -> &'static str {
        match self {
            Source::PlanFiles => "plan files",
            Source::NowLine => "now line",
            Source::BuildOutput => "build output",
            Source::DirtyFile => "uncommitted change",
            Source::Commit => "commit",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Activity {
    at: SystemTime,
    source: Source,
}

/// Replace `best` when `candidate` is newer, or equal and later in the
/// iteration order (the order is chosen so the strongest source wins ties).
fn newer(best: Option<Activity>, at: SystemTime, source: Source) -> Option<Activity> {
    match best {
        Some(current) if current.at > at => Some(current),
        _ => Some(Activity { at, source }),
    }
}

/// One watched plan after classification.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct ClassifiedPlan {
    pub(super) id: String,
    pub(super) owner: Option<String>,
    pub(super) state: PlanState,
    pub(super) bucket: u64,
    pub(super) done: usize,
    pub(super) total: usize,
    pub(super) blocked_tasks: Vec<String>,
    pub(super) open_questions: usize,
    pub(super) now_line: Option<String>,
    pub(super) newest_activity: SystemTime,
    pub(super) source: Source,
    pub(super) idle_minutes: u64,
    pub(super) status: String,
    pub(super) idle_no_handback: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub(super) enum EventKind {
    Stale,
    Blocked,
    NeedsDecision,
    MergeReady,
    Finished,
}

impl EventKind {
    fn label(self) -> &'static str {
        match self {
            EventKind::Stale => "stale",
            EventKind::Blocked => "blocked",
            EventKind::NeedsDecision => "needs-decision",
            EventKind::MergeReady => "merge-ready",
            EventKind::Finished => "finished",
        }
    }
}

/// One `<kind> <plan-id> <detail>` line.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct Event {
    pub(super) kind: EventKind,
    pub(super) plan: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) owner: Option<String>,
    pub(super) detail: String,
}

impl Event {
    pub(super) fn line(&self) -> String {
        let label = if self.detail.starts_with("idle-no-handback;") {
            "idle-no-handback"
        } else {
            self.kind.label()
        };
        format!("{label} {} {}", self.plan, self.detail)
    }
}

struct TaskFacts {
    id: String,
    file_stem: String,
    status: String,
    depends_on: Vec<String>,
}

struct PlanFacts {
    id: String,
    owner: Option<String>,
    status: String,
    plan_path: PathBuf,
    plan_dir: PathBuf,
    branch: Option<String>,
    open_questions: usize,
    now_line: Option<String>,
    now_time: Option<SystemTime>,
    tasks: Vec<TaskFacts>,
}

/// Classify every watched plan in `working`, reading git state from `repo`.
pub(super) fn scan(
    working: &Path,
    repo: &Path,
    now: SystemTime,
    threshold_secs: u64,
) -> Vec<ClassifiedPlan> {
    let threshold = threshold_secs.max(1);
    let plans_dir = working.join("plans");
    let mut paths = Vec::new();
    let mut skipped = 0;
    if plans_dir.is_dir() {
        status::collect_plan_paths(&plans_dir, &mut paths, &mut skipped);
    }
    let facts = paths
        .iter()
        .filter_map(|path| read_facts(working, path))
        .collect::<Vec<_>>();
    let all_ids = facts
        .iter()
        .map(|fact| fact.id.clone())
        .collect::<BTreeSet<_>>();
    let branches = read_branches(repo);
    let worktrees = read_worktrees(repo);

    let mut plans = Vec::new();
    for fact in &facts {
        let task_ids = fact
            .tasks
            .iter()
            .map(|task| task.id.clone())
            .collect::<Vec<_>>();
        let bound = bind_branches(
            &fact.id,
            &task_ids,
            fact.branch.as_deref(),
            &all_ids,
            branches.keys().map(String::as_str),
        );
        let activity = collect_activity(working, fact, &bound, &branches, &worktrees);
        if let Some(mut plan) = classify(fact, &activity, now, threshold) {
            plan.idle_no_handback = status::status_bucket(&plan.status) != StatusBucket::Terminal
                && status::status_bucket(&plan.status) != StatusBucket::Backlog
                && now
                    .duration_since(activity.at)
                    .unwrap_or_default()
                    .as_secs()
                    >= threshold
                && !has_owner_message_after(working, &plan.id, activity.at);
            plans.push(plan);
        }
    }
    plans.sort_by(|left, right| left.id.cmp(&right.id));
    plans
}

/// Every event a plan would emit on its own, with no edge suppression.
pub(super) fn events_for(plans: &[ClassifiedPlan]) -> Vec<Event> {
    let mut events = Vec::new();
    for plan in plans {
        let idle_replaces_stale = plan.state == PlanState::Stale && plan.idle_no_handback;
        if idle_replaces_stale {
            events.push(idle_no_handback_event(plan));
        } else if let Some(event) = state_event(plan) {
            events.push(event);
        }
        if plan.state != PlanState::Blocked {
            for task in &plan.blocked_tasks {
                events.push(Event {
                    kind: EventKind::Blocked,
                    plan: plan.id.clone(),
                    owner: plan.owner.clone(),
                    detail: task.clone(),
                });
            }
        }
    }
    events
}

/// Emit events for the plans whose state, bucket, or blocked set changed, and
/// return the cache that records the current states. An absent cache entry
/// counts as changed, so a missing or corrupt cache emits the current states
/// once.
pub(super) fn diff(previous: &WatchCache, plans: &[ClassifiedPlan]) -> (Vec<Event>, WatchCache) {
    let mut events = Vec::new();
    let mut next = WatchCache::new();
    for plan in plans {
        let previous_plan = previous.plans.get(&plan.id);
        if plan.state != PlanState::Blocked {
            for task in &plan.blocked_tasks {
                let seen = previous_plan.is_some_and(|entry| entry.blocked.contains(task));
                if !seen {
                    events.push(Event {
                        kind: EventKind::Blocked,
                        plan: plan.id.clone(),
                        owner: plan.owner.clone(),
                        detail: task.clone(),
                    });
                }
            }
        }
        let changed = match previous_plan {
            None => true,
            Some(entry) => entry.state != plan.state || entry.bucket != plan.bucket,
        };
        let idle_replaces_stale = plan.state == PlanState::Stale && plan.idle_no_handback;
        if changed && !idle_replaces_stale && let Some(event) = state_event(plan) {
            events.push(event);
        }
        if idle_replaces_stale
            && !previous_plan.is_some_and(|entry| entry.idle_no_handback)
        {
            events.push(idle_no_handback_event(plan));
        }
        next.plans.insert(
            plan.id.clone(),
            CachedPlan {
                state: plan.state,
                bucket: plan.bucket,
                blocked: plan.blocked_tasks.iter().cloned().collect(),
                idle_no_handback: idle_replaces_stale,
            },
        );
    }
    (events, next)
}

fn idle_no_handback_event(plan: &ClassifiedPlan) -> Event {
    Event {
        kind: EventKind::Stale,
        plan: plan.id.clone(),
        owner: plan.owner.clone(),
        detail: format!(
            "idle-no-handback; {}m idle without owner hand-back",
            plan.idle_minutes
        ),
    }
}

/// Inbox inspection is deliberately read-only: watch never touches reader cursors.
fn has_owner_message_after(working: &Path, plan_id: &str, activity: SystemTime) -> bool {
    let path = working.join(".cache/inbox/messages.jsonl");
    let Ok(contents) = fs::read_to_string(path) else {
        return false;
    };
    let activity = timestamp_utc(activity);
    contents.lines().any(|line| {
        serde_json::from_str::<serde_json::Value>(line).is_ok_and(|message| {
            message.get("from").and_then(serde_json::Value::as_str) == Some(plan_id)
                && message
                    .get("ts")
                    .and_then(serde_json::Value::as_str)
                    .is_some_and(|timestamp| timestamp > activity.as_str())
        })
    })
}

fn timestamp_utc(at: SystemTime) -> String {
    let seconds = at.duration_since(UNIX_EPOCH).unwrap_or_default().as_secs() as i64;
    let days = seconds.div_euclid(86_400);
    let day_seconds = seconds.rem_euclid(86_400);
    let shifted = days + 719_468;
    let era = if shifted >= 0 {
        shifted
    } else {
        shifted - 146_096
    } / 146_097;
    let day_of_era = (shifted - era * 146_097) as u64;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era as i64 + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_prime = (5 * day_of_year + 2) / 153;
    let day = (day_of_year - (153 * month_prime + 2) / 5 + 1) as u32;
    let month = if month_prime < 10 {
        month_prime + 3
    } else {
        month_prime - 9
    } as u32;
    let year = if month <= 2 { year + 1 } else { year };
    let hour = day_seconds / 3_600;
    let minute = (day_seconds % 3_600) / 60;
    let second = day_seconds % 60;
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

fn state_event(plan: &ClassifiedPlan) -> Option<Event> {
    let (kind, detail) = match plan.state {
        PlanState::Active | PlanState::Waiting => return None,
        PlanState::Stale => {
            let mut detail = format!(
                "{}m idle; last activity: {}",
                plan.idle_minutes,
                plan.source.label()
            );
            if let Some(reason) = waiting_reason(plan.now_line.as_deref()) {
                detail.push_str(&format!("; waiting: {reason}"));
            }
            (EventKind::Stale, detail)
        }
        PlanState::Blocked => {
            let detail = if plan.status == "blocked" {
                "plan blocked".to_string()
            } else {
                "all tasks blocked".to_string()
            };
            (EventKind::Blocked, detail)
        }
        PlanState::NeedsDecision => (
            EventKind::NeedsDecision,
            format!("{} open question(s)", plan.open_questions),
        ),
        PlanState::MergeReady => (
            EventKind::MergeReady,
            format!("{}/{} tasks done", plan.done, plan.total),
        ),
        PlanState::Finished => (EventKind::Finished, plan.status.clone()),
    };
    Some(Event {
        kind,
        plan: plan.id.clone(),
        owner: plan.owner.clone(),
        detail,
    })
}

fn waiting_reason(now_line: Option<&str>) -> Option<&str> {
    now_line
        .and_then(|line| line.strip_prefix("waiting:"))
        .map(str::trim)
        .filter(|reason| !reason.is_empty())
}

fn read_facts(working: &Path, path: &Path) -> Option<PlanFacts> {
    let bytes = fs::read(path).ok()?;
    let (frontmatter, body) = varde_workflow_core::frontmatter::parse(&bytes).ok()?;
    let mapping = frontmatter.as_mapping()?;
    if status::artifact_type(mapping) != "plan" {
        return None;
    }
    let plan_dir = path.parent()?.to_path_buf();
    let id = status::artifact_id(path, mapping);
    let branch = status::string_field(mapping, "branch").filter(|value| !value.is_empty());
    let now_line = crate::commands::now::read_line(&working.join("plans"), path);
    let now_time = now_line_path(working, path)
        .and_then(|now_path| fs::metadata(now_path).ok()?.modified().ok());
    Some(PlanFacts {
        id,
        owner: status::string_field(mapping, "owner"),
        status: status::string_field(mapping, "status").unwrap_or_else(|| "backlog".to_string()),
        plan_path: path.to_path_buf(),
        plan_dir: plan_dir.clone(),
        branch,
        open_questions: status::count_open_questions(&body),
        now_line,
        now_time,
        tasks: read_tasks(&plan_dir),
    })
}

fn read_tasks(plan_dir: &Path) -> Vec<TaskFacts> {
    let tasks_dir = plan_dir.join("tasks");
    let Ok(entries) = fs::read_dir(&tasks_dir) else {
        return Vec::new();
    };
    let mut tasks = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|extension| extension.to_str()) != Some("md") {
            continue;
        }
        let Ok(bytes) = fs::read(&path) else {
            continue;
        };
        let Ok((frontmatter, _)) = varde_workflow_core::frontmatter::parse(&bytes) else {
            continue;
        };
        let Some(mapping) = frontmatter.as_mapping() else {
            continue;
        };
        if status::artifact_type(mapping) != "task" {
            continue;
        }
        tasks.push(TaskFacts {
            id: status::artifact_id(&path, mapping),
            file_stem: path
                .file_stem()
                .and_then(|stem| stem.to_str())
                .unwrap_or_default()
                .to_string(),
            status: status::string_field(mapping, "status").unwrap_or_else(|| "todo".to_string()),
            depends_on: status::string_list_field(mapping, "depends_on"),
        });
    }
    tasks.sort_by(|left, right| left.file_stem.cmp(&right.file_stem));
    tasks
}

fn classify(
    fact: &PlanFacts,
    activity: &Activity,
    now: SystemTime,
    threshold: u64,
) -> Option<ClassifiedPlan> {
    let bucket = status::status_bucket(&fact.status);
    if bucket == StatusBucket::Terminal {
        let plan_mtime = fs::metadata(&fact.plan_path).ok()?.modified().ok()?;
        let age = now.duration_since(plan_mtime).unwrap_or_default().as_secs();
        return (age <= threshold)
            .then(|| build(fact, activity, now, threshold, PlanState::Finished));
    }
    if bucket == StatusBucket::Backlog {
        return None;
    }

    let idle_secs = now
        .duration_since(activity.at)
        .unwrap_or_default()
        .as_secs();
    let done = fact
        .tasks
        .iter()
        .filter(|task| status::status_bucket(&task.status) == StatusBucket::Terminal)
        .count();
    let total = fact.tasks.len();
    let blocked_tasks = fact
        .tasks
        .iter()
        .filter(|task| task.status == "blocked")
        .map(|task| task.id.clone())
        .collect::<Vec<_>>();
    let waiting = waiting_reason(fact.now_line.as_deref());

    let state = if fact.status == "blocked" {
        PlanState::Blocked
    } else if fact.open_questions > 0 {
        PlanState::NeedsDecision
    } else if total > 0 && done == total {
        PlanState::MergeReady
    } else if !blocked_tasks.is_empty()
        && whole_plan_waiting_on_blocked(&fact.tasks)
        && idle_secs >= threshold
    {
        PlanState::Blocked
    } else if waiting.is_some() && waiting_is_live(fact, now, threshold) {
        PlanState::Waiting
    } else if idle_secs >= threshold {
        PlanState::Stale
    } else {
        PlanState::Active
    };
    Some(build(fact, activity, now, threshold, state))
}

fn waiting_is_live(fact: &PlanFacts, now: SystemTime, threshold: u64) -> bool {
    let Some(set_at) = fact.now_time else {
        return false;
    };
    let age = now.duration_since(set_at).unwrap_or_default().as_secs();
    age < LONG_THRESHOLD * threshold
}

/// Whether every open task is blocked: no task is in progress, and none is
/// ready (all dependencies terminal, or no known dependency).
fn whole_plan_waiting_on_blocked(tasks: &[TaskFacts]) -> bool {
    let in_progress = tasks.iter().any(|task| task.status == "in_progress");
    let ready = tasks.iter().any(|task| {
        if status::status_bucket(&task.status) == StatusBucket::Terminal
            || task.status == "in_progress"
            || task.status == "blocked"
        {
            return false;
        }
        task.depends_on.iter().all(|dependency| {
            tasks
                .iter()
                .filter(|candidate| {
                    candidate.file_stem == *dependency || candidate.id == *dependency
                })
                .all(|candidate| status::status_bucket(&candidate.status) == StatusBucket::Terminal)
        })
    });
    !in_progress && !ready
}

fn build(
    fact: &PlanFacts,
    activity: &Activity,
    now: SystemTime,
    threshold: u64,
    state: PlanState,
) -> ClassifiedPlan {
    let idle_secs = now
        .duration_since(activity.at)
        .unwrap_or_default()
        .as_secs();
    let bucket = match state {
        PlanState::Stale => idle_secs / threshold,
        PlanState::MergeReady => idle_secs / (LONG_THRESHOLD * threshold),
        _ => 0,
    };
    ClassifiedPlan {
        id: fact.id.clone(),
        owner: fact.owner.clone(),
        state,
        bucket,
        done: fact
            .tasks
            .iter()
            .filter(|task| status::status_bucket(&task.status) == StatusBucket::Terminal)
            .count(),
        total: fact.tasks.len(),
        blocked_tasks: fact
            .tasks
            .iter()
            .filter(|task| task.status == "blocked")
            .map(|task| task.id.clone())
            .collect(),
        open_questions: fact.open_questions,
        now_line: fact.now_line.clone(),
        newest_activity: activity.at,
        source: activity.source,
        idle_minutes: idle_secs / 60,
        status: fact.status.clone(),
        idle_no_handback: false,
    }
}

fn collect_activity(
    working: &Path,
    fact: &PlanFacts,
    bound: &[String],
    branches: &BTreeMap<String, SystemTime>,
    worktrees: &BTreeMap<String, PathBuf>,
) -> Activity {
    let mut best = dir_activity(&fact.plan_dir);
    if let Some(now_path) = now_line_path(working, &fact.plan_path)
        && let Ok(metadata) = fs::metadata(now_path)
        && let Ok(modified) = metadata.modified()
    {
        best = newer(best, modified, Source::NowLine);
    }
    for branch in bound {
        if let Some(at) = branches.get(branch) {
            best = newer(best, *at, Source::Commit);
        }
        if let Some(worktree) = worktrees.get(branch)
            && let Some(activity) = worktree_activity(worktree)
        {
            best = newer(best, activity.at, activity.source);
        }
    }
    best.unwrap_or(Activity {
        at: UNIX_EPOCH,
        source: Source::PlanFiles,
    })
}

/// The newest mtime under the plan directory: `plan.md`, tasks, notes, and
/// review files.
fn dir_activity(dir: &Path) -> Option<Activity> {
    let mut best = None;
    let mut stack = vec![dir.to_path_buf()];
    let mut visited = 0;
    while let Some(current) = stack.pop() {
        visited += 1;
        if visited > 10_000 {
            break;
        }
        let Ok(entries) = fs::read_dir(&current) else {
            continue;
        };
        for entry in entries.flatten() {
            let Ok(file_type) = entry.file_type() else {
                continue;
            };
            if file_type.is_dir() {
                stack.push(entry.path());
            } else if let Ok(metadata) = entry.metadata()
                && let Ok(modified) = metadata.modified()
            {
                best = newer(best, modified, Source::PlanFiles);
            }
        }
    }
    best
}

/// The newest mtime of the uncommitted paths and build-output directories in
/// one bound worktree.
fn worktree_activity(worktree: &Path) -> Option<Activity> {
    let mut best = None;
    if let Some((status, output)) =
        crate::execution_wave_tools::git(worktree, &["status", "--porcelain"])
        && status == 0
    {
        for line in output.lines() {
            let Some(relative) = dirty_path(line) else {
                continue;
            };
            if let Ok(metadata) = fs::metadata(worktree.join(relative))
                && let Ok(modified) = metadata.modified()
            {
                best = newer(best, modified, Source::DirtyFile);
            }
        }
    }
    for relative in [
        "clis/target/debug/deps",
        "clis/target/debug/.fingerprint",
        "clis/target/debug/build",
    ] {
        if let Ok(metadata) = fs::metadata(worktree.join(relative))
            && let Ok(modified) = metadata.modified()
        {
            best = newer(best, modified, Source::BuildOutput);
        }
    }
    best
}

fn dirty_path(line: &str) -> Option<PathBuf> {
    if line.len() < 4 {
        return None;
    }
    let rest = line.get(3..)?;
    // A rename shows `old -> new`; the new path is what changed last.
    let rest = rest.rsplit(" -> ").next().unwrap_or(rest).trim();
    if rest.is_empty() {
        return None;
    }
    let rest = rest
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
        .unwrap_or(rest);
    Some(PathBuf::from(rest))
}

fn read_branches(repo: &Path) -> BTreeMap<String, SystemTime> {
    let mut branches = BTreeMap::new();
    let Some((status, output)) = crate::execution_wave_tools::git(
        repo,
        &[
            "for-each-ref",
            "refs/heads",
            "--format=%(refname:short)\t%(committerdate:unix)",
        ],
    ) else {
        return branches;
    };
    if status != 0 {
        return branches;
    }
    for line in output.lines() {
        let Some((name, seconds)) = line.split_once('\t') else {
            continue;
        };
        let Ok(seconds) = seconds.trim().parse::<u64>() else {
            continue;
        };
        branches.insert(
            name.to_string(),
            UNIX_EPOCH + std::time::Duration::from_secs(seconds),
        );
    }
    branches
}

fn read_worktrees(repo: &Path) -> BTreeMap<String, PathBuf> {
    let mut worktrees = BTreeMap::new();
    let Some((status, output)) =
        crate::execution_wave_tools::git(repo, &["worktree", "list", "--porcelain"])
    else {
        return worktrees;
    };
    if status != 0 {
        return worktrees;
    }
    let mut path: Option<PathBuf> = None;
    let mut branch: Option<String> = None;
    for line in output.lines() {
        if let Some(rest) = line.strip_prefix("worktree ") {
            path = Some(PathBuf::from(rest));
            branch = None;
            continue;
        }
        if let Some(rest) = line.strip_prefix("branch refs/heads/") {
            branch = Some(rest.to_string());
            continue;
        }
        if line.is_empty()
            && let (Some(path), Some(branch)) = (path.take(), branch.take())
        {
            worktrees.insert(branch, path);
        }
    }
    if let (Some(path), Some(branch)) = (path, branch) {
        worktrees.insert(branch, path);
    }
    worktrees
}

/// Local branches bound to one plan: the exact `worktree/<plan-id>`, the exact
/// `worktree/<task-id>` for each task, the `branch:` frontmatter value when
/// present, and the `worktree/<plan-id>-` prefix. A branch that belongs to a
/// longer plan id (another id starting with `<plan-id>-`) is skipped, so plan
/// sets do not see each other's commits.
pub(super) fn bind_branches<'a>(
    plan_id: &str,
    task_ids: &[String],
    frontmatter_branch: Option<&str>,
    all_plan_ids: &BTreeSet<String>,
    branches: impl IntoIterator<Item = &'a str>,
) -> Vec<String> {
    let prefix = format!("worktree/{plan_id}-");
    let id_prefix = format!("{plan_id}-");
    let longer = all_plan_ids
        .iter()
        .filter(|id| id.as_str() != plan_id && id.starts_with(&id_prefix))
        .collect::<Vec<_>>();
    let belongs_to_longer = |name: &str| {
        longer.iter().any(|other| {
            name == format!("worktree/{other}") || name.starts_with(&format!("worktree/{other}-"))
        })
    };

    let mut exact = BTreeSet::new();
    exact.insert(format!("worktree/{plan_id}"));
    for task in task_ids {
        exact.insert(format!("worktree/{task}"));
    }
    if let Some(branch) = frontmatter_branch
        && !branch.is_empty()
    {
        exact.insert(branch.to_string());
    }

    let mut bound = BTreeSet::new();
    for name in branches {
        if belongs_to_longer(name) {
            continue;
        }
        if exact.contains(name) || name.starts_with(&prefix) {
            bound.insert(name.to_string());
        }
    }
    bound.into_iter().collect()
}

/// The `plan-now` file for a plan. The key encoding matches
/// `commands::now::plan_key`, so content and mtime stay in sync.
fn now_line_path(working: &Path, plan_path: &Path) -> Option<PathBuf> {
    let plans_dir = working.join("plans");
    let plans_root = fs::canonicalize(&plans_dir).ok()?;
    let directory = fs::canonicalize(plan_path.parent()?).ok()?;
    let relative = directory.strip_prefix(&plans_root).ok()?;
    let mut components = Vec::new();
    for component in relative.components() {
        let Component::Normal(component) = component else {
            return None;
        };
        let component = component.to_str()?;
        if component.is_empty() {
            return None;
        }
        components.push(component.replace('_', "_u"));
    }
    if components.is_empty() {
        return None;
    }
    Some(
        working
            .join("plan-now")
            .join(format!("{}.txt", components.join("__"))),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::watch_cache;
    use std::process::Command;
    use std::sync::Mutex;
    use std::time::Duration;

    /// Serializes tests that touch process environment variables.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn temp_dir(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "varde-watch-{label}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    fn set_modified(path: &Path, at: SystemTime) {
        fs::File::open(path).unwrap().set_modified(at).unwrap();
    }

    fn write_plan(working: &Path, directory: &str, frontmatter: &str) -> PathBuf {
        let plan = working.join("plans").join(directory).join("plan.md");
        fs::create_dir_all(plan.parent().unwrap()).unwrap();
        fs::write(
            &plan,
            format!("---\ntype: plan\n{frontmatter}\n---\n\nbody\n"),
        )
        .unwrap();
        plan
    }

    fn write_task(plan: &Path, stem: &str, frontmatter: &str) -> PathBuf {
        let task = plan
            .parent()
            .unwrap()
            .join("tasks")
            .join(format!("{stem}.md"));
        fs::create_dir_all(task.parent().unwrap()).unwrap();
        fs::write(&task, format!("---\ntype: task\n{frontmatter}\n---\n")).unwrap();
        task
    }

    fn write_owner_handback(working: &Path, plan_id: &str) {
        let inbox = working.join(".cache/inbox/messages.jsonl");
        fs::create_dir_all(inbox.parent().unwrap()).unwrap();
        let message = serde_json::json!({
            "ts": "9999-12-31T23:59:59Z",
            "from": plan_id,
            "to": "main",
            "kind": "info",
            "text": "handed back"
        });
        fs::write(inbox, format!("{message}\n")).unwrap();
    }

    fn set_tree_modified(plan: &Path, at: SystemTime) {
        let directory = plan.parent().unwrap();
        let mut stack = vec![directory.to_path_buf()];
        while let Some(current) = stack.pop() {
            for entry in fs::read_dir(&current).unwrap().flatten() {
                let path = entry.path();
                if entry.file_type().unwrap().is_dir() {
                    stack.push(path.clone());
                }
                set_modified(&path, at);
            }
        }
        set_modified(directory, at);
    }

    fn date_seconds(at: SystemTime) -> u64 {
        at.duration_since(UNIX_EPOCH).unwrap().as_secs()
    }

    fn git(repo: &Path, args: &[&str]) -> String {
        git_with_env(repo, args, &[])
    }

    fn git_with_env(repo: &Path, args: &[&str], envs: &[(&str, String)]) -> String {
        let mut command = Command::new("git");
        command.arg("-C").arg(repo).args(args);
        for (key, value) in envs {
            command.env(key, value);
        }
        let output = command.output().unwrap();
        assert!(
            output.status.success(),
            "git {args:?} failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout).unwrap()
    }

    fn git_repo(label: &str) -> PathBuf {
        let repo = temp_dir(label);
        git(&repo, &["init", "-q"]);
        git(&repo, &["config", "user.email", "watch@example.invalid"]);
        git(&repo, &["config", "user.name", "Watch Test"]);
        git(&repo, &["commit", "--allow-empty", "-qm", "init"]);
        repo
    }

    fn commit_at(repo: &Path, message: &str, at: SystemTime) {
        let stamp = format!("@{} +0000", date_seconds(at));
        git_with_env(
            repo,
            &["commit", "--allow-empty", "-qm", message],
            &[
                ("GIT_COMMITTER_DATE", stamp.clone()),
                ("GIT_AUTHOR_DATE", stamp),
            ],
        );
    }

    fn branch_commit(repo: &Path, branch: &str, message: &str, at: SystemTime) {
        git(repo, &["checkout", "-q", "-b", branch]);
        commit_at(repo, message, at);
        git(repo, &["checkout", "-q", "-"]);
    }

    fn base_now() -> SystemTime {
        UNIX_EPOCH + Duration::from_secs(2_000_000_000)
    }

    fn threshold() -> u64 {
        60
    }

    #[test]
    fn temp_config_and_home_resolve_inside_the_temp_root() {
        let _guard = ENV_LOCK.lock().unwrap();
        let root = temp_dir("config-home");
        let config = root.join("config");
        let home = root.join("home");
        let repo = root.join("repo");
        fs::create_dir_all(&config).unwrap();
        fs::create_dir_all(&home).unwrap();
        fs::create_dir_all(&repo).unwrap();

        // SAFETY: the lock serializes environment mutation across tests.
        unsafe {
            std::env::set_var("VARDE_CONFIG_DIR", &config);
            std::env::set_var("HOME", &home);
            std::env::remove_var("VARDE_WORKING_DIR");
        }
        let paths = varde_workflow_core::memory::MemoryPaths::resolve(&repo).unwrap();
        assert!(paths.working.path.ends_with("memory-bank/working"));
        assert_eq!(paths.config, config.join("config.toml"));
        assert!(paths.config.starts_with(&config));

        unsafe {
            std::env::remove_var("VARDE_CONFIG_DIR");
            std::env::remove_var("HOME");
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn now_line_path_matches_the_now_module() {
        let root = temp_dir("now-path");
        let working = root.join("working");
        let plan = write_plan(&working, "2026-10-10-feature", "status: active");
        let path = now_line_path(&working, &plan).unwrap();
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, "waiting: review\n").unwrap();
        assert_eq!(
            crate::commands::now::read_line(&working.join("plans"), &plan).as_deref(),
            Some("waiting: review")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn stale_when_idle_past_the_threshold() {
        let root = temp_dir("stale");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-idle", "status: active");
        set_tree_modified(&plan, now - Duration::from_secs(4 * threshold()));

        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans.len(), 1);
        assert_eq!(plans[0].state, PlanState::Stale);
        assert_eq!(plans[0].bucket, 4);
        let events = events_for(&plans);
        assert_eq!(events.len(), 1);
        assert!(events[0].line().starts_with("idle-no-handback 2026-10-10-idle "));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn file_activity_resets_idle() {
        let root = temp_dir("file-activity");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-touch", "status: active");
        set_tree_modified(&plan, now - Duration::from_secs(4 * threshold()));
        let task = write_task(&plan, "impl", "status: todo");
        set_modified(&task, now - Duration::from_secs(5));

        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Active);
        assert!(events_for(&plans).is_empty());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn commit_activity_resets_idle() {
        let root = temp_dir("commit-activity");
        let working = root.join("working");
        let repo = git_repo("commit-activity-repo");
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-commit", "status: active");
        set_tree_modified(&plan, now - Duration::from_secs(4 * threshold()));
        branch_commit(
            &repo,
            "worktree/2026-10-10-commit",
            "work",
            now - Duration::from_secs(5),
        );

        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Active);
        assert_eq!(
            plans[0].newest_activity,
            now - Duration::from_secs(5),
            "commit time is the newest activity"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn per_task_blocked_still_goes_stale_while_other_tasks_run() {
        let root = temp_dir("task-blocked");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-blocked", "status: active");
        write_task(&plan, "a-blocked", "status: blocked");
        write_task(&plan, "b-running", "status: in_progress");
        set_tree_modified(&plan, now - Duration::from_secs(4 * threshold()));

        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Stale);
        assert_eq!(plans[0].blocked_tasks, vec!["a-blocked".to_string()]);
        let lines = events_for(&plans)
            .iter()
            .map(Event::line)
            .collect::<Vec<_>>();
        assert!(lines.contains(
            &"idle-no-handback 2026-10-10-blocked idle-no-handback; 4m idle without owner hand-back"
                .to_string()
        ));
        assert!(lines.contains(&"blocked 2026-10-10-blocked a-blocked".to_string()));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_plan_with_every_task_blocked_is_blocked() {
        let root = temp_dir("plan-all-blocked");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-waiting-tasks", "status: active");
        write_task(&plan, "a-blocked", "status: blocked");
        write_task(&plan, "b-todo", "status: todo\ndepends_on: [a-blocked]");
        set_tree_modified(&plan, now - Duration::from_secs(4 * threshold()));

        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Blocked);
        assert!(
            events_for(&plans)
                .iter()
                .any(|event| event.line() == "blocked 2026-10-10-waiting-tasks all tasks blocked")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_blocked_plan_status_suppresses_stale() {
        let root = temp_dir("plan-blocked");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-blocked-status", "status: blocked");
        set_tree_modified(&plan, now - Duration::from_secs(4 * threshold()));

        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Blocked);
        assert!(
            events_for(&plans)
                .iter()
                .any(|event| event.line() == "blocked 2026-10-10-blocked-status plan blocked")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn open_questions_need_a_decision() {
        let root = temp_dir("needs-decision");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-questions", "status: active");
        fs::write(
            &plan,
            "---\ntype: plan\nstatus: active\n---\n\n## Open Questions\n\n- which path?\n- how soon?\n",
        )
        .unwrap();
        set_tree_modified(&plan, now - Duration::from_secs(4 * threshold()));

        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::NeedsDecision);
        assert_eq!(plans[0].open_questions, 2);
        assert!(
            events_for(&plans)
                .iter()
                .any(|event| event.line()
                    == "needs-decision 2026-10-10-questions 2 open question(s)")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn merge_ready_needs_at_least_one_task_and_re_emits_at_three_times() {
        let root = temp_dir("merge-ready");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();

        let empty = write_plan(&working, "2026-10-10-empty", "status: active");
        set_tree_modified(&empty, now - Duration::from_secs(4 * threshold()));
        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(
            plans[0].state,
            PlanState::Stale,
            "0 tasks is never merge-ready"
        );

        let ready = write_plan(&working, "2026-10-10-ready", "status: active");
        write_task(&ready, "impl", "status: done");
        set_tree_modified(&ready, now - Duration::from_secs(4 * threshold()));
        let plans = scan(&working, &repo, now, threshold());
        let plan = plans
            .iter()
            .find(|plan| plan.id == "2026-10-10-ready")
            .unwrap();
        assert_eq!(plan.state, PlanState::MergeReady);
        assert!(
            events_for(&plans)
                .iter()
                .any(|event| event.line() == "merge-ready 2026-10-10-ready 1/1 tasks done")
        );

        let first = diff(&WatchCache::new(), &plans);
        assert!(
            first
                .0
                .iter()
                .any(|event| event.kind == EventKind::MergeReady)
        );
        let (repeat, _) = diff(&first.1, &plans);
        assert!(
            repeat
                .iter()
                .all(|event| event.kind != EventKind::MergeReady),
            "an unchanged merge-ready plan stays quiet"
        );

        // Past 3x the threshold the bucket advances and the event repeats.
        let later = now + Duration::from_secs(3 * threshold());
        let plans = scan(&working, &repo, later, threshold());
        assert_eq!(
            plans
                .iter()
                .find(|plan| plan.id == "2026-10-10-ready")
                .unwrap()
                .state,
            PlanState::MergeReady
        );
        let (again, _) = diff(&first.1, &plans);
        assert!(
            again
                .iter()
                .any(|event| event.kind == EventKind::MergeReady)
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn waiting_suppresses_stale_until_three_times_the_threshold() {
        let root = temp_dir("waiting");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-waiting", "status: active");
        write_owner_handback(&working, "2026-10-10-waiting");
        set_tree_modified(&plan, now - Duration::from_secs(10 * threshold()));
        let now_path = now_line_path(&working, &plan).unwrap();
        fs::create_dir_all(now_path.parent().unwrap()).unwrap();
        fs::write(&now_path, "waiting: on the user\n").unwrap();

        set_modified(&now_path, now - Duration::from_secs(2 * threshold()));
        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Waiting);
        assert!(events_for(&plans).is_empty());

        set_modified(&now_path, now - Duration::from_secs(4 * threshold()));
        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Stale);
        let events = events_for(&plans);
        assert!(events[0].line().contains("; waiting: on the user"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn waiting_is_ignored_for_a_finished_plan() {
        let root = temp_dir("waiting-finished");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-done", "status: completed");
        set_tree_modified(&plan, now - Duration::from_secs(30));
        let now_path = now_line_path(&working, &plan).unwrap();
        fs::create_dir_all(now_path.parent().unwrap()).unwrap();
        fs::write(&now_path, "waiting: stale line\n").unwrap();
        set_modified(&now_path, now - Duration::from_secs(4 * threshold()));

        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Finished);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn backlog_is_excluded_and_finished_comes_from_files() {
        let root = temp_dir("finished");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        write_plan(&working, "2026-10-10-backlog", "status: backlog");
        let done = write_plan(&working, "2026-10-10-done", "status: completed");
        set_tree_modified(&done, now - Duration::from_secs(30));
        let old = write_plan(&working, "2026-10-10-old-done", "status: cancelled");
        set_tree_modified(&old, now - Duration::from_secs(4 * threshold()));

        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans.len(), 1);
        assert_eq!(plans[0].id, "2026-10-10-done");
        assert_eq!(plans[0].state, PlanState::Finished);
        assert!(
            events_for(&plans)
                .iter()
                .any(|event| event.line() == "finished 2026-10-10-done completed")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn stale_re_emits_only_when_the_bucket_advances() {
        let root = temp_dir("stale-bucket");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-bucket", "status: active");
        write_owner_handback(&working, "2026-10-10-bucket");
        set_tree_modified(&plan, now - Duration::from_secs(2 * threshold()));

        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].bucket, 2);
        let (events, cache) = diff(&WatchCache::new(), &plans);
        assert_eq!(events.len(), 1);

        let (quiet, _) = diff(&cache, &plans);
        assert!(quiet.is_empty());

        let later = now + Duration::from_secs(threshold());
        let plans = scan(&working, &repo, later, threshold());
        assert_eq!(plans[0].bucket, 3);
        let (repeated, _) = diff(&cache, &plans);
        assert_eq!(repeated.len(), 1);
        assert_eq!(repeated[0].kind, EventKind::Stale);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_restart_with_unchanged_state_emits_nothing() {
        let root = temp_dir("restart");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-restart", "status: active");
        set_tree_modified(&plan, now - Duration::from_secs(2 * threshold()));

        let plans = scan(&working, &repo, now, threshold());
        let (events, cache) = diff(&WatchCache::new(), &plans);
        assert_eq!(events.len(), 1);
        assert!(watch_cache::write_if_changed(&working, None, &cache).unwrap());

        // Restart: the cache survives, so nothing repeats.
        let restored = watch_cache::read(&working, None).unwrap();
        assert_eq!(restored, cache);
        let (quiet, _) = diff(&restored, &plans);
        assert!(quiet.is_empty());
        assert!(!watch_cache::write_if_changed(&working, None, &cache).unwrap());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_change_during_downtime_emits_once() {
        let root = temp_dir("downtime");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-down", "status: active");
        set_tree_modified(&plan, now - Duration::from_secs(2 * threshold()));
        let plans = scan(&working, &repo, now, threshold());
        let (_, cache) = diff(&WatchCache::new(), &plans);

        // The plan finishes while no watcher runs.
        fs::write(&plan, "---\ntype: plan\nstatus: completed\n---\n\nbody\n").unwrap();
        set_modified(&plan, now - Duration::from_secs(10));
        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Finished);
        let (events, next) = diff(&cache, &plans);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].kind, EventKind::Finished);
        let (again, _) = diff(&next, &plans);
        assert!(again.is_empty());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_corrupt_cache_emits_current_states_once() {
        let root = temp_dir("corrupt");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-corrupt", "status: active");
        set_tree_modified(&plan, now - Duration::from_secs(2 * threshold()));
        let cache_path = watch_cache::cache_path(&working, None);
        fs::create_dir_all(cache_path.parent().unwrap()).unwrap();
        fs::write(&cache_path, b"{ not json").unwrap();

        let previous = watch_cache::read(&working, None).unwrap_or_else(WatchCache::new);
        let plans = scan(&working, &repo, now, threshold());
        let (events, cache) = diff(&previous, &plans);
        assert_eq!(events.len(), 1);
        assert!(watch_cache::write_if_changed(&working, None, &cache).unwrap());
        assert!(watch_cache::read(&working, None).is_some());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn two_watchers_with_different_notes_paths_each_emit_once() {
        let root = temp_dir("two-watchers");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-two", "status: active");
        set_tree_modified(&plan, now - Duration::from_secs(2 * threshold()));
        let first = working.join("notes-a.md");
        let second = working.join("notes-b.md");

        let plans = scan(&working, &repo, now, threshold());
        for notes in [&first, &second] {
            let previous = watch_cache::read(&working, Some(notes)).unwrap_or_else(WatchCache::new);
            let (events, cache) = diff(&previous, &plans);
            assert_eq!(events.len(), 1, "each watcher emits the transition once");
            assert!(watch_cache::write_if_changed(&working, Some(notes), &cache).unwrap());
        }
        // A second tick on either watcher stays quiet.
        for notes in [&first, &second] {
            let previous = watch_cache::read(&working, Some(notes)).unwrap();
            let (events, _) = diff(&previous, &plans);
            assert!(events.is_empty());
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn once_mode_does_not_touch_the_cache() {
        let root = temp_dir("once");
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-once", "status: active");
        set_tree_modified(&plan, now - Duration::from_secs(2 * threshold()));
        let cache_path = watch_cache::cache_path(&working, None);
        fs::create_dir_all(cache_path.parent().unwrap()).unwrap();
        fs::write(&cache_path, b"keep me").unwrap();

        let plans = scan(&working, &repo, now, threshold());
        let events = events_for(&plans);
        assert_eq!(events.len(), 1);
        assert_eq!(fs::read(&cache_path).unwrap(), b"keep me");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn uncommitted_and_build_activity_keep_a_worktree_plan_active() {
        let root = temp_dir("worktree-activity");
        let working = root.join("working");
        let repo = git_repo("worktree-activity-repo");
        fs::write(repo.join(".gitignore"), "clis/target/\n").unwrap();
        git(&repo, &["add", ".gitignore"]);
        git(&repo, &["commit", "-qm", "ignore target"]);
        let now = base_now();
        let plan = write_plan(&working, "2026-10-10-worktree", "status: active");
        set_tree_modified(&plan, now - Duration::from_secs(4 * threshold()));
        let worktree = root.join("worktree");
        git(
            &repo,
            &[
                "worktree",
                "add",
                "-q",
                "-b",
                "worktree/2026-10-10-worktree",
                worktree.to_str().unwrap(),
                "HEAD",
            ],
        );

        // A clean worktree leaves the plan stale.
        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Stale);

        // An uncommitted edit counts as activity.
        let edited = worktree.join("edit.rs");
        fs::write(&edited, "v1\n").unwrap();
        set_modified(&edited, now - Duration::from_secs(5));
        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Active);
        assert_eq!(plans[0].newest_activity, now - Duration::from_secs(5));

        // Remove the edit; a fresh build-output directory counts as activity.
        fs::remove_file(&edited).unwrap();
        let deps = worktree.join("clis/target/debug/deps");
        fs::create_dir_all(&deps).unwrap();
        let artifact = deps.join("libthing.rlib");
        fs::write(&artifact, "x").unwrap();
        set_modified(&artifact, now - Duration::from_secs(5));
        set_modified(&deps, now - Duration::from_secs(5));
        let plans = scan(&working, &repo, now, threshold());
        assert_eq!(plans[0].state, PlanState::Active);
        assert_eq!(plans[0].newest_activity, now - Duration::from_secs(5));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn set_children_do_not_see_each_others_commits() {
        let root = temp_dir("branch-binding");
        let working = root.join("working");
        let repo = git_repo("branch-binding-repo");
        let now = base_now();
        let parent = write_plan(&working, "w4", "status: active");
        set_tree_modified(&parent, now - Duration::from_secs(4 * threshold()));
        let child = write_plan(&working, "w4-x", "status: active");
        set_tree_modified(&child, now - Duration::from_secs(4 * threshold()));

        branch_commit(
            &repo,
            "worktree/w4",
            "parent work",
            now - Duration::from_secs(4 * threshold()),
        );
        branch_commit(
            &repo,
            "worktree/w4-x",
            "child work",
            now - Duration::from_secs(5),
        );

        let all_ids = BTreeSet::from(["w4".to_string(), "w4-x".to_string()]);
        let branches = BTreeSet::from(["worktree/w4".to_string(), "worktree/w4-x".to_string()]);
        let bound = bind_branches(
            "w4",
            &[],
            None,
            &all_ids,
            branches.iter().map(String::as_str),
        );
        assert_eq!(bound, vec!["worktree/w4".to_string()]);

        let plans = scan(&working, &repo, now, threshold());
        let parent_plan = plans.iter().find(|plan| plan.id == "w4").unwrap();
        assert_eq!(
            parent_plan.newest_activity,
            now - Duration::from_secs(4 * threshold())
        );
        let child_plan = plans.iter().find(|plan| plan.id == "w4-x").unwrap();
        assert_eq!(child_plan.newest_activity, now - Duration::from_secs(5));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn branch_binding_uses_frontmatter_exact_task_and_prefix_names() {
        let all_ids = BTreeSet::from(["plan".to_string(), "plan-extra".to_string()]);
        let branches = BTreeSet::from([
            "worktree/plan".to_string(),
            "worktree/plan-extra".to_string(),
            "worktree/plan-integration".to_string(),
            "worktree/plan-extra-task".to_string(),
            "worktree/task-a".to_string(),
            "worktree/unrelated".to_string(),
            "worktree/recorded".to_string(),
        ]);
        let bound = bind_branches(
            "plan",
            &["task-a".to_string()],
            Some("worktree/recorded"),
            &all_ids,
            branches.iter().map(String::as_str),
        );
        assert_eq!(
            bound,
            vec![
                "worktree/plan".to_string(),
                "worktree/plan-integration".to_string(),
                "worktree/recorded".to_string(),
                "worktree/task-a".to_string(),
            ]
        );
    }
}
