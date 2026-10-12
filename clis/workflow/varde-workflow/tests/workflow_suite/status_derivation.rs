use std::fs;
use std::path::PathBuf;
use std::process::{Command, ExitCode};

const ARGS_ENV: &str = "STATUS_DERIVATION_TEST_ARGS";
const BEGIN: &str = "<<<status-derivation-test-begin>>>";
const END: &str = "<<<status-derivation-test-end>>>";

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

struct Store(PathBuf);

impl Store {
    fn new(label: &str) -> Self {
        let root = std::env::temp_dir().join(format!(
            "varde-status-derivation-{label}-{}",
            std::process::id()
        ));
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
        Self(root)
    }

    fn plan(&self, path: &str, status: &str) -> PathBuf {
        let plan = self.working().join("plans").join(path).join("plan.md");
        fs::create_dir_all(plan.parent().unwrap()).unwrap();
        fs::write(
            &plan,
            format!("---\ntype: plan\nstatus: {status}\n---\n\nbody\n"),
        )
        .unwrap();
        plan
    }

    fn working(&self) -> PathBuf {
        self.0.join("working")
    }

    fn run(&self, args: &[&str]) -> String {
        let output = Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "status_derivation::child_entry",
                "--nocapture",
                "--test-threads=1",
            ])
            .env(ARGS_ENV, args.join("\u{1f}"))
            .env("HOME", &self.0)
            .env("VARDE_CONFIG_DIR", self.0.join("config"))
            .env("VARDE_WORKING_DIR", self.working())
            .env("VARDE_KNOWLEDGE_DIR", self.0.join("knowledge"))
            .env("VARDE_LEARN_STORE", self.0.join("learn"))
            .current_dir(self.0.join("repo"))
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let stdout = String::from_utf8_lossy(&output.stdout);
        stdout
            .split_once(BEGIN)
            .and_then(|(_, rest)| rest.split_once(END))
            .map(|(body, _)| body.trim().to_string())
            .unwrap_or_default()
    }
}

impl Drop for Store {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn status_merge_reports_ready_for_an_approved_review() {
    let store = Store::new("merge");
    let plan = store.plan("ready", "active");
    fs::write(
        plan.parent().unwrap().join("review.md"),
        "---\nverdict: approved\n---\n",
    )
    .unwrap();

    let report: serde_json::Value =
        serde_json::from_str(&store.run(&["status", "--json"])).unwrap();
    assert_eq!(report["data"]["plans"][0]["merge"], "ready");
}

#[test]
fn status_merge_reports_none_without_approved_review() {
    let store = Store::new("merge-none");
    store.plan("none", "active");

    let report: serde_json::Value =
        serde_json::from_str(&store.run(&["status", "--json"])).unwrap();
    assert_eq!(report["data"]["plans"][0]["merge"], "none");
}

#[test]
fn status_archived_excludes_archive_path_segments() {
    let store = Store::new("archived");
    store.plan("archive/old", "active");
    store.plan("current", "active");

    let report: serde_json::Value =
        serde_json::from_str(&store.run(&["status", "--json"])).unwrap();
    let ids = report["data"]["plans"]
        .as_array()
        .unwrap()
        .iter()
        .map(|plan| plan["id"].as_str().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(ids, ["current"]);
}

#[test]
fn watch_blocked_does_not_classify_recent_blocked_tasks_as_blocked() {
    let store = Store::new("blocked");
    let plan = store.plan("reviewing", "active");
    let task = plan.parent().unwrap().join("tasks/waiting.md");
    fs::create_dir_all(task.parent().unwrap()).unwrap();
    fs::write(task, "---\ntype: task\nstatus: blocked\n---\nwaiting\n").unwrap();

    let output = store.run(&["watch", "--once", "--stale", "1m", "--repo", "../repo"]);
    assert!(!output.contains("all tasks blocked"), "{output}");
}
