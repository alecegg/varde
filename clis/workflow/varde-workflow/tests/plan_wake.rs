//! End-to-end tests for the user-configured plan wake command.

use sha1::Digest;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::time::{Duration, SystemTime};

const ARGS_ENV: &str = "PLAN_WAKE_TEST_ARGS";
const BEGIN: &str = "<<<plan-wake-test-begin>>>";
const END: &str = "<<<plan-wake-test-end>>>";

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
    fn new(name: &str) -> Self {
        let root =
            std::env::temp_dir().join(format!("varde-plan-wake-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("repo")).unwrap();
        assert!(
            Command::new("git")
                .arg("-C")
                .arg(root.join("repo"))
                .args(["init", "-q"])
                .status()
                .unwrap()
                .success()
        );
        Self { root }
    }
    fn working(&self) -> PathBuf {
        self.root.join("working")
    }
    fn plan(&self, owner: Option<&str>) -> PathBuf {
        self.plan_named("example", owner)
    }
    fn plan_named(&self, name: &str, owner: Option<&str>) -> PathBuf {
        let path = self.working().join("plans").join(name).join("plan.md");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        let owner = owner
            .map(|value| format!("owner: {value}\n"))
            .unwrap_or_default();
        fs::write(
            &path,
            format!("---\ntype: plan\nstatus: active\n{owner}---\n\nbody\n"),
        )
        .unwrap();
        fs::File::options()
            .read(true)
            .open(&path)
            .unwrap()
            .set_modified(SystemTime::now() - Duration::from_secs(3600))
            .unwrap();
        path
    }
    fn hostile_waiting_line(&self) {
        let path = self.working().join("plan-now/example.txt");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, format!("waiting: {}\u{0001}", "x".repeat(400))).unwrap();
        fs::File::options()
            .read(true)
            .open(&path)
            .unwrap()
            .set_modified(SystemTime::now() - Duration::from_secs(3600))
            .unwrap();
    }
    fn script(&self, body: &str) -> PathBuf {
        let path = self.root.join("fake-wake");
        fs::write(&path, format!("#!/bin/sh\nset -eu\n{body}\n")).unwrap();
        let mut permissions = fs::metadata(&path).unwrap().permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&path, permissions).unwrap();
        path
    }
    fn configure(&self, script: &Path, timeout: u64, failures: u32) {
        fs::create_dir_all(self.root.join("config")).unwrap();
        fs::write(self.root.join("config/config.toml"), format!("[orchestration]\nwake_command = [{}]\nwake_timeout_seconds = {timeout}\nwake_max_failures = {failures}\n", toml_quote(&script.display().to_string()))).unwrap();
    }
    fn run(&self, args: &[&str]) -> Run {
        let output = Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "plan_wake::child_entry",
                "--nocapture",
                "--test-threads=1",
            ])
            .env(ARGS_ENV, args.join("\u{1f}"))
            .env("HOME", &self.root)
            .env("VARDE_CONFIG_DIR", self.root.join("config"))
            .env("VARDE_WORKING_DIR", self.working())
            .env("VARDE_KNOWLEDGE_DIR", self.root.join("knowledge"))
            .env("VARDE_LEARN_STORE", self.root.join("learn"))
            .current_dir(self.root.join("repo"))
            .output()
            .unwrap();
        Run {
            success: output.status.success(),
            stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        }
    }
    fn watch(&self, extra: &[&str]) -> Run {
        let mut args = vec!["watch", "--once", "--stale", "1m", "--repo"];
        let repo = self.root.join("repo").display().to_string();
        args.push(&repo);
        args.extend_from_slice(extra);
        self.run(&args)
    }
    fn messages(&self) -> Vec<serde_json::Value> {
        fs::read_to_string(self.working().join(".cache/inbox/messages.jsonl"))
            .unwrap_or_default()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect()
    }
    fn owner_message(&self, plan: &str) {
        let path = self.working().join(".cache/inbox/messages.jsonl");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        let message = serde_json::json!({
            "ts": "9999-12-31T23:59:59Z",
            "from": plan,
            "to": "main",
            "kind": "info",
            "text": "handed back"
        });
        use std::io::Write;
        writeln!(
            fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(path)
                .unwrap(),
            "{message}"
        )
        .unwrap();
    }
}
impl Drop for Store {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn toml_quote(value: &str) -> String {
    serde_json::to_string(value).unwrap()
}

#[test]
fn invokes_direct_argv_with_sanitized_environment_after_inbox_before_cache() {
    let store = Store::new("success");
    store.plan(Some("codex:agent-1"));
    store.owner_message("example");
    store.hostile_waiting_line();
    let record = store.root.join("record");
    let inbox = store.working().join(".cache/inbox/messages.jsonl");
    let repo = fs::canonicalize(store.root.join("repo")).unwrap();
    let digest = sha1::Sha1::digest(repo.as_os_str().to_string_lossy().as_bytes());
    let hash = format!("{digest:x}").chars().take(12).collect::<String>();
    let cache = store
        .working()
        .join(".cache")
        .join(format!("plan-watch-{hash}.json"));
    let script = store.script(&format!("echo WAKE_CHILD_STDOUT\ntest -s '{}'\ntest ! -e '{}'\nprintf '%s\\n%s\\n%s\\n%s\\n' \"$VARDE_WAKE_EVENT\" \"$VARDE_WAKE_PLAN\" \"$VARDE_WAKE_OWNER\" \"$VARDE_WAKE_TEXT\" > '{}'", inbox.display(), cache.display(), record.display()));
    store.configure(&script, 2, 3);
    let run = store.watch(&[]);
    assert!(run.success, "{}", run.stderr);
    let recorded = fs::read_to_string(record).unwrap();
    assert!(
        recorded.starts_with("stale\nexample\ncodex:agent-1\nstale example "),
        "{recorded:?}"
    );
    let text = recorded.lines().nth(3).unwrap();
    assert!(text.chars().count() <= 300);
    assert!(!text.chars().any(char::is_control));
    assert_eq!(store.messages().len(), 2);
    assert!(cache.exists(), "cache should be saved after wake");
    assert!(!run.stdout.contains("WAKE_CHILD_STDOUT"));
}

#[test]
fn failure_timeout_disable_no_owner_empty_command_and_no_wake() {
    let store = Store::new("failure");
    store.plan(None);
    store.plan_named("second", None);
    store.plan_named("third", None);
    let counter = store.root.join("counter");
    let failure = store.script(&format!("count=0; test ! -f '{}' || count=$(cat '{}'); count=$((count+1)); echo $count > '{}'; exit 1", counter.display(), counter.display(), counter.display()));
    store.configure(&failure, 1, 2);
    let run = store.watch(&[]);
    assert!(run.success, "{}", run.stderr);
    assert_eq!(fs::read_to_string(counter).unwrap().trim(), "2");
    let infos = store
        .messages()
        .into_iter()
        .filter(|message| message["kind"] == "info")
        .collect::<Vec<_>>();
    assert!(
        infos
            .iter()
            .any(|message| message["text"].as_str().unwrap().contains("wake failed"))
    );
    assert!(infos.iter().any(|message| {
        message["text"]
            .as_str()
            .unwrap()
            .contains("disabled until restart")
    }));

    for entry in fs::read_dir(store.working().join(".cache")).unwrap() {
        let entry = entry.unwrap();
        if entry
            .file_name()
            .to_string_lossy()
            .starts_with("plan-watch-")
        {
            fs::remove_file(entry.path()).unwrap();
        }
    }
    let timeout = store.script("exec /bin/sleep 5");
    store.configure(&timeout, 1, 1);
    let run = store.watch(&[]);
    assert!(run.success, "{}", run.stderr);
    assert!(store.messages().iter().any(|message| {
        message["text"]
            .as_str()
            .is_some_and(|text| text.contains("timed out"))
    }));

    fs::write(
        store.root.join("config/config.toml"),
        "[orchestration]\nwake_command = []\n",
    )
    .unwrap();
    assert!(store.watch(&[]).success);
    let no_wake_record = store.root.join("no-wake-record");
    let recording = store.script(&format!("touch '{}'", no_wake_record.display()));
    store.configure(&recording, 1, 2);
    for entry in fs::read_dir(store.working().join(".cache")).unwrap() {
        let entry = entry.unwrap();
        if entry
            .file_name()
            .to_string_lossy()
            .starts_with("plan-watch-")
        {
            fs::remove_file(entry.path()).unwrap();
        }
    }
    assert!(store.watch(&["--no-wake"]).success);
    assert!(!no_wake_record.exists());
}

#[test]
fn malformed_config_does_not_disable_inbox_watching() {
    let store = Store::new("malformed-config");
    let plan = store.plan(None);
    store.owner_message("example");
    fs::create_dir_all(store.root.join("config")).unwrap();
    fs::write(store.root.join("config/config.toml"), "not = [valid").unwrap();
    let run = store.watch(&[]);
    assert!(run.success, "{}", run.stderr);
    assert_eq!(
        store
            .messages()
            .iter()
            .filter(|message| message["kind"] == "stale")
            .count(),
        1,
        "stdout: {} stderr: {} messages: {:?}",
        run.stdout,
        run.stderr,
        store.messages()
    );
    assert!(run.stderr.contains("using built-in paths"));
    assert!(
        run.stderr.contains("wake disabled for this run"),
        "{}",
        run.stderr
    );
    assert!(plan.exists());
}

#[test]
fn success_resets_consecutive_wake_failures() {
    let store = Store::new("failure-reset");
    store.plan_named("one", None);
    store.plan_named("two", None);
    store.plan_named("three", None);
    for plan in ["one", "two", "three"] {
        store.owner_message(plan);
    }
    let counter = store.root.join("counter");
    let script = store.script(&format!(
        "count=0; test ! -f '{}' || count=$(cat '{}'); count=$((count+1)); echo $count > '{}'; test \"$count\" -eq 2",
        counter.display(),
        counter.display(),
        counter.display()
    ));
    store.configure(&script, 2, 2);
    let run = store.watch(&[]);
    assert!(run.success, "{}", run.stderr);
    assert_eq!(fs::read_to_string(counter).unwrap().trim(), "3");
    assert!(!store.messages().iter().any(|message| {
        message["text"]
            .as_str()
            .is_some_and(|text| text.contains("disabled until restart"))
    }));
}

#[test]
fn no_inbox_reports_wake_failure_on_stderr() {
    let store = Store::new("no-inbox-failure");
    store.plan(None);
    let script = store.script("exit 1");
    store.configure(&script, 1, 2);
    let run = store.watch(&["--no-inbox"]);
    assert!(run.success, "{}", run.stderr);
    assert!(run.stderr.contains("wake failed"), "{}", run.stderr);
    assert!(store.messages().is_empty());
}

#[test]
fn wakes_after_message_to_main_is_in_inbox() {
    let store = Store::new("main-message-wake");
    store.plan(None);
    let sent = store.run(&[
        "msg",
        "send",
        "--from",
        "agent-1",
        "--to",
        "main",
        "--kind",
        "info",
        "worker finished",
    ]);
    assert!(sent.success, "{}", sent.stderr);

    let record = store.root.join("wake-fired");
    let inbox = store.working().join(".cache/inbox/messages.jsonl");
    let script = store.script(&format!(
        "grep -q 'worker finished' '{}' && touch '{}'",
        inbox.display(),
        record.display()
    ));
    store.configure(&script, 2, 3);

    let run = store.watch(&[]);
    assert!(run.success, "{}", run.stderr);
    assert!(
        record.exists(),
        "wake command did not see the main inbox message"
    );
}

#[test]
fn config_command_is_not_templated_and_owner_is_empty_when_missing() {
    let store = Store::new("argv");
    store.plan(None);
    let record = store.root.join("owner");
    let script = store.script(&format!(
        "printf '%s\\n%s' \"$VARDE_WAKE_OWNER\" \"$1\" > '{}'",
        record.display()
    ));
    fs::create_dir_all(store.root.join("config")).unwrap();
    fs::write(
        store.root.join("config/config.toml"),
        format!(
            "[orchestration]\nwake_command = [{}, {}]\nwake_timeout_seconds = 2\nwake_max_failures = 3\n",
            toml_quote(&script.display().to_string()),
            toml_quote("$VARDE_WAKE_OWNER")
        ),
    )
    .unwrap();
    assert!(store.watch(&[]).success);
    assert_eq!(fs::read_to_string(record).unwrap(), "\n$VARDE_WAKE_OWNER");
}
