//! Derive the session-notes [`BlockModel`] from plan files and git.
//!
//! The classifier in `watch` decides each plan's state; this module only maps
//! that result onto the rows and the blocked-tasks line of the generated block.

use crate::commands::watch::{ClassifiedPlan, PlanState as Classified};
use crate::commands::watch_block::{BlockModel, PlanRow, PlanState};
use std::time::{SystemTime, UNIX_EPOCH};

/// Classify every watched plan in `working` and build the block model.
#[cfg(test)]
pub(super) fn collect(
    working: &std::path::Path,
    repo: &std::path::Path,
    now: SystemTime,
    threshold_secs: u64,
) -> BlockModel {
    model(&crate::commands::watch::scan(
        working,
        repo,
        now,
        threshold_secs,
    ))
}

/// Map classified plans onto block rows and the blocked-tasks line.
pub(super) fn model(plans: &[ClassifiedPlan]) -> BlockModel {
    BlockModel {
        rows: plans.iter().map(row).collect(),
        blocked_tasks: plans
            .iter()
            .flat_map(|plan| {
                plan.blocked_tasks
                    .iter()
                    .map(|task| format!("{}/{task}", plan.id))
            })
            .collect(),
    }
}

fn row(plan: &ClassifiedPlan) -> PlanRow {
    PlanRow {
        id: plan.id.clone(),
        state: state(plan),
        done: plan.done,
        total: plan.total,
        blocked: plan.blocked_tasks.len(),
        open_questions: plan.open_questions,
        now: plan.now_line.clone(),
        idle_no_handback: plan.idle_no_handback,
    }
}

/// A plan that needs a decision still shows as active; its `q<n>` marker
/// carries the open-question count.
fn state(plan: &ClassifiedPlan) -> PlanState {
    match plan.state {
        Classified::Active | Classified::NeedsDecision => PlanState::Active,
        Classified::Blocked => PlanState::Blocked,
        Classified::MergeReady => PlanState::MergeReady,
        Classified::Waiting => PlanState::Waiting,
        Classified::Finished => PlanState::Finished,
        Classified::Stale => PlanState::Stale {
            since: clock_time(plan.newest_activity),
        },
    }
}

/// `HH:MM` in UTC, so every watcher renders the same bytes whatever its zone.
fn clock_time(at: SystemTime) -> String {
    let seconds = at.duration_since(UNIX_EPOCH).unwrap_or_default().as_secs();
    format!("{:02}:{:02}", seconds / 3600 % 24, seconds / 60 % 60)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::watch_block::render;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::time::Duration;

    fn temp_dir(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "varde-watch-state-{label}-{}-{}",
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

    fn write_plan(working: &Path, directory: &str, frontmatter: &str, body: &str) -> PathBuf {
        let plan = working.join("plans").join(directory).join("plan.md");
        fs::create_dir_all(plan.parent().unwrap()).unwrap();
        fs::write(
            &plan,
            format!("---\ntype: plan\n{frontmatter}\n---\n\n{body}\n"),
        )
        .unwrap();
        plan
    }

    fn write_task(plan: &Path, stem: &str, status: &str) {
        let task = plan
            .parent()
            .unwrap()
            .join("tasks")
            .join(format!("{stem}.md"));
        fs::create_dir_all(task.parent().unwrap()).unwrap();
        fs::write(&task, format!("---\ntype: task\nstatus: {status}\n---\n")).unwrap();
    }

    /// Write the `plan-now` file of a top-level plan directory.
    fn write_now_line(working: &Path, directory: &str, line: &str) -> PathBuf {
        let path = working.join("plan-now").join(format!("{directory}.txt"));
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, format!("{line}\n")).unwrap();
        path
    }

    /// Backdate every file under the plan directory.
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

    fn now() -> SystemTime {
        UNIX_EPOCH + Duration::from_secs(2_000_000_000)
    }

    fn collect_for(working: &Path, repo: &Path) -> BlockModel {
        collect(working, repo, now(), 60)
    }

    fn fixture(label: &str) -> (PathBuf, PathBuf, PathBuf) {
        let root = temp_dir(label);
        let working = root.join("working");
        let repo = root.join("repo");
        fs::create_dir_all(&repo).unwrap();
        (root, working, repo)
    }

    #[test]
    fn a_row_carries_progress_blocked_count_questions_and_now_line() {
        let (root, working, repo) = fixture("row");
        let plan = write_plan(
            &working,
            "2026-10-10-alpha",
            "status: active",
            "## Open Questions\n\n- which store?\n- which flag?\n",
        );
        write_task(&plan, "one", "completed");
        write_task(&plan, "two", "blocked");
        write_task(&plan, "three", "in_progress");
        let now_path = write_now_line(&working, "2026-10-10-alpha", "wiring the cache");
        set_tree_modified(&plan, now() - Duration::from_secs(5));
        set_modified(&now_path, now() - Duration::from_secs(5));

        let model = collect_for(&working, &repo);

        assert_eq!(
            model.rows,
            vec![PlanRow {
                id: "2026-10-10-alpha".to_string(),
                state: PlanState::Active,
                done: 1,
                total: 3,
                blocked: 1,
                open_questions: 2,
                now: Some("wiring the cache".to_string()),
                idle_no_handback: false,
            }]
        );
        assert_eq!(
            model.blocked_tasks,
            vec!["2026-10-10-alpha/two".to_string()]
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_stale_plan_shows_the_clock_time_of_its_newest_activity() {
        let (root, working, repo) = fixture("stale");
        let plan = write_plan(&working, "2026-10-10-idle", "status: active", "body");
        write_task(&plan, "one", "todo");
        // 2_000_000_000 - 240 s is 03:33:20 UTC minus 4 min = 03:29:20.
        set_tree_modified(&plan, now() - Duration::from_secs(240));

        let model = collect_for(&working, &repo);

        assert_eq!(
            model.rows[0].state,
            PlanState::Stale {
                since: "03:29".to_string()
            }
        );
        assert_eq!(model.rows[0].blocked, 0);
        assert!(model.blocked_tasks.is_empty());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn states_map_onto_block_states() {
        let (root, working, repo) = fixture("states");
        let recent = now() - Duration::from_secs(5);

        let merge = write_plan(&working, "2026-10-10-merge", "status: active", "body");
        write_task(&merge, "one", "completed");
        set_tree_modified(&merge, recent);

        let blocked = write_plan(&working, "2026-10-10-blocked", "status: blocked", "body");
        set_tree_modified(&blocked, recent);

        let decide = write_plan(
            &working,
            "2026-10-10-decide",
            "status: active",
            "## Open Questions\n\n- one?\n",
        );
        set_tree_modified(&decide, recent);

        let done = write_plan(&working, "2026-10-10-done", "status: completed", "body");
        set_tree_modified(&done, recent);

        let backlog = write_plan(&working, "2026-10-10-later", "status: backlog", "body");
        set_tree_modified(&backlog, recent);

        let old_done = write_plan(&working, "2026-10-10-old", "status: completed", "body");
        set_tree_modified(&old_done, now() - Duration::from_secs(600));

        let model = collect_for(&working, &repo);
        let states = model
            .rows
            .iter()
            .map(|row| (row.id.as_str(), row.state.clone()))
            .collect::<Vec<_>>();

        assert_eq!(
            states,
            vec![
                ("2026-10-10-blocked", PlanState::Blocked),
                ("2026-10-10-decide", PlanState::Active),
                ("2026-10-10-done", PlanState::Finished),
                ("2026-10-10-merge", PlanState::MergeReady),
            ]
        );
        assert_eq!(model.rows[1].open_questions, 1);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_live_waiting_marker_shows_as_waiting() {
        let (root, working, repo) = fixture("waiting");
        let plan = write_plan(&working, "2026-10-10-wait", "status: active", "body");
        write_task(&plan, "one", "in_progress");
        let now_path = write_now_line(&working, "2026-10-10-wait", "waiting: review");
        let idle = now() - Duration::from_secs(120);
        set_tree_modified(&plan, idle);
        set_modified(&now_path, idle);

        let model = collect_for(&working, &repo);

        assert_eq!(model.rows[0].state, PlanState::Waiting);
        assert_eq!(model.rows[0].now.as_deref(), Some("waiting: review"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn blocked_tasks_span_plans_and_render_on_one_line() {
        let (root, working, repo) = fixture("blocked-line");
        let recent = now() - Duration::from_secs(5);
        for (directory, tasks) in [
            ("2026-10-10-a", vec![("x", "blocked"), ("y", "todo")]),
            ("2026-10-10-b", vec![("z", "blocked"), ("w", "in_progress")]),
        ] {
            let plan = write_plan(&working, directory, "status: active", "body");
            for (stem, status) in tasks {
                write_task(&plan, stem, status);
            }
            set_tree_modified(&plan, recent);
        }

        let model = collect_for(&working, &repo);
        let text = render(&model);

        assert!(text.contains("blocked tasks: 2026-10-10-a/x, 2026-10-10-b/z"));
        assert!(text.contains("2026-10-10-a [active] 0/2, 1 blocked"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn no_watched_plans_gives_an_empty_model() {
        let (root, working, repo) = fixture("empty");
        assert_eq!(collect_for(&working, &repo), BlockModel::default());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn clock_time_is_zero_padded_utc() {
        assert_eq!(
            clock_time(UNIX_EPOCH + Duration::from_secs(3 * 3600 + 5 * 60)),
            "03:05"
        );
        assert_eq!(
            clock_time(UNIX_EPOCH + Duration::from_secs(86_399)),
            "23:59"
        );
    }
}
