//! End-to-end tests for setting and reporting plan owners.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::time::{Duration, SystemTime};

const ARGS_ENV: &str = "PLAN_OWNER_TEST_ARGS";
const BEGIN: &str = "<<<plan-owner-test-begin>>>";
const END: &str = "<<<plan-owner-test-end>>>";

#[test]
fn child_entry() {
    let Ok(joined) = std::env::var(ARGS_ENV) else {
        return;
    };
    let mut args = vec!["varde".into()];
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
            std::env::temp_dir().join(format!("varde-plan-owner-{label}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("repo")).unwrap();
        let status = Command::new("git")
            .arg("-C")
            .arg(root.join("repo"))
            .args(["init", "-q"])
            .status()
            .unwrap();
        assert!(status.success());
        Self { root }
    }

    fn working(&self) -> PathBuf {
        self.root.join("working")
    }

    fn plan(&self, name: &str, contents: &str) -> PathBuf {
        let path = self.working().join("plans").join(name).join("plan.md");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, contents).unwrap();
        path
    }

    fn run(&self, args: &[&str]) -> Run {
        let output = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "plan_owner::child_entry", "--nocapture"])
            .env(ARGS_ENV, args.join("\u{1f}"))
            .env("HOME", &self.root)
            .env("VARDE_CONFIG_DIR", self.root.join("config"))
            .env("VARDE_WORKING_DIR", self.working())
            .env("VARDE_KNOWLEDGE_DIR", self.root.join("knowledge"))
            .env("VARDE_LEARN_STORE", self.root.join("learn"))
            .current_dir(self.root.join("repo"))
            .output()
            .unwrap();
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

impl Drop for Store {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn set_owner(store: &Store, path: &Path, value: &str) -> Run {
    store.run(&["owner", &path.display().to_string(), value])
}

#[test]
fn sets_replaces_and_clears_owner_without_changing_other_bytes() {
    let store = Store::new("roundtrip");
    let original =
        "---\ntype: plan\ntitle:  Keep  spacing\nstatus: active\n---\n\n# Body\n  exact\n";
    let path = store.plan("roundtrip", original);

    let set = set_owner(&store, &path, "claude:session-one");
    assert!(set.success, "{}", set.stderr);
    let after_set = fs::read_to_string(&path).unwrap();
    assert!(after_set.contains("owner: claude:session-one\n"));
    assert!(after_set.ends_with("\n\n# Body\n  exact\n"));
    assert!(after_set.contains("title:  Keep  spacing\n"));

    let replace = set_owner(&store, &path, "paseo:opaque:id");
    assert!(replace.success, "{}", replace.stderr);
    let after_replace = fs::read_to_string(&path).unwrap();
    assert_eq!(after_replace.matches("owner:").count(), 1);
    assert!(after_replace.contains("owner: paseo:opaque:id\n"));

    let clear = store.run(&["owner", &path.display().to_string(), "--clear"]);
    assert!(clear.success, "{}", clear.stderr);
    let after_clear = fs::read_to_string(&path).unwrap();
    assert_eq!(after_clear, original);
}

#[test]
fn rejects_owner_without_a_colon() {
    let store = Store::new("invalid");
    let original = "---\ntype: plan\nstatus: active\n---\n\nbody\n";
    let path = store.plan("invalid", original);
    let result = set_owner(&store, &path, "not-an-owner");
    assert!(!result.success);
    assert_eq!(fs::read_to_string(path).unwrap(), original);
}

#[test]
fn rejects_empty_parts_and_multiline_owner() {
    let store = Store::new("invalid-values");
    let original = "---\ntype: plan\nstatus: active\n---\n\nbody\n";
    let path = store.plan("invalid-values", original);
    for invalid in [":", "a\nb:c"] {
        let result = set_owner(&store, &path, invalid);
        assert!(!result.success, "accepted {invalid:?}");
        assert_eq!(fs::read_to_string(&path).unwrap(), original);
    }
}

#[test]
fn replacing_multiline_existing_owner_removes_continuations() {
    let store = Store::new("continuation");
    let path = store.plan(
        "continuation",
        "---\ntype: plan\nstatus: active\nowner: |\n  old\n  value\ntitle: Kept\n---\n\nbody\n",
    );
    let result = set_owner(&store, &path, "codex:thread");
    assert!(result.success, "{}", result.stderr);
    let updated = fs::read_to_string(path).unwrap();
    assert!(updated.contains("owner: codex:thread\ntitle: Kept\n"));
    assert!(!updated.contains("  old\n"));
}

#[test]
fn validation_accepts_owner_frontmatter() {
    let store = Store::new("validate");
    let path = store.plan(
        "validate",
        "---\ntype: plan\nstatus: active\nowner: codex:thread-id\n---\n\n## Acceptance criteria\n\n- [ ] works\n",
    );
    let result = store.run(&["validate", &path.display().to_string()]);
    assert!(result.success, "{}", result.stderr);
}

#[test]
fn plan_status_shows_owner_only_when_set() {
    let store = Store::new("status");
    store.plan(
        "owned",
        "---\ntype: plan\nstatus: active\ntitle: Owned\nowner: pi:session\n---\n\nbody\n",
    );
    store.plan(
        "unowned",
        "---\ntype: plan\nstatus: active\ntitle: Unowned\n---\n\nbody\n",
    );
    let result = store.run(&["status"]);
    assert!(result.success, "{}", result.stderr);
    assert!(result.stdout.contains("pi:session"), "{}", result.stdout);
    assert!(
        result.stdout.contains("owned (owner: pi:session)"),
        "{}",
        result.stdout
    );
    assert!(
        !result.stdout.contains("unowned (owner:"),
        "{}",
        result.stdout
    );
}

#[test]
fn watch_event_json_carries_owner() {
    let store = Store::new("event");
    let path = store.plan(
        "event",
        "---\ntype: plan\nstatus: active\nowner: opencode:session-id\n---\n\nbody\n",
    );
    let old = SystemTime::now() - Duration::from_secs(120);
    fs::File::options()
        .write(true)
        .open(&path)
        .unwrap()
        .set_modified(old)
        .unwrap();
    let threshold = "1m";
    let result = store.run(&[
        "watch",
        "--once",
        "--no-inbox",
        "--json",
        "--stale",
        threshold,
        "--repo",
        &store.root.join("repo").display().to_string(),
    ]);
    assert!(result.success, "{}", result.stderr);
    let event: serde_json::Value =
        serde_json::from_str(result.stdout.lines().next().unwrap()).unwrap();
    assert_eq!(event["owner"], "opencode:session-id");
}
