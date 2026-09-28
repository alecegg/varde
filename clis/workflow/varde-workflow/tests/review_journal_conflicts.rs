mod common;

use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

struct Fixture {
    outside: PathBuf,
    root: PathBuf,
    config: PathBuf,
    knowledge: PathBuf,
    plan: PathBuf,
}
impl Fixture {
    fn new(tag: &str) -> Self {
        let outside = common::temp_bundle(&format!("journal-conflict-{tag}"))
            .canonicalize()
            .unwrap();
        let root = outside.join("repository");
        let config = outside.join("config");
        let plan = root.join("memory-bank/working/plans/group/feature/plan.md");
        fs::create_dir_all(plan.parent().unwrap()).unwrap();
        fs::create_dir_all(&config).unwrap();
        fs::create_dir_all(root.join("src")).unwrap();
        fs::write(root.join("src/feature.rs"), "baseline\n").unwrap();
        fs::write(&plan, "---\ntype: plan\nstatus: backlog\n---\n## Problem\nFinish this isolated change.\n## Acceptance criteria\n- [x] Behavior checked.\n").unwrap();
        let knowledge = root.join("memory-bank/knowledge");
        Self {
            outside,
            root,
            config,
            knowledge,
            plan,
        }
    }
    fn command(&self) -> Command {
        let mut command = Command::new(common::bin());
        command
            .current_dir(&self.root)
            .env("VARDE_CONFIG_DIR", &self.config)
            .env("VARDE_WORKING_DIR", self.root.join("memory-bank/working"))
            .env("VARDE_KNOWLEDGE_DIR", &self.knowledge)
            .env_remove("VARDE_LEARN_STORE");
        command
    }
    fn run(&self, args: &[&str]) -> Output {
        self.command().args(args).arg("--json").output().unwrap()
    }
    fn approve(&self, scope: &str) {
        let inspection = success(self.run(&[
            "review",
            "init",
            "--plan",
            self.plan.to_str().unwrap(),
            "--repository",
            self.root.to_str().unwrap(),
            "--scope",
            scope,
        ]));
        let record = json!({
            "schema_version": 1, "subject_id": inspection["subject"]["subject_id"], "phase": "pre-edit",
            "reviewer": {"identity": "fixture-reviewer", "provenance": "integration-test"}, "verdict": "approved", "unresolved_choices": [],
            "contract_fingerprint": inspection["contract_fingerprint"], "baseline_id": inspection["baseline_id"],
            "verification_approach": "Exercise public journal CLI boundaries.", "verification_rationale": "Test the isolated transaction contract.",
            "verification_expected_results": "Authorized recovery succeeds and conflicts preserve files.", "structural_risk": "low",
            "structural_risk_rationale": "Only temporary fixture files change.", "implementation_review_required": false, "rationale": "No unresolved choices."
        });
        let record_path = self.outside.join("record.json");
        fs::write(&record_path, serde_json::to_vec_pretty(&record).unwrap()).unwrap();
        success(self.run(&[
            "review",
            "record",
            "--subject",
            inspection["subject"]["subject_id"].as_str().unwrap(),
            "--expected-version",
            inspection["version"].as_str().unwrap(),
            "--file",
            record_path.to_str().unwrap(),
        ]));
    }
    fn interrupt_conclusion(&self, partial: bool) {
        let flag = if partial {
            "VARDE_WORKFLOW_FAIL_CONCLUSION_AFTER_RENAMES"
        } else {
            "VARDE_WORKFLOW_FAIL_AFTER_CONCLUSION_STAGE"
        };
        let output = self
            .command()
            .args(["conclude", self.plan.to_str().unwrap(), "--json"])
            .env(flag, "1")
            .output()
            .unwrap();
        assert_eq!(
            output.status.code(),
            Some(1),
            "{} {}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(self.root.join(".varde-workflow-conclusion.json").is_file());
        if partial {
            assert!(
                fs::read_to_string(&self.plan)
                    .unwrap()
                    .contains("status: completed"),
                "first target must actually be applied"
            );
        }
    }
    fn recover(&self) -> Output {
        self.run(&["recover", "--root", self.root.to_str().unwrap()])
    }
    fn target_parent(&self) -> PathBuf {
        let journal: Value = serde_json::from_slice(
            &fs::read(self.root.join(".varde-workflow-conclusion.json")).unwrap(),
        )
        .unwrap();
        journal["entries"]
            .as_array()
            .unwrap()
            .iter()
            .map(|entry| PathBuf::from(entry["target"].as_str().unwrap()))
            .find(|path| path.starts_with(self.root.join("memory-bank/knowledge")))
            .unwrap()
            .parent()
            .unwrap()
            .to_path_buf()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.outside);
    }
}
fn success(output: Output) -> Value {
    assert!(
        output.status.success(),
        "exit={:?}\nstdout={}\nstderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    common::json_data(&output.stdout)
}
fn conflict(output: Output) {
    assert_eq!(
        output.status.code(),
        Some(3),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let bytes = if output.stdout.is_empty() {
        &output.stderr
    } else {
        &output.stdout
    };
    let envelope: Value = serde_json::from_slice(bytes).unwrap();
    assert_eq!(envelope["ok"], false);
    assert_eq!(envelope["data"]["error"]["code"], "conflict");
}
#[derive(Debug, PartialEq, Eq)]
struct Entry {
    kind: &'static str,
    mode: u32,
    bytes: Vec<u8>,
}
fn tree(root: &Path) -> BTreeMap<PathBuf, Entry> {
    fn visit(root: &Path, path: &Path, entries: &mut BTreeMap<PathBuf, Entry>) {
        let metadata = fs::symlink_metadata(path).unwrap();
        #[cfg(unix)]
        let mode = {
            use std::os::unix::fs::PermissionsExt;
            metadata.permissions().mode() & 0o7777
        };
        #[cfg(not(unix))]
        let mode = 0;
        let (kind, bytes) = if metadata.file_type().is_symlink() {
            (
                "symlink",
                fs::read_link(path)
                    .unwrap()
                    .to_string_lossy()
                    .as_bytes()
                    .to_vec(),
            )
        } else if metadata.is_file() {
            ("file", fs::read(path).unwrap())
        } else {
            ("directory", Vec::new())
        };
        entries.insert(
            path.strip_prefix(root).unwrap().to_path_buf(),
            Entry { kind, mode, bytes },
        );
        if metadata.is_dir() && !metadata.file_type().is_symlink() {
            for child in fs::read_dir(path).unwrap() {
                visit(root, &child.unwrap().path(), entries);
            }
        }
    }
    let mut entries = BTreeMap::new();
    visit(root, root, &mut entries);
    entries
}

fn pending_journal_blocks_other(pending_conclusion: bool) {
    let fixture = Fixture::new(if pending_conclusion {
        "pending-conclusion"
    } else {
        "pending-transition"
    });
    fixture.approve("src");
    if pending_conclusion {
        fixture.interrupt_conclusion(false);
    } else {
        let output = fixture
            .command()
            .args([
                "transition",
                fixture.plan.to_str().unwrap(),
                "active",
                "--json",
            ])
            .env("VARDE_WORKFLOW_FAIL_AFTER_STAGE", "1")
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(1));
        assert!(fixture.root.join(".varde-workflow-journal.json").is_file());
    }
    let before = tree(&fixture.root);
    let output = if pending_conclusion {
        fixture.run(&["transition", fixture.plan.to_str().unwrap(), "blocked"])
    } else {
        fixture.run(&["conclude", fixture.plan.to_str().unwrap()])
    };
    conflict(output);
    assert_eq!(
        tree(&fixture.root),
        before,
        "sources, original journal and stages must be preserved"
    );
}
#[test]
fn pending_transition_blocks_conclusion_without_writes() {
    pending_journal_blocks_other(false);
}
#[test]
fn pending_conclusion_blocks_transition_without_writes() {
    pending_journal_blocks_other(true);
}

fn version_one_recovers(all_applied: bool) {
    let fixture = Fixture::new(if all_applied {
        "legacy-applied"
    } else {
        "legacy-partial"
    });
    let first = fixture.root.join("first.md");
    let first_stage = fixture.root.join("first-stage.md");
    let second = fixture.root.join("second.md");
    let second_stage = fixture.root.join("second-stage.md");
    fs::write(&first, "new").unwrap();
    fs::write(&first_stage, "new").unwrap();
    fs::write(&second, if all_applied { "new" } else { "old" }).unwrap();
    fs::write(&second_stage, "new").unwrap();
    // Literal old/new OCC hashes from the original v1 entry format.
    let entries = [(&first, &first_stage), (&second, &second_stage)].map(|(target, stage)| json!({
            "target": target, "staging": stage, "source_hash": "cba06b5736faf67e", "target_hash": "11507a0e2f5e69d5"
        }));
    fs::write(fixture.root.join(".varde-workflow-conclusion.json"), serde_json::to_vec(&json!({ "version": 1, "phase": "staged", "entries": entries, "recovery_action": "commit" })).unwrap()).unwrap();
    assert_eq!(success(fixture.recover())["recovered"], true);
    assert_eq!(fs::read(&first).unwrap(), b"new");
    assert_eq!(fs::read(&second).unwrap(), b"new");
    assert!(!first_stage.exists() && !second_stage.exists());
    assert!(
        !fixture
            .root
            .join(".varde-workflow-conclusion.json")
            .exists()
    );
    assert_eq!(success(fixture.recover())["recovered"], false);
}
#[test]
fn genuine_version_one_conclusion_recovers_partial_entries() {
    version_one_recovers(false);
}
#[test]
fn genuine_version_one_conclusion_recovers_already_applied_entries() {
    version_one_recovers(true);
}

fn root_scope_concludes(interruption: Option<bool>) {
    let fixture = Fixture::new(match interruption {
        None => "root-conclude",
        Some(false) => "root-pre-rename",
        Some(true) => "root-partial",
    });
    fixture.approve(".");
    let existing_parent = fixture.root.join("memory-bank");
    #[cfg(unix)]
    let existing_mode = {
        use std::os::unix::fs::PermissionsExt;
        fs::metadata(&existing_parent).unwrap().permissions().mode()
    };
    if let Some(partial) = interruption {
        fixture.interrupt_conclusion(partial);
        success(fixture.recover());
    } else {
        success(fixture.run(&["conclude", fixture.plan.to_str().unwrap()]));
    }
    assert!(
        fs::read_to_string(&fixture.plan)
            .unwrap()
            .contains("status: completed")
    );
    assert!(
        fixture
            .root
            .join("memory-bank/knowledge/conclusions")
            .is_dir()
    );
    assert!(
        !fixture
            .root
            .join(".varde-workflow-conclusion.json")
            .exists()
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(existing_parent).unwrap().permissions().mode(),
            existing_mode
        );
    }
}
#[test]
fn non_git_root_scope_concludes() {
    root_scope_concludes(None);
}
#[test]
fn non_git_root_scope_recovers_before_any_rename() {
    root_scope_concludes(Some(false));
}
#[test]
fn non_git_root_scope_recovers_after_a_partial_rename() {
    root_scope_concludes(Some(true));
}

#[test]
fn root_scope_recovery_rejects_unrelated_files_and_directories() {
    for variant in ["created-child", "created-directory", "existing-child"] {
        let fixture = Fixture::new(variant);
        fixture.approve(".");
        fixture.interrupt_conclusion(false);
        let path = if variant == "existing-child" {
            fixture.root.join("src/unrelated.rs")
        } else {
            fixture.target_parent().join("unrelated")
        };
        if variant == "created-directory" {
            fs::create_dir(&path).unwrap();
        } else {
            fs::write(&path, "unrelated").unwrap();
        }
        let before = tree(&fixture.root);
        conflict(fixture.recover());
        assert_eq!(tree(&fixture.root), before);
    }
}

#[cfg(unix)]
#[test]
fn root_scope_recovery_rejects_changed_created_directory_type_and_mode() {
    use std::os::unix::fs::{PermissionsExt, symlink};
    for changed_type in [false, true] {
        let fixture = Fixture::new(if changed_type {
            "created-dir-type"
        } else {
            "created-dir-mode"
        });
        fixture.approve(".");
        fixture.interrupt_conclusion(false);
        let parent = fixture.target_parent();
        if changed_type {
            let relocated = fixture.outside.join("relocated-directory");
            fs::rename(&parent, &relocated).unwrap();
            symlink(&relocated, &parent).unwrap();
        } else {
            let mode = fs::metadata(&parent).unwrap().permissions().mode();
            fs::set_permissions(&parent, fs::Permissions::from_mode(mode ^ 0o010)).unwrap();
        }
        let before = tree(&fixture.root);
        conflict(fixture.recover());
        assert_eq!(tree(&fixture.root), before);
    }
}

#[cfg(unix)]
#[test]
fn version_two_recovery_still_rejects_same_bytes_applied_target_symlink() {
    let fixture = Fixture::new("v2-identity");
    fixture.approve("src");
    fixture.interrupt_conclusion(true);
    let outside = fixture.outside.join("same-plan.md");
    fs::write(&outside, fs::read(&fixture.plan).unwrap()).unwrap();
    fs::remove_file(&fixture.plan).unwrap();
    std::os::unix::fs::symlink(&outside, &fixture.plan).unwrap();
    let before = tree(&fixture.root);
    conflict(fixture.recover());
    assert_eq!(tree(&fixture.root), before);
}

fn redirected_missing_ancestor(interruption: Option<bool>) {
    let mut fixture = Fixture::new("redirected-missing-ancestor");
    fixture.knowledge = fixture.outside.join("absent/parent/knowledge");
    let marker = fixture.outside.join("parent-marker");
    fs::write(&marker, "unchanged parent content").unwrap();
    let parent_identity = fs::metadata(&fixture.outside).unwrap();
    #[cfg(unix)]
    let parent_mode = {
        use std::os::unix::fs::PermissionsExt;
        parent_identity.permissions().mode()
    };
    fixture.approve("src");
    if let Some(partial) = interruption {
        fixture.interrupt_conclusion(partial);
        success(fixture.recover());
    } else {
        success(fixture.run(&["conclude", fixture.plan.to_str().unwrap()]));
    }
    assert!(fixture.knowledge.is_dir());
    assert!(
        fs::read_to_string(&fixture.plan)
            .unwrap()
            .contains("status: completed")
    );
    assert!(
        !fixture
            .root
            .join(".varde-workflow-conclusion.json")
            .exists()
    );
    assert_eq!(
        fs::read_to_string(marker).unwrap(),
        "unchanged parent content"
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::{MetadataExt, PermissionsExt};
        let after = fs::metadata(&fixture.outside).unwrap();
        assert_eq!(after.ino(), parent_identity.ino());
        assert_eq!(after.dev(), parent_identity.dev());
        assert_eq!(after.permissions().mode(), parent_mode);
    }
}
#[test]
fn redirected_missing_ancestor_concludes() {
    redirected_missing_ancestor(None);
}
#[test]
fn redirected_missing_ancestor_recovers_before_rename() {
    redirected_missing_ancestor(Some(false));
}
#[test]
fn redirected_missing_ancestor_recovers_after_partial_rename() {
    redirected_missing_ancestor(Some(true));
}
