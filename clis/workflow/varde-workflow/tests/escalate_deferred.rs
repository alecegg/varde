mod common;

use std::fs;
use std::path::PathBuf;
use std::process::{Command, Output};

struct Fixture {
    root: PathBuf,
    working: PathBuf,
    plan: PathBuf,
    deferred: PathBuf,
}

impl Fixture {
    fn new(tag: &str) -> Self {
        let root = common::temp_bundle(&format!("escalation-{tag}"))
            .canonicalize()
            .unwrap();
        let working = root.join("memory-bank/working");
        let plan = working.join("plans/group/feature");
        let deferred = working.join("reviews/deferred");
        fs::create_dir_all(plan.join("review-one")).unwrap();
        fs::write(plan.join("plan.md"), "# Plan\n").unwrap();
        fs::write(
            plan.join("review-one/review.md"),
            "---\ntype: review\nbranch: main\n---\n",
        )
        .unwrap();
        fs::write(plan.join("review-one/CODE.md"), finding("CODE-001")).unwrap();
        Self {
            root,
            working,
            plan,
            deferred,
        }
    }

    fn command(&self) -> Command {
        let mut command = Command::new(common::bin());
        command
            .current_dir(&self.root)
            .env("VARDE_CONFIG_DIR", self.root.join("config"))
            .env("VARDE_WORKING_DIR", &self.working)
            .env("VARDE_KNOWLEDGE_DIR", self.root.join("knowledge"));
        command
    }

    fn escalate(&self) -> Command {
        let mut command = self.command();
        command
            .args(["escalate-deferred", "--plan-dir"])
            .arg(&self.plan)
            .arg("--deferred-dir")
            .arg(&self.deferred)
            .arg("--json");
        command
    }

    fn source(&self) -> PathBuf {
        self.plan.join("review-one/CODE.md")
    }

    fn journal(&self) -> PathBuf {
        self.working.join(".varde-workflow-escalation.json")
    }

    fn recover(&self) -> Output {
        self.command()
            .args(["recover", "--root"])
            .arg(&self.root)
            .arg("--json")
            .output()
            .unwrap()
    }
}

fn finding(id: &str) -> String {
    format!(
        "# CODE\n\n## [{id}] Keep prose\n\n**Severity:** medium\n**Label:** triage\n**Disposition:** blank\n**Location:** `src/a.rs:1`\n**Escalated:** scope-creep — spans modules\n\n### Summary\n\nKeep this prose.\n```markdown\n## not a heading\n```\n\n### Solutions\n\n1. Fix it.\n"
    )
}

fn success(output: Output) -> serde_json::Value {
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice::<serde_json::Value>(&output.stdout).unwrap()["data"].clone()
}

#[test]
fn copies_and_marks_then_reruns_without_writes() {
    let f = Fixture::new("basic");
    let data = success(f.escalate().output().unwrap());
    assert_eq!(data["summary"]["escalated"], 1);
    let destination = fs::read_to_string(f.deferred.join("CODE.md")).unwrap();
    assert!(
        destination.contains("**Source:** group/feature/review-one\n**Source finding:** CODE-001")
    );
    assert!(destination.contains("## not a heading"));
    assert!(destination.contains("**Disposition:** blank"));
    assert!(
        fs::read_to_string(f.source())
            .unwrap()
            .contains("**Disposition:** escalated")
    );
    assert_eq!(
        success(f.escalate().output().unwrap())["summary"]["escalated"],
        0
    );
    assert_eq!(
        fs::read_to_string(f.deferred.join("CODE.md")).unwrap(),
        destination
    );
}

#[test]
fn new_review_uses_local_calendar_date() {
    let f = Fixture::new("local-date");
    let expected = Command::new("date")
        .arg("+%Y-%m-%d")
        .env("TZ", "Etc/GMT-14")
        .output()
        .unwrap();
    assert!(expected.status.success());
    let expected = String::from_utf8(expected.stdout).unwrap();
    success(f.escalate().env("TZ", "Etc/GMT-14").output().unwrap());
    assert!(
        fs::read_to_string(f.deferred.join("review.md"))
            .unwrap()
            .contains(&format!("date: {}\n", expected.trim()))
    );
}

#[test]
fn next_id_and_legacy_partial_copy_preserve_existing_text() {
    let f = Fixture::new("legacy");
    fs::create_dir_all(&f.deferred).unwrap();
    fs::write(f.deferred.join("CODE.md"), finding("CODE-004")).unwrap();
    fs::write(f.deferred.join("review.md"), "---\ntype: review\ncategories: [CODE]\ntriage_status: complete\n---\n\n## Categories\n\n| Category | Status | Findings |\n|---|---|---:|\n| CODE | complete | 1 |\n\nKeep this prose.\n").unwrap();
    let data = success(f.escalate().output().unwrap());
    assert_eq!(data["findings"][0]["deferred_id"], "CODE-005");
    let destination = fs::read_to_string(f.deferred.join("CODE.md")).unwrap();
    let review = fs::read_to_string(f.deferred.join("review.md")).unwrap();
    assert!(review.contains("triage_status: partial"));
    assert!(review.contains("| CODE | complete | 2 |"));
    assert!(review.contains("Keep this prose."));
    fs::write(f.source(), finding("CODE-001")).unwrap();
    let data = success(f.escalate().output().unwrap());
    assert_eq!(
        data["summary"],
        serde_json::json!({"escalated": 0, "skipped": 1})
    );
    assert_eq!(
        fs::read_to_string(f.deferred.join("CODE.md")).unwrap(),
        destination
    );
    assert_eq!(
        fs::read_to_string(f.deferred.join("review.md")).unwrap(),
        review
    );
    assert!(
        fs::read_to_string(f.source())
            .unwrap()
            .contains("**Disposition:** escalated")
    );
}

#[test]
fn malformed_later_finding_leaves_all_files_unchanged() {
    let f = Fixture::new("malformed");
    let source = format!(
        "{}\n{}",
        finding("CODE-001"),
        finding("CODE-002").replace("**Severity:** medium", "**Severity:** urgent")
    );
    // A second header must not masquerade as a non-finding level-two section.
    let source = source.replacen("\n# CODE\n", "\n", 1);
    fs::write(f.source(), &source).unwrap();
    let output = f.escalate().output().unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("CODE-002 Severity"));
    assert_eq!(fs::read_to_string(f.source()).unwrap(), source);
    assert!(!f.deferred.exists());
    assert!(!f.journal().exists());
}

#[test]
fn rejects_relative_overlapping_and_external_directories() {
    let f = Fixture::new("usage");
    for destination in [f.plan.clone(), f.root.join("outside")] {
        let output = f
            .command()
            .arg("escalate-deferred")
            .arg("--plan-dir")
            .arg(&f.plan)
            .arg("--deferred-dir")
            .arg(destination)
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(2));
    }
    let output = f
        .command()
        .args([
            "escalate-deferred",
            "--plan-dir",
            "relative",
            "--deferred-dir",
        ])
        .arg(&f.deferred)
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
}

#[test]
fn staging_and_partial_commit_recover_with_copy_before_source() {
    for (flag, value) in [
        ("VARDE_WORKFLOW_FAIL_AFTER_ESCALATION_STAGE", "1"),
        ("VARDE_WORKFLOW_FAIL_ESCALATION_AFTER_RENAMES", "1"),
        ("VARDE_WORKFLOW_FAIL_ESCALATION_AFTER_RENAMES", "2"),
    ] {
        let f = Fixture::new(&format!("recover-{flag}-{value}"));
        let output = f.escalate().env(flag, value).output().unwrap();
        assert!(!output.status.success());
        assert!(f.journal().is_file());
        assert!(
            fs::read_to_string(f.source())
                .unwrap()
                .contains("**Disposition:** blank")
        );
        assert_eq!(f.escalate().output().unwrap().status.code(), Some(3));
        assert_eq!(success(f.recover())["recovered"], true);
        assert!(!f.journal().exists());
        assert!(
            fs::read_to_string(f.source())
                .unwrap()
                .contains("**Disposition:** escalated")
        );
        assert!(
            fs::read_to_string(f.deferred.join("CODE.md"))
                .unwrap()
                .contains("**Source finding:** CODE-001")
        );
        assert_eq!(
            success(f.escalate().output().unwrap())["summary"]["escalated"],
            0
        );
    }
}

#[test]
fn recovery_rejects_stale_source_and_changed_inventory() {
    for changed_inventory in [false, true] {
        let f = Fixture::new(&format!("stale-{changed_inventory}"));
        assert!(
            !f.escalate()
                .env("VARDE_WORKFLOW_FAIL_AFTER_ESCALATION_STAGE", "1")
                .output()
                .unwrap()
                .status
                .success()
        );
        if changed_inventory {
            fs::write(f.plan.join("review-one/STYLE.md"), "# STYLE\n").unwrap();
        } else {
            fs::write(
                f.source(),
                finding("CODE-001").replace("Keep this prose.", "Human edited."),
            )
            .unwrap();
        }
        assert_eq!(f.recover().status.code(), Some(3));
        assert!(f.journal().exists());
        assert!(!f.deferred.join("CODE.md").exists());
        assert!(!f.deferred.join("review.md").exists());
    }
}

#[test]
fn recovery_rejects_forged_bookkeeping_writes_and_conclusion_kind() {
    for forgery in ["kind", "content", "target", "proof"] {
        let f = Fixture::new(forgery);
        assert!(
            !f.escalate()
                .env("VARDE_WORKFLOW_FAIL_AFTER_ESCALATION_STAGE", "1")
                .output()
                .unwrap()
                .status
                .success()
        );
        let mut journal: serde_json::Value =
            serde_json::from_slice(&fs::read(f.journal()).unwrap()).unwrap();
        match forgery {
            "kind" => journal["kind"] = "conclusion".into(),
            "content" => journal["entries"][0]["target_hash"] = "forged".into(),
            "target" => {
                journal["entries"][0]["target"] = f.plan.join("plan.md").to_str().unwrap().into()
            }
            "proof" => journal
                .as_object_mut()
                .unwrap()
                .remove("escalation_snapshot")
                .map(|_| ())
                .unwrap(),
            _ => unreachable!(),
        }
        fs::write(f.journal(), serde_json::to_vec(&journal).unwrap()).unwrap();
        assert!(!f.recover().status.success());
        assert!(!f.deferred.join("CODE.md").exists());
        assert!(
            fs::read_to_string(f.source())
                .unwrap()
                .contains("**Disposition:** blank")
        );
    }
}

#[test]
fn recovery_preserves_tampered_stage_after_partial_commit() {
    for tamper in ["unrelated", "content", "suffix"] {
        let f = Fixture::new(&format!("applied-stage-{tamper}"));
        assert!(
            !f.escalate()
                .env("VARDE_WORKFLOW_FAIL_ESCALATION_AFTER_RENAMES", "1")
                .output()
                .unwrap()
                .status
                .success()
        );
        let mut journal: serde_json::Value =
            serde_json::from_slice(&fs::read(f.journal()).unwrap()).unwrap();
        let stage = PathBuf::from(journal["entries"][0]["staging"].as_str().unwrap());
        let protected = match tamper {
            "unrelated" => {
                let protected = f.plan.join("plan.md");
                journal["entries"][0]["staging"] = protected.to_str().unwrap().into();
                protected
            }
            "suffix" => {
                let protected = f.deferred.join("CODE.md.varde-stage-private");
                fs::write(&protected, "private evidence\n").unwrap();
                journal["entries"][0]["staging"] = protected.to_str().unwrap().into();
                protected
            }
            "content" => {
                fs::write(&stage, "private evidence\n").unwrap();
                stage
            }
            _ => unreachable!(),
        };
        let original = fs::read(&protected).unwrap();
        fs::write(f.journal(), serde_json::to_vec(&journal).unwrap()).unwrap();
        assert_eq!(f.recover().status.code(), Some(3));
        assert_eq!(fs::read(&protected).unwrap(), original);
        assert!(f.journal().exists());
        assert!(
            fs::read_to_string(f.source())
                .unwrap()
                .contains("**Disposition:** blank")
        );
    }
}

#[cfg(unix)]
#[test]
fn failed_source_staging_removes_destination_stages_and_new_directories() {
    use std::os::unix::fs::PermissionsExt;
    let f = Fixture::new("stage-failure");
    let review = f.source().parent().unwrap().to_owned();
    fs::set_permissions(&review, fs::Permissions::from_mode(0o555)).unwrap();
    let output = f.escalate().output().unwrap();
    fs::set_permissions(&review, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(!output.status.success());
    assert!(!f.journal().exists());
    assert!(!f.deferred.exists());
    assert!(
        fs::read_to_string(f.source())
            .unwrap()
            .contains("**Disposition:** blank")
    );
    assert_eq!(fs::read_dir(&review).unwrap().count(), 2);
}

#[test]
fn shared_store_serializes_distinct_checkout_lock_domains() {
    use fs4::FileExt;
    let f = Fixture::new("concurrent");
    let one = f.root.join("checkout-one");
    let two = f.root.join("checkout-two");
    for root in [&one, &two] {
        fs::create_dir_all(root).unwrap();
        assert!(
            Command::new("git")
                .args(["init", "-q"])
                .arg(root)
                .status()
                .unwrap()
                .success()
        );
    }
    let store_lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(f.working.join(".varde-workflow-escalation.lock"))
        .unwrap();
    FileExt::lock(&store_lock).unwrap();
    let mut first = f
        .escalate()
        .current_dir(&one)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    let mut second = f
        .escalate()
        .current_dir(&two)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    std::thread::sleep(std::time::Duration::from_millis(150));
    assert!(first.try_wait().unwrap().is_none());
    assert!(second.try_wait().unwrap().is_none());
    FileExt::unlock(&store_lock).unwrap();
    let first = success(first.wait_with_output().unwrap());
    let second = success(second.wait_with_output().unwrap());
    assert_eq!(
        first["summary"]["escalated"].as_u64().unwrap()
            + second["summary"]["escalated"].as_u64().unwrap(),
        1
    );
    assert_eq!(
        fs::read_to_string(f.deferred.join("CODE.md"))
            .unwrap()
            .matches("## [CODE-")
            .count(),
        1
    );
}
