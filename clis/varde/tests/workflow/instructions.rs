//! `instructions`: managed global instruction files and persisted targets.

use super::common;

use std::fs;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::path::{Path, PathBuf};
use std::process::Output;

struct Fixture {
    root: PathBuf,
    bin_dir: PathBuf,
    config_dir: PathBuf,
}

impl Fixture {
    fn new(tag: &str) -> Self {
        let root = common::temp_bundle(tag);
        let bin_dir = root.join("bin");
        let config_dir = root.join("isolated-config");
        fs::create_dir_all(&bin_dir).unwrap();
        let date = bin_dir.join("date");
        fs::write(&date, "#!/bin/sh\nprintf '09:41\\n'\n").unwrap();
        let mut permissions = fs::metadata(&date).unwrap().permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&date, permissions).unwrap();
        Self {
            root,
            bin_dir,
            config_dir,
        }
    }

    fn run(&self, args: &[String]) -> Output {
        let inherited_path = std::env::var_os("PATH").unwrap_or_default();
        let mut path = self.bin_dir.as_os_str().to_owned();
        path.push(":");
        path.push(inherited_path);
        let mut command = common::isolate_memory(&self.root);
        command.args(args).env("PATH", path).output().unwrap()
    }

    fn config_file(&self) -> PathBuf {
        self.config_dir.join("config.toml")
    }

    fn plans_dir(&self) -> PathBuf {
        self.root.join("memory-bank/working/plans")
    }

    fn now_dir(&self) -> PathBuf {
        self.root.join("memory-bank/working/plan-now")
    }

    fn write_plan(&self, directory: &str, frontmatter: &str) -> PathBuf {
        let plan = self.plans_dir().join(directory).join("plan.md");
        fs::create_dir_all(plan.parent().unwrap()).unwrap();
        fs::write(
            &plan,
            format!("---\ntype: plan\n{frontmatter}\n---\n# Plan\n"),
        )
        .unwrap();
        plan
    }

    fn run_now(&self, plan: &str, text: Option<&str>, flags: &[&str]) -> Output {
        let mut args = vec!["now".into(), plan.into()];
        if let Some(text) = text {
            args.push(text.into());
        }
        args.extend(flags.iter().map(|flag| (*flag).into()));
        self.run(&args)
    }
}

fn cli_args(parts: &[&str]) -> Vec<String> {
    parts.iter().map(|part| (*part).to_owned()).collect()
}

fn install_args(target: &Path) -> Vec<String> {
    vec![
        "instructions".into(),
        "install".into(),
        "--target".into(),
        target.to_string_lossy().into_owned(),
    ]
}

fn text(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn set_modified(path: &Path, modified: std::time::SystemTime) {
    let file = fs::OpenOptions::new().write(true).open(path).unwrap();
    file.set_times(fs::FileTimes::new().set_modified(modified))
        .unwrap();
}

fn write_block_count(content: &str) -> usize {
    content.matches("<!-- varde:start -->").count()
}

/// The orchestration preference lines of the managed block, before the Toz section.
fn preference_lines(content: &str) -> Vec<String> {
    content
        .split_once("<!-- varde:start -->\n")
        .expect("managed block")
        .1
        .split("## varde-toz (tool-output-zone)")
        .next()
        .unwrap()
        .trim_end()
        .lines()
        .filter(|line| !line.is_empty())
        .map(str::to_owned)
        .collect()
}

#[test]
fn install_appends_after_user_text_with_a_blank_line() {
    let fixture = Fixture::new("instructions-append");
    let target = fixture.root.join("AGENTS.md");
    fs::write(&target, "# User instructions\nKeep this text.\n").unwrap();

    let output = fixture.run(&install_args(&target));
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let content = fs::read_to_string(&target).unwrap();
    assert!(content.starts_with("# User instructions\nKeep this text.\n\n\n"));
    assert!(content.ends_with("<!-- varde:end -->\n"));
    assert_eq!(write_block_count(&content), 1, "{content}");
    assert!(content.contains(
        "Orchestration: you are the main agent, the session manager: talk to the user, launch one orchestrator per plan, relay decisions and approvals, keep session notes; do not explore or implement. Orchestrators run their plan's workers, reviewers, merges, sync, memory commits and `varde plan conclude`."
    ));
    assert!(
        content.contains("If you were launched with a bounded task, follow that brief instead.")
    );
    assert!(content.contains(&toz_note_block()));
}

#[test]
fn install_snippet_is_seven_preference_lines_with_role_caps() {
    let fixture = Fixture::new("instructions-preference-lines");
    let target = fixture.root.join("AGENTS.md");
    let output = fixture.run(&install_args(&target));
    assert!(output.status.success());

    let content = fs::read_to_string(target).unwrap();
    assert_eq!(
        preference_lines(&content),
        [
            "Orchestration: you are the main agent, the session manager: talk to the user, launch one orchestrator per plan, relay decisions and approvals, keep session notes; do not explore or implement. Orchestrators run their plan's workers, reviewers, merges, sync, memory commits and `varde plan conclude`.",
            "Route every change through `varde-change`.",
            "Role caps per orchestrator: 4 builders, 2 planners, 2 reviewers, 4 explorers; at most 4 orchestrators, one per plan.",
            "Orchestrators and workers report milestones with `varde msg send` to `main`; their final reply is one line. Main agent status format: details: varde-change `references/status.md`. On a wake-up or without the per-prompt hook, the main agent runs `varde msg read`.",
            "Update the hand-written session notes section when a rule is set or a decision opens or closes; tidy it at the nudge, before compaction, or on request, and never edit the generated block.",
            "Run `varde plan watch --stale 20m --notes <session notes path>` under your harness's monitor while orchestrators run; the session notes block shows plan state.",
            "If you were launched with a bounded task, follow that brief instead.",
        ]
    );
    assert!(
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../skills/varde-change/references/status.md")
            .is_file()
    );
}

#[test]
fn status_renders_nested_groups_drafts_and_matching_json_without_writing() {
    let fixture = Fixture::new("plan-status-nested");
    let group_dir = fixture.plans_dir().join("2026-10-07-example-group");
    let completed = group_dir.join("complete/plan.md");
    let draft = group_dir.join("draft/plan.md");
    let nested = group_dir.join("draft/nested/plan.md");
    fs::create_dir_all(completed.parent().unwrap()).unwrap();
    fs::create_dir_all(draft.parent().unwrap()).unwrap();
    fs::create_dir_all(nested.parent().unwrap()).unwrap();
    fs::write(
        group_dir.join("plan.md"),
        "---\ntype: plan\nshape: group\nstatus: active\ndepends_on: []\ntitle: Example Group\n---\n## Acceptance criteria\n- [ ] Child plans finish\n",
    )
    .unwrap();
    fs::write(
        &completed,
        "---\ntype: plan\nstatus: completed\ndepends_on: []\ntitle: Complete Child\n---\n## Acceptance criteria\n- [x] Done\n",
    )
    .unwrap();
    fs::write(
        &draft,
        "---\ntype: plan\nstatus: backlog\ndepends_on: []\ntitle: Draft Child\n---\n## Open Questions\n- Which approach should we use?\n\n## Acceptance criteria\n- [ ] Decide\n",
    )
    .unwrap();
    fs::write(
        &nested,
        "---\ntype: plan\nstatus: active\ndepends_on: []\n---\n## Acceptance criteria\n- [ ] Work\n",
    )
    .unwrap();
    let original = fs::read(&draft).unwrap();

    let output = fixture.run(&cli_args(&["status"]));
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let rendered = text(&output);
    assert_eq!(
        rendered,
        "**Progress** 09:41\n1. 2026-10-07-example-group (group) 1/2 plans: active\n   - 1a. draft (group) 0/1 plans: backlog\n      - 1aa. nested: no tasks yet\n"
    );
    assert!(!rendered.contains('|'));
    assert_eq!(fs::read(draft).unwrap(), original);

    let output = fixture.run(&cli_args(&["status", "--json"]));
    assert!(output.status.success());
    let data = common::json_data(&output.stdout);
    assert_eq!(data["plans"][0]["id"], "2026-10-07-example-group");
    assert_eq!(data["plans"][0]["done"], 1);
    assert_eq!(data["plans"][0]["total"], 2);
    assert_eq!(data["plans"][0]["children"][0]["now"], "backlog");
    assert_eq!(
        data["plans"][0]["children"][0]["children"][0]["id"],
        "nested"
    );
    assert!(!rendered.contains('—'));
}

#[test]
fn now_set_replace_clear_and_status_use_the_external_line() {
    let fixture = Fixture::new("plan-now-lifecycle");
    let plan = fixture.write_plan("now-plan", "id: display-id\nstatus: active");
    let original_plan = fs::read(&plan).unwrap();

    let set = fixture.run_now(
        "display-id",
        Some("  inspect\tfiles\nthen run — now  "),
        &["--json"],
    );
    assert!(
        set.status.success(),
        "{}",
        String::from_utf8_lossy(&set.stderr)
    );
    let set_data = common::json_data(&set.stdout);
    assert_eq!(set_data["plan"], "display-id");
    assert_eq!(set_data["now"], "inspect files then run — now");

    let now_file = fixture.now_dir().join("now-plan.txt");
    assert_eq!(
        fs::read_to_string(&now_file).unwrap(),
        "inspect files then run — now\n"
    );
    assert_eq!(fs::read(&plan).unwrap(), original_plan);

    let json_status = fixture.run(&cli_args(&["status", "--json"]));
    assert!(json_status.status.success());
    let data = common::json_data(&json_status.stdout);
    assert_eq!(data["plans"][0]["now"], "inspect files then run - now");
    let cache = fixture
        .root
        .join("memory-bank/working/.cache/plan-status-last.txt");
    assert!(!cache.exists(), "--json must not create the status cache");

    let first_status = fixture.run(&cli_args(&["status"]));
    assert!(first_status.status.success());
    assert!(text(&first_status).contains("1. display-id: inspect files then run - now\n"));
    assert!(!text(&first_status).contains('—'));
    let repeated_status = fixture.run(&cli_args(&["status"]));
    assert!(text(&repeated_status).contains("no change since last check"));

    let long_line = "x".repeat(250);
    let path_argument = fixture
        .root
        .join("memory-bank/working/plans/now-plan/plan.md")
        .to_string_lossy()
        .into_owned();
    let replace = fixture.run_now(&path_argument, Some(&long_line), &[]);
    assert!(
        replace.status.success(),
        "{}",
        String::from_utf8_lossy(&replace.stderr)
    );
    assert!(text(&replace).contains("Set now line for display-id."));
    assert_eq!(
        fs::read_to_string(&now_file).unwrap(),
        format!("{}\n", "x".repeat(200))
    );

    let changed_status = fixture.run(&cli_args(&["status"]));
    assert!(changed_status.status.success());
    assert!(!text(&changed_status).contains("no change since last check"));
    assert!(text(&changed_status).contains(&format!("1. display-id: {}\n", "x".repeat(200))));

    let clear = fixture.run_now("display-id", None, &["--clear", "--json"]);
    assert!(
        clear.status.success(),
        "{}",
        String::from_utf8_lossy(&clear.stderr)
    );
    assert_eq!(common::json_data(&clear.stdout)["cleared"], true);
    assert!(!now_file.exists());
    let clear_missing = fixture.run_now("now-plan", None, &["--clear"]);
    assert!(
        clear_missing.status.success(),
        "{}",
        String::from_utf8_lossy(&clear_missing.stderr)
    );
    assert!(text(&clear_missing).contains("Cleared now line for display-id."));
    assert_eq!(fs::read(&plan).unwrap(), original_plan);

    let fallback = fixture.run(&cli_args(&["status"]));
    assert!(text(&fallback).contains("1. display-id: no tasks yet\n"));
}

#[test]
fn now_paths_and_ids_use_distinct_nested_keys() {
    let fixture = Fixture::new("plan-now-identities");
    let group = fixture.write_plan("top", "id: top-id\nstatus: active\nshape: group");
    let child = fixture.write_plan("top/child", "id: child-id\nstatus: active");
    let other_child = fixture.write_plan("top/other", "id: child-id\nstatus: active");
    fixture.write_plan("solo", "id: solo-id\nstatus: active");

    let relative_group_path = "memory-bank/working/plans/top/plan.md";
    let set_group = fixture.run_now(relative_group_path, Some("group by path"), &[]);
    assert!(
        set_group.status.success(),
        "{}",
        String::from_utf8_lossy(&set_group.stderr)
    );
    let replace_group = fixture.run_now("top", Some("group by directory"), &[]);
    assert!(
        replace_group.status.success(),
        "{}",
        String::from_utf8_lossy(&replace_group.stderr)
    );
    let set_child = fixture.run_now(&child.to_string_lossy(), Some("child by path"), &[]);
    assert!(
        set_child.status.success(),
        "{}",
        String::from_utf8_lossy(&set_child.stderr)
    );
    let set_other_child = fixture.run_now(
        &other_child.to_string_lossy(),
        Some("other child by path"),
        &[],
    );
    assert!(
        set_other_child.status.success(),
        "{}",
        String::from_utf8_lossy(&set_other_child.stderr)
    );
    let set_solo = fixture.run_now("solo-id", Some("frontmatter id"), &[]);
    assert!(
        set_solo.status.success(),
        "{}",
        String::from_utf8_lossy(&set_solo.stderr)
    );

    assert_eq!(
        fs::read_to_string(fixture.now_dir().join("top.txt")).unwrap(),
        "group by directory\n"
    );
    assert_eq!(
        fs::read_to_string(fixture.now_dir().join("top__child.txt")).unwrap(),
        "child by path\n"
    );
    assert_eq!(
        fs::read_to_string(fixture.now_dir().join("top__other.txt")).unwrap(),
        "other child by path\n"
    );
    assert_eq!(
        fs::read_to_string(fixture.now_dir().join("solo.txt")).unwrap(),
        "frontmatter id\n"
    );

    let nested = fixture.write_plan("collision/child", "id: nested-id\nstatus: active");
    let flat = fixture.write_plan("collision__child", "id: flat-id\nstatus: active");
    let set_nested = fixture.run_now(&nested.to_string_lossy(), Some("nested"), &[]);
    let set_flat = fixture.run_now(&flat.to_string_lossy(), Some("flat"), &[]);
    assert!(set_nested.status.success());
    assert!(set_flat.status.success());
    assert_eq!(
        fs::read_to_string(fixture.now_dir().join("collision__child.txt")).unwrap(),
        "nested\n"
    );
    assert_eq!(
        fs::read_to_string(fixture.now_dir().join("collision_u_uchild.txt")).unwrap(),
        "flat\n"
    );

    let ambiguous = fixture.run_now("child-id", Some("ambiguous"), &[]);
    assert!(!ambiguous.status.success());
    assert!(String::from_utf8_lossy(&ambiguous.stderr).contains("ambiguous"));
    assert!(fs::read(&group).is_ok());
}

#[test]
fn now_rejects_unsafe_keys_unknown_ids_and_paths_outside_plans() {
    let fixture = Fixture::new("plan-now-rejections");
    let unsafe_plan = fixture.write_plan("bad!key", "status: active");
    let unsafe_key = fixture.run_now(
        &unsafe_plan.to_string_lossy(),
        Some("must not be written"),
        &[],
    );
    assert!(!unsafe_key.status.success());
    assert!(String::from_utf8_lossy(&unsafe_key.stderr).contains("unsafe key component"));
    assert!(!fixture.now_dir().exists());

    let outside = fixture.root.join("outside/plan.md");
    fs::create_dir_all(outside.parent().unwrap()).unwrap();
    fs::write(&outside, "---\ntype: plan\nstatus: active\n---\n").unwrap();
    let outside_path = fixture.run_now(&outside.to_string_lossy(), Some("unsafe"), &[]);
    assert!(!outside_path.status.success());
    assert!(String::from_utf8_lossy(&outside_path.stderr).contains("inside"));

    let unknown = fixture.run_now("../outside", Some("unsafe"), &[]);
    assert!(!unknown.status.success());
    assert!(String::from_utf8_lossy(&unknown.stderr).contains("unknown plan"));

    let missing_text = fixture.run(&cli_args(&["now", "bad!key"]));
    assert!(!missing_text.status.success());
    let conflicting = fixture.run_now("bad!key", Some("line"), &["--clear"]);
    assert!(!conflicting.status.success());
}

#[test]
fn status_falls_back_for_empty_and_unreadable_now_files_and_hides_terminal_plans() {
    let fixture = Fixture::new("plan-now-lenient-read");
    fixture.write_plan("empty", "status: active");
    fixture.write_plan("unreadable", "status: active");
    fixture.write_plan("terminal", "status: completed");
    fs::create_dir_all(fixture.now_dir()).unwrap();
    fs::write(fixture.now_dir().join("empty.txt"), "\n").unwrap();
    symlink(
        fixture.root.join("missing-now.txt"),
        fixture.now_dir().join("unreadable.txt"),
    )
    .unwrap();
    fs::write(fixture.now_dir().join("terminal.txt"), "stale line\n").unwrap();

    let output = fixture.run(&cli_args(&["status"]));
    assert!(output.status.success());
    let rendered = text(&output);
    assert!(rendered.contains("1. empty: no tasks yet\n"));
    assert!(rendered.contains("2. unreadable: no tasks yet\n"));
    assert!(!rendered.contains("terminal"));
    assert!(!rendered.contains("Skipped"));
    assert!(fixture.now_dir().join("terminal.txt").exists());
}

#[test]
fn status_shows_only_five_top_level_plans_and_counts_the_rest() {
    let fixture = Fixture::new("plan-status-limit");
    for index in 1..=6 {
        let plan = fixture
            .plans_dir()
            .join(format!("2026-10-0{index}-plan-{index}/plan.md"));
        fs::create_dir_all(plan.parent().unwrap()).unwrap();
        let status = if index == 2 { "backlog" } else { "active" };
        fs::write(
            plan,
            format!("---\ntype: plan\nstatus: {status}\ndepends_on: []\n---\n## Acceptance criteria\n- [ ] Work\n"),
        )
        .unwrap();
    }
    let tasks_dir = fixture.plans_dir().join("2026-10-06-plan-6/tasks");
    fs::create_dir_all(&tasks_dir).unwrap();
    fs::write(
        tasks_dir.join("complete.md"),
        "---\ntype: task\nstatus: done\ndepends_on: []\n---\n",
    )
    .unwrap();
    fs::write(
        tasks_dir.join("current.md"),
        "---\ntype: task\nstatus: in_progress\ntitle: Build — current\ndepends_on: []\n---\n",
    )
    .unwrap();

    let output = fixture.run(&cli_args(&["status"]));
    assert!(output.status.success());
    let rendered = text(&output);
    assert!(rendered.contains("1. 2026-10-06-plan-6 1/2: Build - current in progress"));
    assert!(rendered.contains("5. 2026-10-01-plan-1: no tasks yet"));
    assert!(rendered.ends_with("+1 backlog\n"));
    assert!(!rendered.contains("2026-10-02-plan-2"));
}

#[test]
fn status_limits_each_nested_group_and_keeps_full_child_totals() {
    let fixture = Fixture::new("plan-status-nested-limit");
    let group_dir = fixture.plans_dir().join("2026-10-07-example-group");
    fs::create_dir_all(&group_dir).unwrap();
    fs::write(
        group_dir.join("plan.md"),
        "---\ntype: plan\nshape: group\nstatus: active\ndepends_on: []\n---\n## Acceptance criteria\n- [ ] Child plans finish\n",
    )
    .unwrap();
    for index in 1..=7 {
        let child = group_dir.join(format!("child-{index}/plan.md"));
        fs::create_dir_all(child.parent().unwrap()).unwrap();
        let status = if index == 1 { "completed" } else { "active" };
        fs::write(
            child,
            format!("---\ntype: plan\nstatus: {status}\ndepends_on: []\n---\n## Acceptance criteria\n- [ ] Work\n"),
        )
        .unwrap();
    }

    let output = fixture.run(&cli_args(&["status"]));
    assert!(output.status.success());
    let rendered = text(&output);
    assert!(rendered.contains("1. 2026-10-07-example-group (group) 1/7 plans: active"));
    assert!(rendered.contains("- 1a. child-2: no tasks yet"));
    assert!(rendered.contains("- 1e. child-6: no tasks yet"));
    assert!(rendered.ends_with("   +1 more\n"));
    assert!(!rendered.contains("child-7"));

    let output = fixture.run(&cli_args(&["status", "--json"]));
    assert!(output.status.success());
    let data = common::json_data(&output.stdout);
    assert_eq!(data["plans"][0]["total"], 7);
    assert_eq!(data["plans"][0]["children"].as_array().unwrap().len(), 5);
    assert_eq!(data["plans"][0]["more_count"], 1);
}

#[test]
fn status_uses_default_and_warns_for_invalid_stall_minutes_without_writing() {
    let fixture = Fixture::new("plan-status-invalid-stall-minutes");
    fs::create_dir_all(&fixture.config_dir).unwrap();
    let config = "[orchestration]\nstall_minutes = 0\n";
    fs::write(fixture.config_file(), config).unwrap();

    let output = fixture.run(&cli_args(&["status"]));
    assert!(output.status.success());
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("0 is not a positive integer"),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(text(&output).contains("No plans in a non-terminal status."));
    assert_eq!(fs::read_to_string(fixture.config_file()).unwrap(), config);
}

#[test]
fn status_marks_stale_tasks_and_resets_for_activity() {
    let fixture = Fixture::new("plan-status-stall-detection");
    let plan_dir = fixture.plans_dir().join("2026-10-07-stall-plan");
    let plan = plan_dir.join("plan.md");
    let task = plan_dir.join("tasks/stall.md");
    fs::create_dir_all(task.parent().unwrap()).unwrap();
    fs::write(
        &plan,
        "---\ntype: plan\nstatus: active\ndepends_on: []\ntitle: Stall plan\n---\n## Acceptance criteria\n- [ ] Task is checked\n",
    )
    .unwrap();
    fs::write(
        &task,
        "---\ntype: task\nid: stall\nstatus: in_progress\ndepends_on: []\ntitle: Slow task\nmodifies:\n  - src/feature.rs\ncreates: []\nrenames: []\nverification_resources: []\n---\n## Progress\n- 2000-01-01: Waiting\n",
    )
    .unwrap();

    let stale_time = std::time::SystemTime::now() - std::time::Duration::from_secs(10 * 60);
    set_modified(&task, stale_time);
    fs::create_dir_all(&fixture.config_dir).unwrap();
    fs::write(
        fixture.config_file(),
        "[orchestration]\nstall_minutes = 20\n",
    )
    .unwrap();
    let below_threshold = fixture.run(&cli_args(&["status"]));
    assert!(below_threshold.status.success());
    assert!(!text(&below_threshold).contains("stalled"));

    fs::write(
        fixture.config_file(),
        "[orchestration]\nstall_minutes = 5\n",
    )
    .unwrap();
    let stale = fixture.run(&cli_args(&["status"]));
    assert!(stale.status.success());
    assert!(text(&stale).contains("Slow task in progress stalled "));
    let stale_json = fixture.run(&cli_args(&["status", "--json"]));
    assert!(stale_json.status.success());
    let stale_data = common::json_data(&stale_json.stdout);
    let stale_now = stale_data["plans"][0]["now"].as_str().unwrap();
    assert!(stale_now.starts_with("Slow task in progress stalled "));
    assert!(text(&stale).contains(stale_now));

    let note = plan_dir.join("notes/stall.md");
    fs::create_dir_all(note.parent().unwrap()).unwrap();
    fs::write(&note, "## Progress\n- Worker is active.\n").unwrap();
    let noted = fixture.run(&cli_args(&["status"]));
    assert!(noted.status.success());
    assert!(!text(&noted).contains("stalled"));
}

#[test]
fn install_creates_new_target_with_a_final_newline() {
    let fixture = Fixture::new("instructions-new-target");
    let target = fixture.root.join("AGENTS.md");

    let output = fixture.run(&install_args(&target));
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let content = fs::read(&target).unwrap();
    assert!(content.ends_with(b"<!-- varde:end -->\n"));
}

#[test]
fn install_replaces_the_block_in_place_and_preserves_surrounding_bytes() {
    let fixture = Fixture::new("instructions-replace");
    let target = fixture.root.join("AGENTS.md");
    let prefix = b"before\n\n";
    let old_block = b"<!-- varde:start -->\nold body\n<!-- varde:end -->";
    let suffix = b"\n\nafter\n";
    let mut original = prefix.to_vec();
    original.extend_from_slice(old_block);
    original.extend_from_slice(suffix);
    fs::write(&target, &original).unwrap();

    let output = fixture.run(&install_args(&target));
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let updated = fs::read(&target).unwrap();
    assert!(updated.starts_with(prefix));
    assert!(updated.ends_with(suffix));
    let content = String::from_utf8_lossy(&updated);
    assert_eq!(write_block_count(&content), 1, "{content}");
    assert!(!content.contains("old body"));
}

#[test]
fn symlink_targets_are_deduplicated_and_writes_keep_the_link() {
    let fixture = Fixture::new("instructions-symlink");
    let real = fixture.root.join("canonical.md");
    let link = fixture.root.join("AGENTS.md");
    fs::write(&real, "# Shared instructions\n").unwrap();
    symlink(&real, &link).unwrap();
    let args = vec![
        "instructions".into(),
        "install".into(),
        "--target".into(),
        link.to_string_lossy().into_owned(),
        "--target".into(),
        real.to_string_lossy().into_owned(),
    ];

    let output = fixture.run(&args);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        fs::symlink_metadata(&link)
            .unwrap()
            .file_type()
            .is_symlink()
    );
    let content = fs::read_to_string(&real).unwrap();
    assert_eq!(write_block_count(&content), 1, "{content}");
    let configured = fs::read_to_string(fixture.config_file()).unwrap();
    assert!(configured.contains(&link.to_string_lossy().to_string()));
    assert!(!configured.contains(&real.to_string_lossy().to_string()));
}

#[test]
fn remove_restores_user_file_bytes_after_an_append() {
    let cases: [(&str, &[u8], bool); 4] = [
        ("instructions-remove-empty", b"", false),
        (
            "instructions-remove-with-newline",
            b"# User instructions\n",
            false,
        ),
        (
            "instructions-remove-without-newline",
            b"# User instructions",
            false,
        ),
        (
            "instructions-remove-editor-newline",
            b"# User instructions\n",
            true,
        ),
    ];
    for (tag, original, add_newline_after_block) in cases {
        let fixture = Fixture::new(tag);
        let target = fixture.root.join("AGENTS.md");
        let mut initial = original.to_vec();
        if add_newline_after_block {
            initial.extend_from_slice(
                b"\n\n<!-- varde:start -->\nold managed text\n<!-- varde:end -->",
            );
        }
        fs::write(&target, initial).unwrap();

        let installed = fixture.run(&install_args(&target));
        assert!(
            installed.status.success(),
            "{}",
            String::from_utf8_lossy(&installed.stderr)
        );
        if add_newline_after_block {
            let mut edited = fs::read(&target).unwrap();
            edited.push(b'\n');
            fs::write(&target, edited).unwrap();
        }

        let removed = fixture.run(&cli_args(&["instructions", "remove"]));
        assert!(
            removed.status.success(),
            "{}",
            String::from_utf8_lossy(&removed.stderr)
        );
        assert_eq!(fs::read(&target).unwrap(), original, "{tag}");
    }
}

#[test]
fn remove_clears_targets_and_keeps_other_config_values() {
    let fixture = Fixture::new("instructions-remove-targets");
    let target = fixture.root.join("AGENTS.md");
    fs::write(
        &target,
        "User text\n\n\n<!-- varde:start -->\nmanaged\n<!-- varde:end -->\n",
    )
    .unwrap();
    fs::create_dir_all(&fixture.config_dir).unwrap();
    fs::write(
        fixture.config_file(),
        format!(
            "[orchestration]\nmax_agents = 2\n\n[instructions]\ntargets = [\"{}\"]\n\n[custom]\nkeep = \"yes\"\n",
            target.display()
        ),
    )
    .unwrap();

    let removed = fixture.run(&cli_args(&["instructions", "remove"]));
    assert!(
        removed.status.success(),
        "{}",
        String::from_utf8_lossy(&removed.stderr)
    );
    assert_eq!(fs::read(&target).unwrap(), b"User text\n");
    let config = fs::read_to_string(fixture.config_file()).unwrap();
    assert!(!config.contains("targets ="), "{config}");
    assert!(config.contains("max_agents = 2"), "{config}");
    assert!(config.contains("keep = \"yes\""), "{config}");
}

#[test]
fn install_without_targets_prints_the_setup_warning_and_targets_is_empty() {
    let fixture = Fixture::new("instructions-no-targets");
    let output = fixture.run(&cli_args(&["instructions", "install"]));
    assert!(output.status.success());
    assert!(text(&output).contains("Varde will not work as designed"));
    assert!(text(&output).contains("varde setup instructions install --target <file>"));

    let targets = fixture.run(&cli_args(&["instructions", "targets"]));
    assert!(targets.status.success());
    assert!(targets.stdout.is_empty());
}

#[test]
fn read_only_target_warns_and_prints_the_block_without_failing() {
    let fixture = Fixture::new("instructions-read-only");
    let target = fixture.root.join("readonly.md");
    fs::write(&target, "# Read only\n").unwrap();
    fs::set_permissions(&target, fs::Permissions::from_mode(0o444)).unwrap();

    let output = fixture.run(&install_args(&target));
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains("<!-- varde:start -->"));
    assert!(String::from_utf8_lossy(&output.stderr).contains("could not write"));
    assert_eq!(fs::read_to_string(target).unwrap(), "# Read only\n");
}

#[test]
fn max_agents_is_persisted_and_rendered() {
    let fixture = Fixture::new("instructions-builders");
    let target = fixture.root.join("AGENTS.md");
    let mut args = install_args(&target);
    args.extend(["--builders".into(), "2".into()]);

    let output = fixture.run(&args);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let config = fs::read_to_string(fixture.config_file()).unwrap();
    assert!(config.contains("builders = 2"), "{config}");
    assert!(!config.contains("max_agents"), "{config}");
    assert!(config.contains("[instructions]"), "{config}");
    assert!(
        fs::read_to_string(target)
            .unwrap()
            .contains("Role caps per orchestrator: 2 builders, 2 planners, 2 reviewers, 4 explorers; at most 4 orchestrators, one per plan.")
    );
}

#[test]
fn invalid_max_agents_exits_nonzero_without_writing_config_or_target() {
    let fixture = Fixture::new("instructions-invalid-builders");
    let target = fixture.root.join("AGENTS.md");
    let mut args = install_args(&target);
    args.extend(["--builders".into(), "0".into()]);

    let output = fixture.run(&args);
    assert!(!output.status.success());
    assert!(!target.exists());
    assert!(!fixture.config_file().exists());
}

#[test]
fn invalid_configured_max_agents_warns_and_uses_four() {
    let fixture = Fixture::new("instructions-invalid-configured-builders");
    let target = fixture.root.join("AGENTS.md");
    fs::create_dir_all(&fixture.config_dir).unwrap();
    fs::write(fixture.config_file(), "[orchestration]\nmax_agents = 0\n").unwrap();

    let output = fixture.run(&install_args(&target));
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("0 is not a positive integer"),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        fs::read_to_string(target)
            .unwrap()
            .contains("Role caps per orchestrator: 4 builders, 2 planners, 2 reviewers, 4 explorers; at most 4 orchestrators, one per plan.")
    );
}

/// The Toz section the instruction block embeds: a heading over the shared note.
fn toz_note_block() -> String {
    format!(
        "## varde-toz (tool-output-zone)\n\n{}",
        varde_core::TOZ_NOTE
    )
}

#[test]
fn toz_note_is_always_included() {
    let fixture = Fixture::new("instructions-toz-always");
    let target = fixture.root.join("AGENTS.md");
    let output = fixture.run(&install_args(&target));
    assert!(output.status.success());
    let content = fs::read_to_string(target).unwrap();
    let block = toz_note_block();
    assert!(
        block.starts_with("## varde-toz (tool-output-zone)"),
        "{block}"
    );
    assert!(content.contains(&block), "{content}");
}

#[test]
fn install_renders_only_requested_sections() {
    for (sections, orchestration, toz, learn) in [
        ("orchestration", true, false, false),
        ("toz", false, true, false),
        ("learn", false, false, true),
        ("orchestration,toz,learn", true, true, true),
    ] {
        let fixture = Fixture::new("instructions-sections");
        let target = fixture.root.join("AGENTS.md");
        let mut args = install_args(&target);
        args.extend(["--sections".into(), sections.into()]);
        let output = fixture.run(&args);
        assert!(output.status.success(), "{}", text(&output));
        let content = fs::read_to_string(target).unwrap();
        assert_eq!(
            content.contains("the session manager"),
            orchestration,
            "{sections}"
        );
        assert_eq!(
            content.contains("## varde-toz (tool-output-zone)"),
            toz,
            "{sections}"
        );
        assert_eq!(
            content.contains("<!-- varde-learn:start -->"),
            learn,
            "{sections}"
        );
    }
}

#[test]
fn targets_prints_persisted_absolute_paths() {
    let fixture = Fixture::new("instructions-targets");
    let target = fixture.root.join("AGENTS.md");
    let empty = fixture.run(&cli_args(&["instructions", "targets"]));
    assert!(empty.status.success());
    assert!(empty.stdout.is_empty());

    let installed = fixture.run(&install_args(&target));
    assert!(installed.status.success());
    let output = fixture.run(&cli_args(&["instructions", "targets"]));
    assert!(output.status.success());
    assert_eq!(text(&output), format!("{}\n", target.display()));
}

#[test]
fn legacy_toz_blocks_emit_the_migration_warning() {
    let fixture = Fixture::new("instructions-legacy-toz");
    let target = fixture.root.join("AGENTS.md");
    fs::write(
        &target,
        "# Existing\n\n<!-- varde-toz:start -->\nlegacy\n<!-- varde-toz:end -->\n",
    )
    .unwrap();

    let output = fixture.run(&install_args(&target));
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("varde setup sync"));
}

#[test]
fn missing_parent_write_error_warns_and_prints_the_block() {
    let fixture = Fixture::new("instructions-missing-parent");
    let target = fixture.root.join("missing-parent").join("AGENTS.md");

    let output = fixture.run(&install_args(&target));
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("could not write"));
    assert!(String::from_utf8_lossy(&output.stdout).contains("<!-- varde:start -->"));
    assert!(!target.exists());
}

#[test]
fn install_dry_run_prints_only_target_and_block_without_writing() {
    let fixture = Fixture::new("instructions-dry-run");
    let target = fixture.root.join("AGENTS.md");
    fs::write(&target, "Private target content\n").unwrap();
    let mut args = install_args(&target);
    args.push("--dry-run".into());

    let output = fixture.run(&args);
    assert!(output.status.success());
    assert!(text(&output).contains("would write the Varde instruction block"));
    assert!(text(&output).contains(&target.display().to_string()));
    assert!(text(&output).contains("<!-- varde:start -->"));
    assert!(!text(&output).contains("Private target content"));
    assert_eq!(
        fs::read_to_string(target).unwrap(),
        "Private target content\n"
    );
    assert!(!fixture.config_file().exists());
}
