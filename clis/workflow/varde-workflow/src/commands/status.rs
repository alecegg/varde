//! Read-only progress rollup for configured working plans.

use crate::cli::StatusArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::print_success;
use anyhow::{Context, Result};
use serde::Serialize;
use serde_yaml::{Mapping, Value as YamlValue};
use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};
use std::ffi::OsStr;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};
use varde_workflow_core::memory::MemoryPaths;

const DISPLAY_LIMIT: usize = 5;

#[derive(Debug, Serialize)]
struct ProgressReport {
    plans: Vec<PlanProgress>,
    more_count: usize,
    backlog_count: usize,
    skipped: usize,
}

#[derive(Debug, Serialize)]
struct PlanProgress {
    id: String,
    title: String,
    status: String,
    merge: &'static str,
    done: usize,
    total: usize,
    unit: &'static str,
    now: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    owner: Option<String>,
    group: bool,
    children: Vec<PlanProgress>,
    more_count: usize,
}

struct PlanRecord {
    id: String,
    status: String,
    title: String,
    owner: Option<String>,
    group: bool,
    open_questions: usize,
    task_done: usize,
    task_total: usize,
    task_in_progress: bool,
    task_now: Option<String>,
    task_stalled: Option<u64>,
    depends_on: Vec<String>,
    now_line: Option<String>,
    terminal: bool,
    merge: &'static str,
}

struct TaskRecord {
    path: PathBuf,
    file_stem: String,
    id: String,
    status: String,
    title: String,
    depends_on: Vec<String>,
}

impl PlanRecord {
    fn now(&self, group: bool, waiting_on: Option<&str>) -> String {
        if self.task_total == 0 {
            if let Some(sibling) = waiting_on {
                return format!("waits on {sibling}");
            }
            if !group && (is_draft_id(&self.id) || self.open_questions > 0) {
                return self.draft_status();
            }
        }
        if self.status == "blocked" {
            return "blocked".to_string();
        }
        if let Some(task) = &self.task_now {
            return match self.task_stalled {
                Some(minutes) => format!("{task} stalled {minutes}m"),
                None => task.clone(),
            };
        }
        if !group && self.task_total > 0 && self.task_done == self.task_total {
            return "tasks complete".to_string();
        }
        if !group && self.task_total == 0 {
            return "no tasks yet".to_string();
        }
        self.status.clone()
    }

    fn draft_status(&self) -> String {
        let noun = if self.open_questions == 1 {
            "question"
        } else {
            "questions"
        };
        format!("draft, {} open {noun}", self.open_questions)
    }
}

fn is_draft_id(id: &str) -> bool {
    id.ends_with("-draft")
        || id.rsplit_once("-draft-").is_some_and(|(_, suffix)| {
            !suffix.is_empty() && suffix.bytes().all(|byte| byte.is_ascii_digit())
        })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum StatusBucket {
    Terminal,
    Backlog,
    Other,
}

/// The configured stall threshold in minutes, with a notice when the config
/// could not be read. Shared by `plan status` and `plan watch`.
pub(super) fn load_stall_minutes() -> (u64, Option<String>) {
    match varde_workflow_core::memory::load_config() {
        Ok(config) => config.orchestration.stall_minutes(),
        Err(error) => (
            varde_workflow_core::memory::DEFAULT_STALL_MINUTES,
            Some(format!("could not load config ({error})")),
        ),
    }
}

pub fn run(args: StatusArgs) -> Result<()> {
    let (stall_minutes, notice) = load_stall_minutes();
    if let Some(reason) = notice {
        eprintln!(
            "varde plan status: orchestration stall_minutes ignored ({reason}); using {stall_minutes}"
        );
    }
    let (report, working) = match collect_at(SystemTime::now(), stall_minutes) {
        Ok(result) => result,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    for notice in staleness_notices(&working, args.repo.as_deref()) {
        eprintln!("{notice}");
    }
    if args.json {
        print_success(serde_json::to_value(report)?)
    } else {
        let last_output = working.join(".cache/plan-status-last.txt");
        print!(
            "{}",
            render_with_cache(&report, OsStr::new("date"), &last_output)?
        );
        Ok(())
    }
}

fn collect_at(now: SystemTime, stall_minutes: u64) -> Result<(ProgressReport, PathBuf)> {
    let current_dir = std::env::current_dir().context("could not resolve current directory")?;
    let working = MemoryPaths::resolve(&current_dir)?.working.path;
    Ok((collect_from(&working, now, stall_minutes), working))
}

fn collect_from(working: &Path, now: SystemTime, stall_minutes: u64) -> ProgressReport {
    let plans_dir = working.join("plans");
    let mut paths = Vec::new();
    let mut skipped = 0;
    if plans_dir.is_dir() {
        collect_plan_paths(&plans_dir, &mut paths, &mut skipped);
    }
    paths.sort_by(|left, right| compare_plan_paths(left, right));

    let mut records = BTreeMap::new();
    for path in &paths {
        match read_plan(path, now, stall_minutes) {
            Some((mut record, task_skipped)) => {
                skipped += task_skipped;
                record.now_line = crate::commands::now::read_line(&plans_dir, path);
                records.insert(path.clone(), record);
            }
            None => skipped += 1,
        }
    }
    let plan_paths = records.keys().cloned().collect::<BTreeSet<_>>();
    let mut children = BTreeMap::<PathBuf, Vec<PathBuf>>::new();
    let mut roots = Vec::new();
    for path in records.keys() {
        if let Some(parent) = parent_plan(path, &plans_dir, &plan_paths) {
            children.entry(parent).or_default().push(path.clone());
        } else {
            roots.push(path.clone());
        }
    }
    roots.retain(|path| !records[path].terminal);
    roots.sort_by(|left, right| compare_plan_paths(left, right));
    let root_siblings = roots.clone();

    let backlog_count = roots
        .iter()
        .filter(|path| is_collapsible_backlog(path, &records, &children))
        .count();
    let mut visible_roots = roots
        .into_iter()
        .filter(|path| !is_collapsible_backlog(path, &records, &children))
        .collect::<Vec<_>>();
    // Descendant tasks count as activity when ranking a top-level group.
    visible_roots.sort_by(|left, right| {
        root_priority(left, &records, &children)
            .cmp(&root_priority(right, &records, &children))
            .then_with(|| compare_plan_paths(left, right))
    });

    let more_count = visible_roots.len().saturating_sub(DISPLAY_LIMIT);
    let plans = visible_roots
        .iter()
        .take(DISPLAY_LIMIT)
        .map(|path| build_progress(path, &records, &children, &root_siblings))
        .collect();
    ProgressReport {
        plans,
        more_count,
        backlog_count,
        skipped,
    }
}

fn root_priority(
    path: &Path,
    records: &BTreeMap<PathBuf, PlanRecord>,
    children: &BTreeMap<PathBuf, Vec<PathBuf>>,
) -> u8 {
    if has_in_progress(path, records, children) {
        0
    } else if has_tasks_or_activity(path, records, children) {
        1
    } else {
        2
    }
}

fn has_in_progress(
    path: &Path,
    records: &BTreeMap<PathBuf, PlanRecord>,
    children: &BTreeMap<PathBuf, Vec<PathBuf>>,
) -> bool {
    records[path].task_in_progress
        || children
            .get(path)
            .into_iter()
            .flatten()
            .any(|child| has_in_progress(child, records, children))
}

fn has_tasks_or_activity(
    path: &Path,
    records: &BTreeMap<PathBuf, PlanRecord>,
    children: &BTreeMap<PathBuf, Vec<PathBuf>>,
) -> bool {
    records[path].task_total > 0
        || children
            .get(path)
            .into_iter()
            .flatten()
            .any(|child| has_tasks_or_activity(child, records, children))
}

fn is_collapsible_backlog(
    path: &Path,
    records: &BTreeMap<PathBuf, PlanRecord>,
    children: &BTreeMap<PathBuf, Vec<PathBuf>>,
) -> bool {
    let record = &records[path];
    record.status == "backlog"
        && !has_tasks_or_activity(path, records, children)
        && !is_draft_id(&record.id)
        && record.open_questions == 0
}

pub(super) fn collect_plan_paths(directory: &Path, paths: &mut Vec<PathBuf>, skipped: &mut usize) {
    let Ok(entries) = fs::read_dir(directory) else {
        *skipped += 1;
        return;
    };
    let mut entries = entries
        .filter_map(|entry| match entry {
            Ok(entry) => Some(entry),
            Err(_) => {
                *skipped += 1;
                None
            }
        })
        .collect::<Vec<_>>();
    entries.sort_by_key(std::fs::DirEntry::file_name);
    for entry in entries {
        let path = entry.path();
        let file_type = match entry.file_type() {
            Ok(file_type) => file_type,
            Err(_) => {
                *skipped += 1;
                continue;
            }
        };
        if file_type.is_dir() && entry.file_name() != "archive" {
            collect_plan_paths(&path, paths, skipped);
        } else if (file_type.is_file() || file_type.is_symlink()) && entry.file_name() == "plan.md"
        {
            paths.push(path);
        } else if (file_type.is_file() || file_type.is_symlink())
            && entry.file_name() == "task.md"
            && !path
                .parent()
                .is_some_and(|directory| directory.join("plan.md").exists())
        {
            // A single-change directory lists as one line: `task.md` with no
            // sibling `plan.md`.
            paths.push(path);
        }
    }
}

fn read_plan(path: &Path, now: SystemTime, stall_minutes: u64) -> Option<(PlanRecord, usize)> {
    let bytes = fs::read(path).ok()?;
    let (frontmatter, body) = varde_workflow_core::frontmatter::parse(&bytes).ok()?;
    let mapping = frontmatter.as_mapping()?;
    let artifact_type = artifact_type(mapping);
    if path.file_name().and_then(OsStr::to_str) == Some("task.md") && artifact_type == "task" {
        return Some(single_change_record(path, mapping));
    }
    if artifact_type != "plan" {
        return None;
    }
    let id = artifact_id(path, mapping);
    let status = string_field(mapping, "status").unwrap_or_else(|| "backlog".to_string());
    let merge = merge_state(path, &status);
    let title = string_field(mapping, "title").unwrap_or_else(|| id.clone());
    let owner = string_field(mapping, "owner");
    let group = string_field(mapping, "shape").as_deref() == Some("group");
    let open_questions = count_open_questions(&body);
    let depends_on = string_list_field(mapping, "depends_on");
    let (task_done, task_total, task_in_progress, task_now, task_stalled, skipped) =
        read_tasks(path, now, stall_minutes);
    let terminal = status_bucket(&status) == StatusBucket::Terminal;
    Some((
        PlanRecord {
            id,
            status,
            title,
            owner,
            group,
            open_questions,
            task_done,
            task_total,
            task_in_progress,
            task_now,
            task_stalled,
            depends_on,
            now_line: None,
            terminal,
            merge,
        },
        skipped,
    ))
}

fn read_tasks(
    path: &Path,
    now: SystemTime,
    stall_minutes: u64,
) -> (usize, usize, bool, Option<String>, Option<u64>, usize) {
    let Some(plan_dir) = path.parent() else {
        return (0, 0, false, None, None, 0);
    };
    let tasks_dir = plan_dir.join("tasks");
    if !tasks_dir.is_dir() {
        return (0, 0, false, None, None, 0);
    }
    let Ok(entries) = fs::read_dir(&tasks_dir) else {
        return (0, 0, false, None, None, 1);
    };
    let mut tasks = Vec::new();
    let mut skipped = 0;
    for entry in entries {
        let Ok(entry) = entry else {
            skipped += 1;
            continue;
        };
        let Ok(file_type) = entry.file_type() else {
            skipped += 1;
            continue;
        };
        if (file_type.is_file() || file_type.is_symlink())
            && entry
                .path()
                .extension()
                .is_some_and(|extension| extension == "md")
        {
            tasks.push(entry);
        }
    }
    tasks.sort_by_key(std::fs::DirEntry::file_name);

    let mut records = Vec::new();
    for entry in tasks {
        let task_path = entry.path();
        let Ok(bytes) = fs::read(&task_path) else {
            skipped += 1;
            continue;
        };
        let Ok((frontmatter, _)) = varde_workflow_core::frontmatter::parse(&bytes) else {
            skipped += 1;
            continue;
        };
        let Some(mapping) = frontmatter.as_mapping() else {
            skipped += 1;
            continue;
        };
        if artifact_type(mapping) != "task" {
            skipped += 1;
            continue;
        }
        let id = artifact_id(&task_path, mapping);
        let status = string_field(mapping, "status").unwrap_or_else(|| "todo".to_string());
        let title = string_field(mapping, "title").unwrap_or_else(|| id.clone());
        let file_stem = task_path
            .file_stem()
            .and_then(OsStr::to_str)
            .unwrap_or_default()
            .to_string();
        records.push(TaskRecord {
            path: task_path,
            file_stem,
            id,
            status,
            title,
            depends_on: string_list_field(mapping, "depends_on"),
        });
    }

    let done = records
        .iter()
        .filter(|task| status_bucket(&task.status) == StatusBucket::Terminal)
        .count();
    let in_progress_task = records.iter().find(|task| task.status == "in_progress");
    let in_progress = in_progress_task.map(|task| format!("{} in progress", task.title));
    let stalled = in_progress_task
        .and_then(|task| task_stall_minutes(path, &task.path, &task.id, now, stall_minutes));
    let is_open = |task: &&TaskRecord| status_bucket(&task.status) != StatusBucket::Terminal;
    let ready = records.iter().find(|task| {
        is_open(task)
            && task.status != "in_progress"
            && task.depends_on.iter().all(|dependency| {
                records
                    .iter()
                    .filter(|candidate| {
                        candidate.file_stem == *dependency || candidate.id == *dependency
                    })
                    .all(|candidate| status_bucket(&candidate.status) == StatusBucket::Terminal)
            })
    });
    let next = ready.or_else(|| {
        records
            .iter()
            .find(|task| is_open(task) && task.status != "in_progress")
    });
    let next = next.map(|task| format!("next: {}", task.title));
    (
        done,
        records.len(),
        in_progress.is_some(),
        in_progress.or(next),
        stalled,
        skipped,
    )
}

fn task_stall_minutes(
    plan_path: &Path,
    task_path: &Path,
    _task_id: &str,
    now: SystemTime,
    threshold: u64,
) -> Option<u64> {
    let mut activity = task_path.metadata().ok()?.modified().ok()?;
    let note = plan_path
        .parent()?
        .join("notes")
        .join(format!("{}.md", _task_id));
    match note.metadata() {
        Ok(metadata) => activity = activity.max(metadata.modified().ok()?),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return None,
    }
    stalled_minutes(now, activity, threshold)
}

pub(super) fn stalled_minutes(
    now: SystemTime,
    latest_activity: SystemTime,
    threshold: u64,
) -> Option<u64> {
    let elapsed = now
        .duration_since(latest_activity)
        .unwrap_or_default()
        .as_secs()
        / 60;
    (elapsed >= threshold).then_some(elapsed)
}

fn build_progress(
    path: &Path,
    records: &BTreeMap<PathBuf, PlanRecord>,
    child_map: &BTreeMap<PathBuf, Vec<PathBuf>>,
    siblings: &[PathBuf],
) -> PlanProgress {
    let record = &records[path];
    let child_paths = child_map.get(path).map(Vec::as_slice).unwrap_or_default();
    let group = record.group || !child_paths.is_empty();
    let (done, total, unit) = if group {
        (
            child_paths
                .iter()
                .filter(|child| records[*child].terminal)
                .count(),
            child_paths.len(),
            "plans",
        )
    } else {
        (record.task_done, record.task_total, "tasks")
    };
    let visible_children = child_paths
        .iter()
        .filter(|child| !records[*child].terminal)
        .cloned()
        .collect::<Vec<_>>();
    let ordered_children = dependency_order(&visible_children, records);
    let more_count = ordered_children.len().saturating_sub(DISPLAY_LIMIT);
    let waiting_on = waiting_on_sibling(record, siblings, records);
    let children = ordered_children
        .iter()
        .take(DISPLAY_LIMIT)
        .map(|child| build_progress(child, records, child_map, child_paths))
        .collect();
    let current = record
        .now_line
        .clone()
        .unwrap_or_else(|| record.now(group, waiting_on.as_deref()));
    PlanProgress {
        id: plain_text(&record.id),
        title: plain_text(&record.title),
        status: plain_text(&record.status),
        merge: record.merge,
        done,
        total,
        unit,
        now: plain_text(&current),
        owner: record.owner.as_deref().map(plain_text),
        group,
        children,
        more_count,
    }
}

fn merge_state(plan_path: &Path, status: &str) -> &'static str {
    let approved = plan_path
        .parent()
        .map(|directory| directory.join("review.md"))
        .and_then(|path| fs::read(path).ok())
        .and_then(|bytes| varde_workflow_core::frontmatter::parse(&bytes).ok())
        .and_then(|(frontmatter, _)| frontmatter.as_mapping().cloned())
        .and_then(|mapping| string_field(&mapping, "verdict"))
        .is_some_and(|verdict| verdict == "approved");
    if !approved {
        "none"
    } else if status == "completed" {
        "merged"
    } else {
        "ready"
    }
}

fn waiting_on_sibling(
    record: &PlanRecord,
    siblings: &[PathBuf],
    records: &BTreeMap<PathBuf, PlanRecord>,
) -> Option<String> {
    record
        .depends_on
        .iter()
        .filter(|dependency| dependency.as_str() != record.id.as_str())
        .find_map(|dependency| {
            siblings.iter().find_map(|sibling| {
                let sibling_record = &records[sibling];
                // A dependency is satisfied only when the sibling is `completed`;
                // any other status, including `cancelled`, keeps the plan waiting,
                // matching select-plans.py's `completed` requirement.
                (sibling_record.id == *dependency && sibling_record.status != "completed")
                    .then(|| sibling_record.id.clone())
            })
        })
}

fn dependency_order(paths: &[PathBuf], records: &BTreeMap<PathBuf, PlanRecord>) -> Vec<PathBuf> {
    let mut remaining = paths.to_vec();
    remaining.sort_by(|left, right| {
        records[left]
            .id
            .cmp(&records[right].id)
            .then_with(|| left.cmp(right))
    });
    let mut ordered = Vec::with_capacity(remaining.len());
    while !remaining.is_empty() {
        let ready = remaining.iter().position(|path| {
            !records[path].depends_on.iter().any(|dependency| {
                remaining
                    .iter()
                    .any(|sibling| records[sibling].id == *dependency)
            })
        });
        if let Some(index) = ready {
            ordered.push(remaining.remove(index));
        } else {
            ordered.extend(remaining);
            break;
        }
    }
    ordered
}

fn parent_plan(path: &Path, plans_dir: &Path, plans: &BTreeSet<PathBuf>) -> Option<PathBuf> {
    let mut directory = path.parent()?;
    while directory.starts_with(plans_dir) {
        let candidate = directory.join("plan.md");
        if candidate != path && plans.contains(&candidate) {
            return Some(candidate);
        }
        if directory == plans_dir {
            break;
        }
        directory = directory.parent()?;
    }
    None
}

fn compare_plan_paths(left: &Path, right: &Path) -> Ordering {
    let left_id = plan_id(left);
    let right_id = plan_id(right);
    match (date_prefix(left_id), date_prefix(right_id)) {
        (Some(left_date), Some(right_date)) => right_date
            .cmp(left_date)
            .then_with(|| left_id.cmp(right_id)),
        (Some(_), None) => Ordering::Less,
        (None, Some(_)) => Ordering::Greater,
        (None, None) => left_id.cmp(right_id),
    }
}

fn plan_id(path: &Path) -> &str {
    path.parent()
        .and_then(Path::file_name)
        .and_then(std::ffi::OsStr::to_str)
        .unwrap_or("plan")
}

fn date_prefix(id: &str) -> Option<&str> {
    let prefix = id.get(..10)?;
    let mut parts = prefix.split('-');
    let year = parts.next()?;
    let month = parts.next()?;
    let day = parts.next()?;
    (year.len() == 4
        && month.len() == 2
        && day.len() == 2
        && year.bytes().all(|byte| byte.is_ascii_digit())
        && month.bytes().all(|byte| byte.is_ascii_digit())
        && day.bytes().all(|byte| byte.is_ascii_digit())
        && id.as_bytes().get(10) == Some(&b'-'))
    .then_some(prefix)
}

pub(super) fn count_open_questions(body: &str) -> usize {
    let mut section_level = None;
    let mut count = 0;
    let mut fence = None;
    for line in body.lines() {
        let trimmed = line.trim_start();
        if let Some((marker, width)) = fence {
            if fence_end(trimmed, marker, width) {
                fence = None;
            }
            continue;
        }
        if let Some((marker, width)) = fence_start(trimmed) {
            fence = Some((marker, width));
            continue;
        }
        if let Some((level, title)) = markdown_heading(trimmed) {
            if section_level.is_some_and(|section| level <= section) {
                break;
            }
            if title.eq_ignore_ascii_case("open questions") {
                section_level = Some(level);
            }
            continue;
        }
        if section_level.is_some() && (trimmed.starts_with("- ") || trimmed.starts_with("* ")) {
            count += 1;
        }
    }
    count
}

fn markdown_heading(line: &str) -> Option<(usize, &str)> {
    let level = line.bytes().take_while(|byte| *byte == b'#').count();
    if !(1..=6).contains(&level) {
        return None;
    }
    let rest = &line[level..];
    if !rest.starts_with(' ') && !rest.starts_with('\t') {
        return None;
    }
    Some((level, rest.trim()))
}

fn fence_start(line: &str) -> Option<(char, usize)> {
    let marker = line.chars().next()?;
    if !matches!(marker, '`' | '~') {
        return None;
    }
    let width = line
        .chars()
        .take_while(|character| *character == marker)
        .count();
    (width >= 3).then_some((marker, width))
}

fn fence_end(line: &str, marker: char, width: usize) -> bool {
    line.chars()
        .take_while(|character| *character == marker)
        .count()
        >= width
        && line
            .chars()
            .skip_while(|character| *character == marker)
            .all(char::is_whitespace)
}

pub(super) fn string_field(mapping: &Mapping, name: &str) -> Option<String> {
    mapping
        .get(YamlValue::String(name.to_string()))
        .and_then(YamlValue::as_str)
        .map(str::to_string)
}

pub(super) fn string_list_field(mapping: &Mapping, name: &str) -> Vec<String> {
    let Some(value) = mapping.get(YamlValue::String(name.to_string())) else {
        return Vec::new();
    };
    let values = match value {
        YamlValue::Sequence(values) => values.iter().filter_map(YamlValue::as_str).collect(),
        YamlValue::String(value) => vec![value.as_str()],
        _ => Vec::new(),
    };
    values
        .into_iter()
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .collect()
}

pub(super) fn artifact_type(mapping: &Mapping) -> String {
    string_field(mapping, "artifact_type")
        .or_else(|| string_field(mapping, "type"))
        .unwrap_or_else(|| "plan".to_string())
}

pub(super) fn artifact_id(path: &Path, mapping: &Mapping) -> String {
    string_field(mapping, "id").unwrap_or_else(|| {
        if path.file_name().and_then(OsStr::to_str) == Some("plan.md") {
            plan_id(path).to_string()
        } else {
            path.file_stem()
                .and_then(OsStr::to_str)
                .unwrap_or("artifact")
                .to_string()
        }
    })
}

/// Return the canonical plan ID when its owner matches `owner`.
pub fn owned_plan_id(path: &Path, owner: &str) -> Option<String> {
    let bytes = fs::read(path).ok()?;
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(&bytes).ok()?;
    let mapping = frontmatter.as_mapping()?;
    if artifact_type(mapping) != "plan" || string_field(mapping, "owner").as_deref() != Some(owner) {
        return None;
    }
    Some(artifact_id(path, mapping))
}

pub(super) fn status_bucket(status: &str) -> StatusBucket {
    match status {
        "cancelled" | "done" | "complete" | "completed" | "dismissed" | "stale" | "archived" => {
            StatusBucket::Terminal
        }
        "backlog" | "draft" | "proposed" | "ready" => StatusBucket::Backlog,
        _ => StatusBucket::Other,
    }
}

/// A single-change directory (`task.md` without `plan.md`) lists as one line.
fn single_change_record(path: &Path, mapping: &Mapping) -> (PlanRecord, usize) {
    let id = plan_id(path).to_string();
    let title = string_field(mapping, "title").unwrap_or_else(|| id.clone());
    let status = string_field(mapping, "status").unwrap_or_else(|| "todo".to_string());
    let terminal = status_bucket(&status) == StatusBucket::Terminal;
    let record = PlanRecord {
        id,
        status,
        title,
        owner: None,
        group: false,
        open_questions: 0,
        task_done: 0,
        task_total: 0,
        task_in_progress: false,
        task_now: None,
        task_stalled: None,
        depends_on: string_list_field(mapping, "depends_on"),
        now_line: None,
        terminal,
        merge: "none",
    };
    (record, 0)
}

fn plain_text(value: &str) -> String {
    value.replace('—', "-")
}

fn render(report: &ProgressReport, date: &OsStr) -> Result<String> {
    let time = local_time(date)?;
    let mut lines = vec![format!("**Progress** {time}")];
    if report.plans.is_empty() && report.backlog_count == 0 {
        lines.push("No plans in a non-terminal status.".to_string());
    } else {
        for (index, plan) in report.plans.iter().enumerate() {
            render_plan(plan, &(index + 1).to_string(), 0, &mut lines);
        }
        if report.more_count > 0 {
            lines.push(format!("+{} more", report.more_count));
        }
    }
    if report.backlog_count > 0 {
        lines.push(format!("+{} backlog", report.backlog_count));
    }
    if report.skipped > 0 {
        lines.push(format!(
            "Skipped {} file(s): unknown artifact type or unreadable.",
            report.skipped
        ));
    }
    lines.push(String::new());
    Ok(lines.join("\n"))
}

fn render_with_cache(report: &ProgressReport, date: &OsStr, last_output: &Path) -> Result<String> {
    let rendered = render(report, date)?;
    let (header, list) = rendered
        .split_once('\n')
        .context("progress output is missing its header")?;
    let previous = read_last_output(last_output);
    write_last_output(last_output, list);
    if previous.as_deref() == Some(list) {
        Ok(format!("{header}: no change since last check.\n"))
    } else {
        Ok(rendered)
    }
}

fn read_last_output(path: &Path) -> Option<String> {
    fs::read_to_string(path).ok()
}

fn write_last_output(path: &Path, output: &str) {
    let Some(parent) = path.parent() else {
        return;
    };
    if fs::create_dir_all(parent).is_ok() {
        let _ = fs::write(path, output);
    }
}

fn local_time(date: &OsStr) -> Result<String> {
    let output = Command::new(date)
        .arg("+%H:%M")
        .output()
        .context("could not read local time with date +%H:%M")?;
    anyhow::ensure!(
        output.status.success(),
        "date +%H:%M exited with {}",
        output.status
    );
    Ok(String::from_utf8(output.stdout)?.trim().to_string())
}

fn render_plan(plan: &PlanProgress, label: &str, depth: usize, lines: &mut Vec<String>) {
    let indent = "   ".repeat(depth);
    let progress = if plan.total == 0 {
        String::new()
    } else if plan.group {
        format!(" (group) {}/{} plans", plan.done, plan.total)
    } else {
        format!(" {}/{}", plan.done, plan.total)
    };
    let bullet = if depth == 0 {
        String::new()
    } else {
        "- ".to_string()
    };
    let owner = plan
        .owner
        .as_deref()
        .map(|owner| format!(" (owner: {owner})"))
        .unwrap_or_default();
    lines.push(format!(
        "{indent}{bullet}{label}. {}{owner}{progress}: {}",
        plan.id, plan.now
    ));
    for (index, child) in plan.children.iter().enumerate() {
        let child_label = format!("{label}{}", alpha_label(index));
        render_plan(child, &child_label, depth + 1, lines);
    }
    if plan.more_count > 0 {
        lines.push(format!(
            "{}+{} more",
            "   ".repeat(depth + 1),
            plan.more_count
        ));
    }
}

fn alpha_label(mut index: usize) -> String {
    let mut label = String::new();
    loop {
        let letter = (b'a' + (index % 26) as u8) as char;
        label.insert(0, letter);
        if index < 26 {
            break;
        }
        index = index / 26 - 1;
    }
    label
}

/// Advisory staleness notices for plans whose review is old or whose reviewed
/// scope has later commits. Never affects the exit code.
fn staleness_notices(working: &Path, repo: Option<&Path>) -> Vec<String> {
    let Some(repo) = resolve_repo(repo) else {
        return Vec::new();
    };
    let plans_dir = working.join("plans");
    let mut paths = Vec::new();
    let mut skipped = 0;
    if plans_dir.is_dir() {
        collect_plan_paths(&plans_dir, &mut paths, &mut skipped);
    }
    let today = today_days();
    let mut notices = Vec::new();
    for path in paths {
        if let Some(notice) = staleness_notice(&path, &repo, today) {
            notices.push(notice);
        }
    }
    notices
}

/// The staleness notice for one plan, used by `varde plan now`.
pub(super) fn staleness_notice_for(plan_path: &Path, repo: Option<&Path>) -> Option<String> {
    let repo = resolve_repo(repo)?;
    staleness_notice(plan_path, &repo, today_days())
}

fn resolve_repo(repo: Option<&Path>) -> Option<PathBuf> {
    if let Some(repo) = repo {
        return Some(repo.canonicalize().unwrap_or_else(|_| repo.to_path_buf()));
    }
    let cwd = std::env::current_dir().ok()?;
    git_root(&cwd)
}

fn git_root(start: &Path) -> Option<PathBuf> {
    let (status, output) =
        crate::execution_wave_tools::git(start, &["rev-parse", "--show-toplevel"])?;
    if status != 0 {
        return None;
    }
    let root = output.trim();
    (!root.is_empty()).then(|| PathBuf::from(root))
}

fn staleness_notice(plan_path: &Path, repo: &Path, today: i64) -> Option<String> {
    let bytes = fs::read(plan_path).ok()?;
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(&bytes).ok()?;
    let mapping = frontmatter.as_mapping()?;
    let status = string_field(mapping, "status").unwrap_or_else(|| "backlog".to_string());
    if status_bucket(&status) == StatusBucket::Terminal {
        return None;
    }
    let reviewed_commit =
        string_field(mapping, "reviewed_commit").filter(|value| !value.is_empty())?;
    let id = artifact_id(plan_path, mapping);
    let patterns = plan_owns(plan_path, mapping);
    if !git_succeeds(
        repo,
        &["cat-file", "-e", &format!("{reviewed_commit}^{{commit}}")],
    ) {
        return Some(format!(
            "review commit {reviewed_commit} not found in {}",
            repo.display()
        ));
    }
    let days = reviewed_on_days(mapping)
        .map(|reviewed| (today - reviewed).max(0))
        .unwrap_or(0);
    if patterns.is_empty() {
        return (days > 7).then(|| format!("review of {id} is {days} days old"));
    }
    let commits = commits_touching(repo, &reviewed_commit, &patterns);
    if commits == 0 && days <= 7 {
        return None;
    }
    Some(format!(
        "review of {id} is {days} days old; {commits} commits since touched its scope"
    ))
}

fn plan_owns(plan_path: &Path, mapping: &Mapping) -> Vec<String> {
    let mut patterns = string_list_field(mapping, "shared");
    let Some(plan_dir) = plan_path.parent() else {
        return patterns;
    };
    let Ok(entries) = fs::read_dir(plan_dir.join("tasks")) else {
        return patterns;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(OsStr::to_str) != Some("md") {
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
        patterns.extend(string_list_field(mapping, "owns"));
        patterns.extend(string_list_field(mapping, "modifies"));
        patterns.extend(string_list_field(mapping, "creates"));
        for rename in string_list_field(mapping, "renames") {
            if let Some((from, to)) = rename.split_once("->") {
                patterns.push(from.trim().to_string());
                patterns.push(to.trim().to_string());
            }
        }
    }
    patterns.sort();
    patterns.dedup();
    patterns
}

fn commits_touching(repo: &Path, base: &str, patterns: &[String]) -> u64 {
    let range = format!("{base}..HEAD");
    let Some((status, output)) =
        crate::execution_wave_tools::git(repo, &["log", "--format=%H", "--name-only", &range])
    else {
        return 0;
    };
    if status != 0 {
        return 0;
    }
    let mut count = 0u64;
    let mut touched = false;
    for line in output.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        if line.len() == 40 && line.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            if touched {
                count += 1;
            }
            touched = false;
        } else if !touched
            && patterns
                .iter()
                .any(|pattern| crate::execution_wave_paths::matches_declaration(pattern, line))
        {
            touched = true;
        }
    }
    if touched {
        count += 1;
    }
    count
}

fn git_succeeds(repo: &Path, args: &[&str]) -> bool {
    crate::execution_wave_tools::git(repo, args).is_some_and(|(status, _)| status == 0)
}

fn reviewed_on_days(mapping: &Mapping) -> Option<i64> {
    let value = string_field(mapping, "reviewed_on")?;
    let mut parts = value.split('-');
    let year: i64 = parts.next()?.parse().ok()?;
    let month: i64 = parts.next()?.parse().ok()?;
    let day: i64 = parts.next()?.parse().ok()?;
    if parts.next().is_some() {
        return None;
    }
    Some(days_from_civil(year, month, day))
}

fn today_days() -> i64 {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;
    seconds.div_euclid(86_400)
}

/// Days since 1970-01-01 for a proleptic Gregorian date.
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = (if year >= 0 { year } else { year - 399 }) / 400;
    let yoe = year - era * 400;
    let doy = (153 * (if month > 2 { month - 3 } else { month + 9 }) + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::{PermissionsExt, symlink};

    #[test]
    fn merge_state_covers_none_ready_merged_and_unapproved_completion() {
        let root = temp_dir("merge-state");
        let active = write_plan(&root, "active", "type: plan\nstatus: active");
        assert_eq!(merge_state(&active, "active"), "none");

        let approved = write_plan(&root, "approved", "type: plan\nstatus: active");
        fs::write(
            approved.parent().unwrap().join("review.md"),
            "---\nverdict: approved\n---\n",
        )
        .unwrap();
        assert_eq!(merge_state(&approved, "active"), "ready");
        assert_eq!(merge_state(&approved, "completed"), "merged");
        assert_eq!(merge_state(&active, "completed"), "none");
        fs::remove_dir_all(root).unwrap();
    }

    fn temp_dir(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "varde-status-{label}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    fn write_date(root: &Path) -> PathBuf {
        let date = root.join("date");
        fs::write(&date, "#!/bin/sh\nprintf '09:41\\n'\n").unwrap();
        let mut permissions = fs::metadata(&date).unwrap().permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&date, permissions).unwrap();
        date
    }

    fn write_plan(working: &Path, directory: &str, frontmatter: &str) -> PathBuf {
        let path = working.join("plans").join(directory).join("plan.md");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, format!("---\n{frontmatter}\n---\n# Plan\n")).unwrap();
        path
    }

    fn write_task(plan: &Path, id: &str, status: &str) {
        let task = plan
            .parent()
            .unwrap()
            .join("tasks")
            .join(format!("{id}.md"));
        fs::create_dir_all(task.parent().unwrap()).unwrap();
        fs::write(task, format!("---\ntype: task\nstatus: {status}\n---\n")).unwrap();
    }

    fn write_task_frontmatter(plan: &Path, file_stem: &str, frontmatter: &str) {
        let task = plan
            .parent()
            .unwrap()
            .join("tasks")
            .join(format!("{file_stem}.md"));
        fs::create_dir_all(task.parent().unwrap()).unwrap();
        fs::write(task, format!("---\ntype: task\n{frontmatter}\n---\n")).unwrap();
    }

    fn task_now(plan: &Path) -> Option<String> {
        read_tasks(
            plan,
            UNIX_EPOCH + std::time::Duration::from_secs(10_000),
            30,
        )
        .3
    }

    #[test]
    fn next_skips_tasks_until_all_known_dependencies_are_terminal() {
        let root = temp_dir("next-dependencies");
        let working = root.join("working");
        let plan = write_plan(&working, "next-dependencies", "status: active");
        write_task_frontmatter(
            &plan,
            "a-blocked",
            "status: todo\ndepends_on: [b-done, c-pending]",
        );
        write_task_frontmatter(&plan, "b-done", "status: done");
        write_task_frontmatter(&plan, "c-pending", "status: todo\ndepends_on: a-blocked");
        write_task_frontmatter(&plan, "d-ready", "status: todo");

        assert_eq!(task_now(&plan).as_deref(), Some("next: d-ready"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn unknown_dependencies_are_satisfied() {
        let root = temp_dir("next-unknown-dependency");
        let working = root.join("working");
        let plan = write_plan(&working, "next-unknown-dependency", "status: active");
        write_task_frontmatter(&plan, "a-blocked", "status: todo\ndepends_on: z-pending");
        write_task_frontmatter(
            &plan,
            "b-external",
            "status: todo\ndepends_on: missing-task",
        );
        write_task_frontmatter(&plan, "z-pending", "status: todo");

        assert_eq!(task_now(&plan).as_deref(), Some("next: b-external"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn all_waiting_cycles_fall_back_to_the_first_non_terminal_task() {
        let root = temp_dir("next-cycle");
        let working = root.join("working");
        let plan = write_plan(&working, "next-cycle", "status: active");
        write_task_frontmatter(&plan, "a-first", "status: todo\ndepends_on: b-second");
        write_task_frontmatter(&plan, "b-second", "status: todo\ndepends_on: a-first");

        assert_eq!(task_now(&plan).as_deref(), Some("next: a-first"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_later_sorted_dependency_still_blocks_its_dependent() {
        let root = temp_dir("next-later-dependency");
        let working = root.join("working");
        let plan = write_plan(&working, "next-later-dependency", "status: active");
        write_task_frontmatter(&plan, "a-dependent", "status: todo\ndepends_on: z-later");
        write_task_frontmatter(&plan, "b-ready", "status: todo");
        write_task_frontmatter(&plan, "z-later", "status: todo");

        assert_eq!(task_now(&plan).as_deref(), Some("next: b-ready"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn dependencies_match_frontmatter_task_ids() {
        let root = temp_dir("next-frontmatter-id");
        let working = root.join("working");
        let plan = write_plan(&working, "next-frontmatter-id", "status: active");
        write_task_frontmatter(&plan, "a-dependent", "status: todo\ndepends_on: named-task");
        write_task_frontmatter(
            &plan,
            "b-file-stem",
            "id: named-task\nstatus: todo\ndepends_on: named-task",
        );
        write_task_frontmatter(&plan, "c-ready", "status: todo");

        assert_eq!(task_now(&plan).as_deref(), Some("next: c-ready"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn commit_pins_next_skips_artifact_pins_until_remove_exceptions_is_done() {
        let root = temp_dir("next-commit-pins");
        let working = root.join("working");
        let plan = write_plan(&working, "review/commit-pins", "status: active");
        write_task_frontmatter(
            &plan,
            "cp-artifact-pins",
            "status: todo\ndepends_on:\n  - cp-remove-exceptions",
        );
        write_task_frontmatter(&plan, "cp-remove-exceptions", "status: todo");
        write_task_frontmatter(&plan, "cp-dirty-scope", "status: todo");

        assert_eq!(task_now(&plan).as_deref(), Some("next: cp-dirty-scope"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn in_progress_task_wins_even_when_an_earlier_task_is_ready() {
        let root = temp_dir("next-in-progress");
        let working = root.join("working");
        let plan = write_plan(&working, "next-in-progress", "status: active");
        write_task_frontmatter(&plan, "a-ready", "status: todo");
        write_task_frontmatter(
            &plan,
            "b-in-progress",
            "status: in_progress\ndepends_on: c-pending",
        );
        write_task_frontmatter(&plan, "c-pending", "status: todo");

        assert_eq!(
            task_now(&plan).as_deref(),
            Some("b-in-progress in progress")
        );
        fs::remove_dir_all(root).unwrap();
    }

    fn collect_fixture(working: &Path) -> ProgressReport {
        collect_from(
            working,
            UNIX_EPOCH + std::time::Duration::from_secs(10_000),
            30,
        )
    }

    fn git_repo(label: &str) -> (PathBuf, Vec<String>) {
        let root = temp_dir(label);
        for args in [
            &["init", "-q"][..],
            &["config", "user.email", "status-test@example.invalid"][..],
            &["config", "user.name", "Status Test"][..],
        ] {
            let output = Command::new("git")
                .args(args)
                .current_dir(&root)
                .output()
                .unwrap();
            assert!(output.status.success());
        }
        let commit = |message: &str| -> String {
            let output = Command::new("git")
                .args(["commit", "--allow-empty", "-qm", message])
                .current_dir(&root)
                .output()
                .unwrap();
            assert!(output.status.success());
            let output = Command::new("git")
                .args(["rev-parse", "HEAD"])
                .current_dir(&root)
                .output()
                .unwrap();
            String::from_utf8(output.stdout).unwrap().trim().to_owned()
        };
        let first = commit("first");
        (root, vec![first])
    }

    fn commit_path(repo: &Path, message: &str, path: &str, content: &str) {
        let path = repo.join(path);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, content).unwrap();
        let relative = path.strip_prefix(repo).unwrap();
        let add = Command::new("git")
            .args(["add", "--"])
            .arg(relative)
            .current_dir(repo)
            .output()
            .unwrap();
        assert!(add.status.success());
        let output = Command::new("git")
            .args(["commit", "-qm", message])
            .current_dir(repo)
            .output()
            .unwrap();
        assert!(output.status.success());
    }

    #[test]
    fn staleness_notice_reports_commits_that_touch_owned_paths() {
        let (repo, shas) = git_repo("staleness-commits");
        let working = repo.join("working");
        let plan = write_plan(
            &working,
            "2026-10-01-feature",
            &format!(
                "type: plan\nstatus: active\nreviewed_commit: {}\nreviewed_on: 2026-10-01",
                shas[0]
            ),
        );
        write_task_frontmatter(&plan, "impl", "status: done\nowns: [src/owned.rs]");
        commit_path(&repo, "touch owned", "src/owned.rs", "v1\n");

        let today = days_from_civil(2026, 10, 2);
        let notice = staleness_notice(&plan, &repo, today).unwrap();
        assert!(
            notice.contains("2026-10-01-feature is 1 days old")
                && notice.ends_with("1 commits since touched its scope"),
            "{notice}"
        );
        fs::remove_dir_all(repo).unwrap();
    }

    #[test]
    fn staleness_notice_without_owns_shows_age_only() {
        let (repo, shas) = git_repo("staleness-no-owns");
        let working = repo.join("working");
        let plan = write_plan(
            &working,
            "2026-09-20-known",
            &format!(
                "type: plan\nstatus: active\nreviewed_commit: {}\nreviewed_on: 2026-09-20",
                shas[0]
            ),
        );
        let today = days_from_civil(2026, 10, 5);
        let notice = staleness_notice(&plan, &repo, today).unwrap();
        assert_eq!(notice, "review of 2026-09-20-known is 15 days old");
        fs::remove_dir_all(repo).unwrap();
    }

    #[test]
    fn staleness_notice_names_an_unknown_reviewed_commit() {
        let (repo, _) = git_repo("staleness-unknown");
        let working = repo.join("working");
        let plan = write_plan(
            &working,
            "2026-10-01-unknown",
            "type: plan\nstatus: active\nreviewed_commit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\nreviewed_on: 2026-10-01",
        );
        let notice = staleness_notice(&plan, &repo, days_from_civil(2026, 10, 2)).unwrap();
        assert!(
            notice.contains("review commit aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa not found in"),
            "{notice}"
        );
        fs::remove_dir_all(repo).unwrap();
    }

    #[test]
    fn staleness_notice_skips_an_empty_reviewed_commit() {
        // PLAN-TEMPLATE.md writes `reviewed_commit:` empty until Finalize.
        let (repo, _) = git_repo("staleness-empty-commit");
        let working = repo.join("working");
        let plan = write_plan(
            &working,
            "2026-10-09-template-fresh",
            "type: plan\nstatus: active\nreviewed_commit:\n",
        );
        assert_eq!(
            staleness_notice(&plan, &repo, days_from_civil(2030, 1, 1)),
            None
        );
        fs::remove_dir_all(repo).unwrap();
    }

    #[test]
    fn staleness_notice_skips_completed_and_cancelled_plans() {
        let (repo, shas) = git_repo("staleness-terminal");
        let working = repo.join("working");
        let completed = write_plan(
            &working,
            "2026-01-01-completed",
            &format!(
                "type: plan\nstatus: completed\nreviewed_commit: {}\nreviewed_on: 2026-01-01",
                shas[0]
            ),
        );
        let cancelled = write_plan(
            &working,
            "2026-01-01-old",
            &format!(
                "type: plan\nstatus: cancelled\nreviewed_commit: {}\nreviewed_on: 2026-01-01",
                shas[0]
            ),
        );
        assert_eq!(
            staleness_notice(&completed, &repo, days_from_civil(2030, 1, 1)),
            None
        );
        assert_eq!(
            staleness_notice(&cancelled, &repo, days_from_civil(2030, 1, 1)),
            None
        );
        fs::remove_dir_all(repo).unwrap();
    }

    #[test]
    fn staleness_notice_is_absent_within_seven_days_and_no_scope_commits() {
        let (repo, shas) = git_repo("staleness-fresh");
        let working = repo.join("working");
        let plan = write_plan(
            &working,
            "2026-10-01-fresh",
            &format!(
                "type: plan\nstatus: active\nreviewed_commit: {}\nreviewed_on: 2026-10-01",
                shas[0]
            ),
        );
        write_task_frontmatter(&plan, "impl", "status: done\nowns: [src/owned.rs]");
        assert_eq!(
            staleness_notice(&plan, &repo, days_from_civil(2026, 10, 2)),
            None
        );
        fs::remove_dir_all(repo).unwrap();
    }

    #[test]
    fn single_change_dir_lists_as_one_line() {
        let root = temp_dir("single-change-status");
        let working = root.join("working");
        let dir = working.join("plans/2026-10-09-single");
        fs::create_dir_all(&dir).unwrap();
        fs::write(
            dir.join("task.md"),
            "---\ntype: task\nstatus: todo\ntitle: Bump the dependency\n---\n",
        )
        .unwrap();
        let plan = write_plan(&working, "2026-10-09-feature", "type: plan\nstatus: active");
        write_task(&plan, "one", "todo");

        let report = collect_fixture(&working);
        assert_eq!(report.skipped, 0);
        assert_eq!(report.plans.len(), 2);
        let single = report
            .plans
            .iter()
            .find(|item| item.id == "2026-10-09-single")
            .unwrap();
        assert_eq!(single.total, 0);
        assert_eq!(single.title, "Bump the dependency");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn cancelled_status_hides_plan() {
        let root = temp_dir("cancelled-status");
        let working = root.join("working");
        write_plan(
            &working,
            "2026-09-01-cancelled",
            "type: plan\nstatus: cancelled",
        );
        let active = write_plan(&working, "2026-09-02-active", "type: plan\nstatus: active");
        write_task(&active, "one", "todo");

        let report = collect_fixture(&working);
        assert_eq!(report.plans.len(), 1);
        assert_eq!(report.plans[0].id, "2026-09-02-active");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn progress_header_uses_local_time_from_date() {
        let root = temp_dir("date");
        let date = write_date(&root);

        let report = ProgressReport {
            plans: Vec::new(),
            more_count: 0,
            backlog_count: 0,
            skipped: 0,
        };
        assert_eq!(
            render(&report, date.as_os_str()).unwrap(),
            "**Progress** 09:41\nNo plans in a non-terminal status.\n"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn legacy_plan_and_task_statuses_are_accepted() {
        let root = temp_dir("legacy-status");
        let working = root.join("working");
        write_plan(&working, "done-plan", "type: plan\nstatus: done");
        let proposed = write_plan(&working, "proposed-plan", "type: plan\nstatus: proposed");
        let task = proposed.parent().unwrap().join("tasks/backlog.md");
        fs::create_dir_all(task.parent().unwrap()).unwrap();
        fs::write(&task, "---\ntype: task\nstatus: backlog\n---\n").unwrap();

        let report = collect_fixture(&working);
        assert_eq!(report.skipped, 0);
        assert_eq!(report.plans.len(), 1);
        assert_eq!(report.plans[0].id, "proposed-plan");
        assert_eq!(report.plans[0].status, "proposed");
        assert_eq!((report.plans[0].done, report.plans[0].total), (0, 1));
        assert_eq!(report.plans[0].now, "next: backlog");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn missing_plan_and_task_fields_keep_their_defaults() {
        let root = temp_dir("defaults");
        let working = root.join("working");
        let plan = write_plan(&working, "default-plan", "title: Default Plan");
        let task = plan.parent().unwrap().join("tasks/default.md");
        fs::create_dir_all(task.parent().unwrap()).unwrap();
        fs::write(&task, "---\ntype: task\n---\n").unwrap();

        let report = collect_fixture(&working);
        assert_eq!(report.plans.len(), 1);
        assert_eq!(report.plans[0].status, "backlog");
        assert_eq!((report.plans[0].done, report.plans[0].total), (0, 1));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn unknown_types_are_skipped_counted_and_warned_once() {
        let root = temp_dir("unknown-types");
        let working = root.join("working");
        write_plan(&working, "visible", "type: plan\nstatus: active");
        write_plan(&working, "ignored-plan", "type: review-fix\nstatus: active");
        let task = working.join("plans/visible/tasks/review-fix.md");
        fs::create_dir_all(task.parent().unwrap()).unwrap();
        fs::write(&task, "---\ntype: review-fix\nstatus: done\n---\n").unwrap();

        let report = collect_fixture(&working);
        assert_eq!(report.skipped, 2);
        assert_eq!(report.plans.len(), 1);
        let date = write_date(&root);
        let rendered = render(&report, date.as_os_str()).unwrap();
        assert!(rendered.contains("1. visible: no tasks yet\n"));
        assert_eq!(
            rendered
                .matches("Skipped 2 file(s): unknown artifact type or unreadable.")
                .count(),
            1
        );
        assert_eq!(serde_json::to_value(report).unwrap()["skipped"], 2);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn malformed_and_unreadable_artifacts_are_skipped_and_counted() {
        let root = temp_dir("unreadable");
        let working = root.join("working");
        let valid = write_plan(&working, "valid", "type: plan\nstatus: active");
        write_plan(&working, "malformed", "type: [plan");
        let broken_plan = working.join("plans/unreadable/plan.md");
        fs::create_dir_all(broken_plan.parent().unwrap()).unwrap();
        symlink(root.join("missing-plan.md"), &broken_plan).unwrap();
        let broken_task = valid.parent().unwrap().join("tasks/unreadable.md");
        fs::create_dir_all(broken_task.parent().unwrap()).unwrap();
        symlink(root.join("missing-task.md"), &broken_task).unwrap();

        let report = collect_fixture(&working);
        assert_eq!(report.skipped, 3);
        assert_eq!(report.plans.len(), 1);
        assert_eq!(report.plans[0].id, "valid");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn status_synonym_buckets_hide_terminal_and_show_backlog_and_unknown_values() {
        let root = temp_dir("synonyms");
        let working = root.join("working");
        for (index, status) in [
            "done",
            "complete",
            "completed",
            "dismissed",
            "stale",
            "archived",
        ]
        .into_iter()
        .enumerate()
        {
            write_plan(
                &working,
                &format!("terminal-{index}"),
                &format!("type: plan\nstatus: {status}"),
            );
            assert_eq!(status_bucket(status), StatusBucket::Terminal);
        }
        for (index, status) in ["backlog", "draft", "proposed", "ready"]
            .into_iter()
            .enumerate()
        {
            write_plan(
                &working,
                &format!("backlog-{index}"),
                &format!("type: plan\nstatus: {status}"),
            );
            assert_eq!(status_bucket(status), StatusBucket::Backlog);
        }
        write_plan(&working, "unknown", "type: plan\nstatus: reviewing");
        assert_eq!(status_bucket("reviewing"), StatusBucket::Other);
        let archived_task = working.join("plans/backlog-3/tasks/archived.md");
        fs::create_dir_all(archived_task.parent().unwrap()).unwrap();
        fs::write(&archived_task, "---\ntype: task\nstatus: archived\n---\n").unwrap();
        let backlog_task = working.join("plans/backlog-3/tasks/proposed.md");
        fs::write(&backlog_task, "---\ntype: task\nstatus: proposed\n---\n").unwrap();

        let report = collect_fixture(&working);
        let statuses = report
            .plans
            .iter()
            .map(|plan| plan.status.as_str())
            .collect::<BTreeSet<_>>();
        assert_eq!(report.plans.len(), 4);
        assert_eq!(report.backlog_count, 1);
        assert_eq!(
            statuses,
            ["draft", "proposed", "ready", "reviewing"]
                .into_iter()
                .collect()
        );
        let ready = report
            .plans
            .iter()
            .find(|plan| plan.status == "ready")
            .unwrap();
        assert_eq!((ready.done, ready.total), (1, 2));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn repeated_render_uses_one_line_until_the_list_changes() {
        let root = temp_dir("no-change");
        let date = write_date(&root);
        let last_output = root.join("working/.cache/plan-status-last.txt");
        let report = ProgressReport {
            plans: Vec::new(),
            more_count: 0,
            backlog_count: 0,
            skipped: 0,
        };
        assert_eq!(
            render_with_cache(&report, date.as_os_str(), &last_output).unwrap(),
            "**Progress** 09:41\nNo plans in a non-terminal status.\n"
        );
        assert_eq!(
            read_last_output(&last_output).as_deref(),
            Some("No plans in a non-terminal status.\n")
        );
        assert_eq!(
            render_with_cache(&report, date.as_os_str(), &last_output).unwrap(),
            "**Progress** 09:41: no change since last check.\n"
        );
        let changed = ProgressReport {
            skipped: 1,
            ..report
        };
        assert_eq!(
            render_with_cache(&changed, date.as_os_str(), &last_output).unwrap(),
            "**Progress** 09:41\nNo plans in a non-terminal status.\nSkipped 1 file(s): unknown artifact type or unreadable.\n"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn stall_threshold_uses_whole_minutes_and_newest_activity() {
        let now = UNIX_EPOCH + std::time::Duration::from_secs(10_000);
        let twenty_minutes_ago = now - std::time::Duration::from_secs(20 * 60);
        let twenty_minutes_and_one_second_ago = now - std::time::Duration::from_secs(20 * 60 + 1);
        assert_eq!(stalled_minutes(now, twenty_minutes_ago, 20), Some(20));
        assert_eq!(
            stalled_minutes(now, twenty_minutes_and_one_second_ago, 20),
            Some(20)
        );
        assert_eq!(
            stalled_minutes(now, now - std::time::Duration::from_secs(19 * 60 + 59), 20),
            None
        );

        // A newer task note, commit, or reported worktree edit resets idle age.
        let task_activity = now - std::time::Duration::from_secs(40 * 60);
        for newer_activity in [
            now - std::time::Duration::from_secs(2 * 60),
            now - std::time::Duration::from_secs(1),
        ] {
            assert_eq!(
                stalled_minutes(now, task_activity.max(newer_activity), 20),
                None
            );
        }
    }

    #[test]
    fn taskless_child_shows_unfinished_sibling_dependency() {
        let root = temp_dir("child-dependency");
        let working = root.join("working");
        write_plan(
            &working,
            "group",
            "type: plan\nstatus: active\nshape: group",
        );
        write_plan(
            &working,
            "group/2026-02-02-dependent",
            "type: plan\nstatus: active\ndepends_on: [unknown, 2026-02-01-sibling, 7]",
        );
        write_plan(
            &working,
            "group/2026-02-01-sibling",
            "type: plan\nstatus: active\ndepends_on: odd-value",
        );

        let report = collect_fixture(&working);
        let group = &report.plans[0];
        let dependent = group
            .children
            .iter()
            .find(|child| child.id == "2026-02-02-dependent")
            .unwrap();
        assert_eq!(dependent.now, "waits on 2026-02-01-sibling");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn children_are_ordered_by_dependencies_then_id() {
        let root = temp_dir("child-order");
        let working = root.join("working");
        write_plan(
            &working,
            "group",
            "type: plan\nstatus: active\nshape: group",
        );
        write_plan(
            &working,
            "group/2026-01-03-a-dependent",
            "type: plan\nstatus: active\ndepends_on: [2026-01-01-z-dependency]",
        );
        write_plan(
            &working,
            "group/2025-01-01-b-ready",
            "type: plan\nstatus: active",
        );
        write_plan(
            &working,
            "group/2026-01-01-z-dependency",
            "type: plan\nstatus: active",
        );

        let report = collect_fixture(&working);
        let ids = report.plans[0]
            .children
            .iter()
            .map(|child| child.id.as_str())
            .collect::<Vec<_>>();
        assert_eq!(
            ids,
            [
                "2025-01-01-b-ready",
                "2026-01-01-z-dependency",
                "2026-01-03-a-dependent"
            ]
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn backlog_collapses_after_task_activity_and_rest_plans() {
        let root = temp_dir("backlog-collapse");
        let working = root.join("working");
        let in_progress = write_plan(&working, "2020-01-01-in-progress", "status: active");
        write_task(&in_progress, "active", "in_progress");
        for id in [
            "2026-01-03-task-new",
            "2026-01-02-task-middle",
            "2026-01-01-task-old",
        ] {
            let plan = write_plan(&working, id, "status: active");
            write_task(&plan, "todo", "todo");
        }
        write_plan(&working, "2026-01-04-rest-new", "status: active");
        write_plan(&working, "2025-01-01-rest-old", "status: active");
        for index in 0..8 {
            write_plan(
                &working,
                &format!("2020-01-{index:02}-backlog-{index}"),
                "status: backlog",
            );
        }

        let report = collect_fixture(&working);
        let ids = report
            .plans
            .iter()
            .map(|plan| plan.id.as_str())
            .collect::<Vec<_>>();
        assert_eq!(
            ids,
            [
                "2020-01-01-in-progress",
                "2026-01-03-task-new",
                "2026-01-02-task-middle",
                "2026-01-01-task-old",
                "2026-01-04-rest-new",
            ]
        );
        assert_eq!(report.more_count, 1);
        assert_eq!(report.backlog_count, 8);
        let date = write_date(&root);
        let rendered = render(&report, date.as_os_str()).unwrap();
        assert!(rendered.contains("+1 more\n"));
        assert!(rendered.contains("+8 backlog\n"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn taskless_plans_children_and_groups_never_render_zero_over_zero() {
        let root = temp_dir("no-zero-over-zero");
        let working = root.join("working");
        write_plan(&working, "2026-03-01-group", "status: active\nshape: group");
        write_plan(&working, "2026-03-01-group/child", "status: active");
        write_plan(
            &working,
            "2026-03-02-empty-group",
            "status: active\nshape: group",
        );
        write_plan(&working, "2026-03-03-leaf", "status: active");

        let report = collect_fixture(&working);
        let date = write_date(&root);
        let rendered = render(&report, date.as_os_str()).unwrap();
        let json = serde_json::to_string(&report).unwrap();
        assert!(!rendered.contains("0/0"), "{rendered}");
        assert!(!json.contains("0/0"), "{json}");
        assert!(rendered.contains("(group) 0/1 plans: active"));
        assert!(rendered.contains("2026-03-02-empty-group: active"));
        assert!(rendered.contains("2026-03-03-leaf: no tasks yet"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn all_terminal_group_shows_its_status_without_task_state() {
        let root = temp_dir("terminal-group-status");
        let working = root.join("working");
        write_plan(&working, "2026-04-01-group", "status: active\nshape: group");
        for child in ["one", "two", "three"] {
            write_plan(
                &working,
                &format!("2026-04-01-group/{child}"),
                "status: completed",
            );
        }

        let report = collect_fixture(&working);
        let group = &report.plans[0];
        assert_eq!((group.done, group.total), (3, 3));
        assert_eq!(group.now, "active");
        assert!(group.children.is_empty());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn self_dependency_does_not_report_waiting_on_self() {
        let root = temp_dir("self-dependency");
        let working = root.join("working");
        write_plan(
            &working,
            "group",
            "type: plan\nstatus: active\nshape: group",
        );
        write_plan(
            &working,
            "group/self-dep",
            "type: plan\nstatus: active\ndepends_on: [self-dep]",
        );

        let report = collect_fixture(&working);
        let child = &report.plans[0].children[0];
        assert_eq!(child.now, "no tasks yet");
        assert!(!child.now.contains("waits on self-dep"));
        fs::remove_dir_all(root).unwrap();
    }
}
