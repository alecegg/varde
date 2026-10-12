//! End-to-end `plan watch --once` and `plan now --waiting` scenarios.
//!
//! The crate has no binary, so each scenario re-runs this test executable with
//! `child_entry` selected; the child calls `varde_workflow::run` and exits with
//! the CLI's code.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::time::{Duration, SystemTime};
use varde_workflow_core::memory::{
    LEGACY_HANDOFF_FILE, LEGACY_HANDOFFS_DIR, NOTES_FILE, SESSION_NOTES_DIR,
};

const ARGS_ENV: &str = "PLAN_WATCH_TEST_ARGS";
const BEGIN: &str = "<<<plan-watch-test-begin>>>";
const END: &str = "<<<plan-watch-test-end>>>";
const BLOCK_BEGIN: &str = "<!-- varde:plan-status:begin -->";
const BLOCK_END: &str = "<!-- varde:plan-status:end -->";

#[test]
fn child_entry() {
    let Ok(joined) = std::env::var(ARGS_ENV) else {
        return;
    };
    let mut args = vec!["varde-workflow".into()];
    args.extend(joined.split('\u{1f}').map(Into::into));
    println!("{BEGIN}");
    let code = varde_workflow::run(args, &varde_contracts::Io::default());
    println!("{END}");
    std::process::exit(i32::from(
        format!("{code:?}") != format!("{:?}", ExitCode::SUCCESS),
    ));
}

struct Store {
    root: PathBuf,
}

struct Run {
    success: bool,
    stdout: String,
    stderr: String,
}

impl Store {
    fn new(label: &str) -> Self {
        let root =
            std::env::temp_dir().join(format!("varde-plan-watch-{label}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("repo")).unwrap();
        let status = Command::new("git")
            .arg("-C")
            .arg(root.join("repo"))
            .args(["init", "-q"])
            .status()
            .unwrap();
        assert!(status.success());
        Store { root }
    }

    fn working(&self) -> PathBuf {
        self.root.join("working")
    }

    fn plan(&self, directory: &str, frontmatter: &str) -> PathBuf {
        let plan = self.working().join("plans").join(directory).join("plan.md");
        fs::create_dir_all(plan.parent().unwrap()).unwrap();
        fs::write(
            &plan,
            format!("---\ntype: plan\n{frontmatter}\n---\n\nbody\n"),
        )
        .unwrap();
        plan
    }

    fn run(&self, args: &[&str]) -> Run {
        self.run_with_env(args, None)
    }

    fn run_with_env(&self, args: &[&str], extra: Option<(&str, &str)>) -> Run {
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                "plan_watch::child_entry",
                "--nocapture",
                "--test-threads=1",
            ])
            .env(ARGS_ENV, args.join("\u{1f}"))
            .env("HOME", &self.root)
            .env("VARDE_CONFIG_DIR", self.root.join("config"))
            .env("VARDE_WORKING_DIR", self.working())
            .env("VARDE_KNOWLEDGE_DIR", self.root.join("knowledge"))
            .env("VARDE_LEARN_STORE", self.root.join("learn"))
            .current_dir(self.root.join("repo"));
        if let Some((key, value)) = extra {
            command.env(key, value);
        }
        let output = command.output().unwrap();
        let stdout = String::from_utf8_lossy(&output.stdout);
        let stdout = stdout
            .split_once(BEGIN)
            .and_then(|(_, rest)| rest.split_once(END))
            .map(|(body, _)| body.trim().to_string())
            .unwrap_or_default();
        Run {
            success: output.status.success(),
            stdout,
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        }
    }
}

fn inbox_lines(store: &Store) -> Vec<serde_json::Value> {
    let path = store.working().join(".cache/inbox/messages.jsonl");
    fs::read_to_string(path)
        .unwrap_or_default()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

impl Drop for Store {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn backdate(plan: &Path, age: Duration) {
    let at = SystemTime::now() - age;
    let directory = plan.parent().unwrap();
    for path in [plan, directory] {
        fs::File::options()
            .read(true)
            .open(path)
            .unwrap()
            .set_modified(at)
            .unwrap();
    }
}

fn repo_arg(store: &Store) -> String {
    store.root.join("repo").display().to_string()
}

#[test]
fn once_prints_stale_for_an_idle_plan() {
    let store = Store::new("stale");
    let plan = store.plan("2026-10-10-idle", "status: active");
    backdate(&plan, Duration::from_secs(2 * 3600));
    let inbox = store.working().join(".cache/inbox/messages.jsonl");
    fs::create_dir_all(inbox.parent().unwrap()).unwrap();
    fs::write(
        inbox,
        format!(
            "{}\n",
            serde_json::json!({
                "ts": "9999-12-31T23:59:59Z",
                "from": "2026-10-10-idle",
                "to": "main",
                "kind": "info",
                "text": "handed back"
            })
        ),
    )
    .unwrap();

    let run = store.run(&[
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
    ]);

    assert!(run.success, "{}", run.stderr);
    assert!(
        run.stdout
            .lines()
            .any(|line| line.starts_with("stale 2026-10-10-idle ")),
        "{}",
        run.stdout
    );
}

#[test]
fn watch_idle_emits_once_and_marks_session_notes_without_touching_inbox_cursor() {
    let store = Store::new("idle-no-handback");
    let plan = store.plan("2026-10-10-idle", "status: active");
    backdate(&plan, Duration::from_secs(2 * 3600));
    let notes = store.root.join("session-notes.md");
    let cursor_dir = store.working().join(".cache/inbox/cursors");
    fs::create_dir_all(&cursor_dir).unwrap();
    let cursor = cursor_dir.join("2026-10-10-idle");
    fs::write(&cursor, b"17").unwrap();
    let args = [
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
        "--notes",
        notes.to_str().unwrap(),
    ];

    let first = store.run(&args);
    assert!(first.success, "{}", first.stderr);
    assert!(
        first
            .stdout
            .lines()
            .any(|line| line.starts_with("idle-no-handback 2026-10-10-idle ")),
        "{}",
        first.stdout
    );
    assert!(
        fs::read_to_string(&notes)
            .unwrap()
            .contains("idle-no-handback")
    );
    assert_eq!(fs::read(&cursor).unwrap(), b"17");

    let second = store.run(&args);
    assert!(second.success, "{}", second.stderr);
    assert!(
        !second.stdout.contains("idle-no-handback"),
        "{}",
        second.stdout
    );
    fs::remove_dir_all(&store.root).unwrap();
}

#[test]
fn once_appends_event_kinds_and_repeat_once_is_quiet() {
    let store = Store::new("inbox-kinds");
    let stale = store.plan("stale", "status: active");
    backdate(&stale, Duration::from_secs(2 * 3600));
    store.plan("blocked", "status: blocked");
    let decision = store.plan("decision", "status: active");
    fs::write(
        &decision,
        "---\ntype: plan\nstatus: active\n---\n\n## Open Questions\n\n- choose one\n",
    )
    .unwrap();
    let ready = store.plan("ready", "status: active");
    let task = ready.parent().unwrap().join("tasks/finished.md");
    fs::create_dir_all(task.parent().unwrap()).unwrap();
    fs::write(task, "---\ntype: task\nstatus: done\n---\nfinished\n").unwrap();
    let finished = store.plan("finished", "status: done");
    let _ = finished;

    let args = [
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
    ];
    let first = store.run(&args);
    assert!(first.success, "{}", first.stderr);
    let messages = inbox_lines(&store);
    let kinds = messages
        .iter()
        .map(|message| message["kind"].as_str().unwrap())
        .collect::<Vec<_>>();
    assert!(kinds.contains(&"stale"), "{kinds:?}");
    assert!(kinds.contains(&"blocked"), "{kinds:?}");
    assert!(kinds.contains(&"needs-user"), "{kinds:?}");
    assert!(kinds.contains(&"merge-ready"), "{kinds:?}");
    assert!(kinds.contains(&"done"), "{kinds:?}");
    assert!(
        messages
            .iter()
            .all(|message| message["to"] == "main" && message["from"] == "varde-watch")
    );
    let count = messages.len();
    let second = store.run(&args);
    assert!(second.success, "{}", second.stderr);
    assert_eq!(inbox_lines(&store).len(), count);
}

#[test]
fn no_inbox_keeps_print_everything_once() {
    let store = Store::new("no-inbox");
    let plan = store.plan("idle", "status: active");
    backdate(&plan, Duration::from_secs(2 * 3600));
    let run = store.run(&[
        "watch",
        "--once",
        "--no-inbox",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
    ]);
    assert!(run.success, "{}", run.stderr);
    assert!(run.stdout.contains("idle-no-handback idle"), "{}", run.stdout);
    assert!(inbox_lines(&store).is_empty());
}

#[test]
fn crash_before_cache_save_replays_one_inbox_line() {
    let store = Store::new("replay");
    let plan = store.plan("idle", "status: active");
    backdate(&plan, Duration::from_secs(2 * 3600));
    let args = [
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
    ];
    let failed = store.run_with_env(&args, Some(("VARDE_WATCH_FAIL_BEFORE_CACHE_SAVE", "1")));
    assert!(
        !failed.success,
        "failure injection should interrupt before cache save"
    );
    assert_eq!(inbox_lines(&store).len(), 1);
    let replay = store.run(&args);
    assert!(replay.success, "{}", replay.stderr);
    assert_eq!(inbox_lines(&store).len(), 2);
}

#[test]
fn event_text_is_truncated_to_the_inbox_limit() {
    let store = Store::new("long-detail");
    let long_id = "p".repeat(250);
    let plan = store.plan("long-detail", "status: active");
    fs::write(
        &plan,
        format!("---\ntype: plan\nid: {long_id}\nstatus: active\n---\n\nbody\n"),
    )
    .unwrap();
    backdate(&plan, Duration::from_secs(2 * 3600));
    let run = store.run(&[
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
    ]);
    assert!(run.success, "{}", run.stderr);
    let messages = inbox_lines(&store);
    assert_eq!(messages.len(), 1);
    assert!(messages[0]["text"].as_str().unwrap().chars().count() <= 300);
}

#[test]
fn non_ascii_event_fits_atomic_inbox_line_limit() {
    let store = Store::new("long-unicode");
    let plan = store.plan(
        "long-unicode",
        &format!("status: active\ntitle: {}", "界".repeat(300)),
    );
    backdate(&plan, Duration::from_secs(2 * 3600));
    let run = store.run(&[
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
    ]);
    assert!(run.success, "{}", run.stderr);
    let raw = fs::read(store.working().join(".cache/inbox/messages.jsonl")).unwrap();
    assert!(raw.len() <= 1_000);
    assert_eq!(inbox_lines(&store).len(), 1);
}

#[test]
fn msg_send_rejects_newlines_and_overlong_text() {
    let store = Store::new("strict-msg-send");
    let newline = store.run(&[
        "msg", "send", "--from", "a", "--to", "main", "--kind", "info", "--text", "a\nb",
    ]);
    assert!(!newline.success);
    let long = "x".repeat(301);
    let overlong = store.run(&[
        "msg", "send", "--from", "a", "--to", "main", "--kind", "info", "--text", &long,
    ]);
    assert!(!overlong.success);
    assert!(inbox_lines(&store).is_empty());
}

#[test]
fn repo_caches_are_separate_and_leftover_lock_files_do_not_block() {
    let store = Store::new("repo-cache");
    let plan = store.plan("idle", "status: active");
    backdate(&plan, Duration::from_secs(2 * 3600));
    let other_repo = store.root.join("other-repo");
    fs::create_dir_all(&other_repo).unwrap();
    assert!(
        Command::new("git")
            .arg("-C")
            .arg(&other_repo)
            .args(["init", "-q"])
            .status()
            .unwrap()
            .success()
    );

    let first = store.run(&[
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
    ]);
    assert!(first.success, "{}", first.stderr);
    let second = store.run(&[
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        other_repo.to_str().unwrap(),
    ]);
    assert!(second.success, "{}", second.stderr);
    assert_eq!(inbox_lines(&store).len(), 2);

    let lock_file = fs::read_dir(store.working().join(".cache"))
        .unwrap()
        .flatten()
        .map(|entry| entry.path())
        .find(|path| {
            path.extension()
                .is_some_and(|extension| extension == "lock")
        })
        .unwrap();
    fs::write(lock_file, "left over after process exit").unwrap();
    let after_exit = store.run(&[
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
    ]);
    assert!(after_exit.success, "{}", after_exit.stderr);
}

#[test]
fn a_second_watcher_exits_while_the_first_holds_the_lock() {
    let store = Store::new("live-lock");
    store.plan("active", "status: active");
    let mut holder = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "plan_watch::child_entry",
            "--nocapture",
            "--test-threads=1",
        ])
        .env(
            ARGS_ENV,
            ["watch", "--interval", "10s", "--repo", &repo_arg(&store)].join("\u{1f}"),
        )
        .env("HOME", &store.root)
        .env("VARDE_CONFIG_DIR", store.root.join("config"))
        .env("VARDE_WORKING_DIR", store.working())
        .env("VARDE_KNOWLEDGE_DIR", store.root.join("knowledge"))
        .env("VARDE_LEARN_STORE", store.root.join("learn"))
        .current_dir(store.root.join("repo"))
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .unwrap();
    std::thread::sleep(Duration::from_millis(250));
    let second = store.run(&["watch", "--once", "--repo", &repo_arg(&store)]);
    assert!(!second.success);
    assert!(
        second
            .stderr
            .contains("another varde plan watch is already running"),
        "{}",
        second.stderr
    );
    holder.kill().unwrap();
    holder.wait().unwrap();
}

#[test]
fn once_prints_json_events() {
    let store = Store::new("json");
    let plan = store.plan("2026-10-10-idle", "status: active");
    backdate(&plan, Duration::from_secs(2 * 3600));

    let run = store.run(&[
        "watch",
        "--once",
        "--stale",
        "1m",
        "--json",
        "--repo",
        &repo_arg(&store),
    ]);

    assert!(run.success, "{}", run.stderr);
    let event: serde_json::Value =
        serde_json::from_str(run.stdout.lines().next().unwrap()).unwrap();
    assert_eq!(event["kind"], "stale");
    assert_eq!(event["plan"], "2026-10-10-idle");
}

#[test]
fn waiting_now_line_suppresses_stale() {
    let store = Store::new("waiting");
    let plan = store.plan("2026-10-10-idle", "status: active");
    let set = store.run(&["now", "2026-10-10-idle", "--waiting", "review pending"]);
    assert!(set.success, "{}", set.stderr);
    backdate(&plan, Duration::from_secs(2 * 3600));
    let now_file = store.working().join("plan-now/2026-10-10-idle.txt");
    let stored = fs::read_to_string(&now_file).unwrap();
    assert_eq!(stored, "waiting: review pending\n");
    backdate(&now_file, Duration::from_secs(120));

    let run = store.run(&[
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
    ]);

    assert!(run.success, "{}", run.stderr);
    assert!(!run.stdout.contains("stale "), "{}", run.stdout);
}

#[test]
fn waiting_conflicts_with_clear_and_text() {
    let store = Store::new("conflict");
    store.plan("2026-10-10-idle", "status: active");

    let with_clear = store.run(&["now", "2026-10-10-idle", "--waiting", "x", "--clear"]);
    let with_text = store.run(&["now", "2026-10-10-idle", "note", "--waiting", "x"]);

    assert!(!with_clear.success);
    assert!(
        with_clear.stderr.contains("cannot be used with"),
        "{}",
        with_clear.stderr
    );
    assert!(!with_text.success);
    assert!(
        with_text.stderr.contains("cannot be used with"),
        "{}",
        with_text.stderr
    );
    assert!(!store.working().join("plan-now").exists());
}

#[test]
fn once_notes_updates_only_the_block_and_accepts_session_notes_type() {
    let store = Store::new("notes");
    let plan = store.plan("2026-10-10-idle", "status: active");
    backdate(&plan, Duration::from_secs(2 * 3600));
    let notes = store
        .working()
        .join(SESSION_NOTES_DIR)
        .join("2026-10-10-session")
        .join(NOTES_FILE);
    let before = format!(
        "---\ntype: session-notes\nstatus: open\n---\nhand-written rule\n\n{BLOCK_BEGIN}\nold\n{BLOCK_END}\n\ntrailing note\n"
    );
    fs::create_dir_all(notes.parent().unwrap()).unwrap();
    fs::write(&notes, &before).unwrap();

    let run = store.run(&[
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
        "--notes",
        &notes.display().to_string(),
    ]);

    assert!(run.success, "{}", run.stderr);
    assert!(
        !run.stderr.contains("--handoff is deprecated"),
        "{}",
        run.stderr
    );
    let after = fs::read_to_string(&notes).unwrap();
    let (head, rest) = after.split_once(BLOCK_BEGIN).unwrap();
    let (block, tail) = rest.split_once(BLOCK_END).unwrap();
    assert_eq!(head, before.split_once(BLOCK_BEGIN).unwrap().0);
    assert_eq!(tail, "\n\ntrailing note\n");
    assert!(block.contains("2026-10-10-idle [stale since "), "{block}");
    assert!(!block.contains("old"), "{block}");
}

#[test]
fn handoff_alias_updates_legacy_type_and_prints_deprecation() {
    let store = Store::new("legacy-handoff-alias");
    let plan = store.plan("2026-10-10-idle", "status: active");
    backdate(&plan, Duration::from_secs(2 * 3600));
    let handoff = store
        .working()
        .join(LEGACY_HANDOFFS_DIR)
        .join("2026-10-10-session")
        .join(LEGACY_HANDOFF_FILE);
    fs::create_dir_all(handoff.parent().unwrap()).unwrap();
    fs::write(
        &handoff,
        format!("---\ntype: handoff\nstatus: open\n---\n\n{BLOCK_BEGIN}\nold\n{BLOCK_END}\n"),
    )
    .unwrap();

    let run = store.run(&[
        "watch",
        "--once",
        "--stale",
        "1m",
        "--repo",
        &repo_arg(&store),
        "--handoff",
        &handoff.display().to_string(),
    ]);

    assert!(run.success, "{}", run.stderr);
    assert!(
        run.stderr
            .contains("varde plan watch: --handoff is deprecated; use --notes"),
        "{}",
        run.stderr
    );
    let after = fs::read_to_string(handoff).unwrap();
    assert!(after.starts_with("---\ntype: handoff\nstatus: open\n---\n"));
    assert!(after.contains("2026-10-10-idle [stale since "), "{after}");
}

#[test]
fn watch_help_shows_notes_and_hides_handoff_alias() {
    let mut command = varde_workflow::cli_command();
    let help = command
        .find_subcommand_mut("watch")
        .unwrap()
        .render_help()
        .to_string();

    assert!(help.contains("--notes"), "{help}");
    assert!(!help.contains("--handoff"), "{help}");
}
