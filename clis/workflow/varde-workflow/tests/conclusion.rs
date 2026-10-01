mod common;

use sha1::{Digest, Sha1};
use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

fn git_blob_hash(bytes: &[u8]) -> String {
    let mut hasher = Sha1::new();
    hasher.update(format!("blob {}\0", bytes.len()).as_bytes());
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

const POST_ACTION_STATE: &str = "---\nactions:\n  reflection: pending\n  friction: pending\n  handoff: pending\nstatus: pending\n---\nsentinel\n";

#[test]
#[cfg(unix)]
fn post_action_and_retry_preserve_private_permissions() {
    let (root, plan_dir) = fixture("post-action-permissions");
    let plan = plan_dir.join("plan.md");
    fs::write(
        &plan,
        "---\ntype: plan\nid: feature\nstatus: completed\n---\n",
    )
    .unwrap();
    let post_dir = root.join("memory-bank/knowledge/workflow/post-conclusion");
    fs::create_dir_all(&post_dir).unwrap();
    let document = post_dir.join("feature.md");
    fs::write(&document, POST_ACTION_STATE).unwrap();
    fs::set_permissions(&document, fs::Permissions::from_mode(0o600)).unwrap();
    for operation in ["conclusion-action", "conclusion-retry"] {
        let output = post_action_command(&root, &plan, operation)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(
            fs::metadata(&document).unwrap().permissions().mode() & 0o7777,
            0o600
        );
    }
    fs::remove_dir_all(root).unwrap();
}

fn post_action_command(root: &Path, plan: &Path, operation: &str) -> Command {
    let mut command = common::isolate_memory(root);
    command.arg(operation).arg(plan);
    if operation == "conclusion-action" {
        command.arg("reflection");
    }
    command.arg("--json");
    command
}

fn assert_post_action_rejected(root: &Path, plan: &Path, victim: &Path) {
    let before = fs::read(victim).unwrap();
    for operation in ["conclusion-status", "conclusion-action", "conclusion-retry"] {
        let output = post_action_command(root, plan, operation).output().unwrap();
        assert!(
            !output.status.success(),
            "{operation} accepted an unsafe path"
        );
        assert_eq!(fs::read(victim).unwrap(), before);
    }
}

#[test]
fn post_action_rejects_traversal_and_absolute_ids() {
    let (root, plan_dir) = fixture("post-action-unsafe-id");
    fs::create_dir_all(root.join("memory-bank/knowledge/workflow/post-conclusion")).unwrap();
    let victim = root.join("victim.md");
    fs::write(&victim, POST_ACTION_STATE).unwrap();
    let plan = plan_dir.join("plan.md");
    for id in [
        "../../../../victim".to_string(),
        root.join("victim").display().to_string(),
    ] {
        fs::write(
            &plan,
            format!("---\ntype: plan\nid: {id}\nstatus: completed\n---\n"),
        )
        .unwrap();
        assert_post_action_rejected(&root, &plan, &victim);
    }
    fs::remove_dir_all(root).unwrap();
}

#[cfg(unix)]
#[test]
fn post_action_rejects_escaping_file_and_directory_symlinks() {
    use std::os::unix::fs::symlink;
    let (root, plan_dir) = fixture("post-action-escaping-symlink");
    let post_dir = root.join("memory-bank/knowledge/workflow/post-conclusion");
    fs::create_dir_all(&post_dir).unwrap();
    let victim = root.join("victim.md");
    fs::write(&victim, POST_ACTION_STATE).unwrap();
    let plan = plan_dir.join("plan.md");
    fs::write(
        &plan,
        "---\ntype: plan\nid: victim\nstatus: completed\n---\n",
    )
    .unwrap();
    symlink(&victim, post_dir.join("victim.md")).unwrap();
    assert_post_action_rejected(&root, &plan, &victim);
    fs::remove_file(post_dir.join("victim.md")).unwrap();
    fs::remove_dir(&post_dir).unwrap();
    symlink(&root, &post_dir).unwrap();
    assert_post_action_rejected(&root, &plan, &victim);
    fs::remove_dir_all(root).unwrap();
}

#[cfg(unix)]
#[test]
fn post_action_accepts_nested_ids_and_contained_aliases_in_redirected_knowledge() {
    use std::os::unix::fs::symlink;
    let (root, plan_dir) = fixture("post-action-contained-alias");
    let knowledge = common::temp_bundle("post-action-redirected-knowledge");
    let post_dir = knowledge.join("workflow/post-conclusion/group");
    fs::create_dir_all(&post_dir).unwrap();
    let target = post_dir.join("actual.md");
    fs::write(&target, POST_ACTION_STATE).unwrap();
    symlink(&target, post_dir.join("alias.md")).unwrap();
    let plan = plan_dir.join("plan.md");
    fs::write(
        &plan,
        "---\ntype: plan\nid: group/alias\nstatus: completed\n---\n",
    )
    .unwrap();
    for operation in ["conclusion-status", "conclusion-action", "conclusion-retry"] {
        let output = post_action_command(&root, &plan, operation)
            .env("VARDE_KNOWLEDGE_DIR", &knowledge)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{operation}: {}",
            String::from_utf8_lossy(&output.stdout)
        );
    }
    assert!(
        fs::read_to_string(&target)
            .unwrap()
            .contains("reflection: completed")
    );
    assert!(
        fs::symlink_metadata(post_dir.join("alias.md"))
            .unwrap()
            .file_type()
            .is_symlink()
    );
    fs::remove_dir_all(root).unwrap();
    fs::remove_dir_all(knowledge).unwrap();
}

fn fixture(tag: &str) -> (PathBuf, PathBuf) {
    let root = common::temp_bundle(tag);
    assert!(
        Command::new("git")
            .arg("init")
            .arg("-q")
            .arg(&root)
            .status()
            .unwrap()
            .success()
    );
    fs::create_dir_all(root.join("memory-bank/knowledge")).unwrap();
    fs::write(
        root.join("memory-bank/knowledge/index.md"),
        "---\nschema_version: 1\n---\n",
    )
    .unwrap();
    let plan_dir = root.join("memory-bank/working/plans/group/feature");
    fs::create_dir_all(&plan_dir).unwrap();
    (root, plan_dir)
}

fn write_plan(plan_dir: &Path, extra: &str, checked: bool) -> PathBuf {
    write_plan_and_subject(plan_dir, extra, checked).0
}

fn write_plan_and_subject(plan_dir: &Path, extra: &str, checked: bool) -> (PathBuf, String) {
    let mark = if checked { "x" } else { " " };
    let path = plan_dir.join("plan.md");
    fs::write(
        &path,
        format!(
            "---\ntype: plan\nstatus: active\n{extra}---\n\n## Acceptance criteria\n\n- [{mark}] behavior verified\n"
        ),
    )
    .unwrap();
    let root = plan_dir
        .ancestors()
        .find(|ancestor| {
            ancestor
                .file_name()
                .is_some_and(|name| name == "memory-bank")
        })
        .unwrap()
        .parent()
        .unwrap();
    let subject = common::review::approve_plan(root, &path);
    common::review::approve_implementation(root, &subject);
    (path, subject)
}

fn write_delta(plan_dir: &Path) {
    fs::write(
        plan_dir.join("delta.md"),
        "---\ntype: contract-delta\nschema_version: 1\ncapability: checkout\nsource_plan: feature\n---\n\n## ADDED\n\n### Requirement: submit-order\n\nGiven a valid cart, When checkout runs, Then one order exists.\n\n#### Scenario: retry\n\nRetries preserve one order.\n\n## MODIFIED\n\n## REMOVED\n",
    )
    .unwrap();
}

fn write_fresh_spec(root: &Path) -> PathBuf {
    let source = root.join("src/checkout.txt");
    fs::create_dir_all(source.parent().unwrap()).unwrap();
    fs::write(&source, "checkout source\n").unwrap();
    let source_hash = git_blob_hash(&fs::read(&source).unwrap());
    let aggregate = git_blob_hash(format!("src/checkout.txt{source_hash}").as_bytes());
    let spec = root.join("memory-bank/knowledge/specs/checkout.md");
    fs::create_dir_all(spec.parent().unwrap()).unwrap();
    fs::write(
        &spec,
        format!(
            "---\ntype: spec\nid: specs/checkout\ndomain: checkout\nsource_roots:\n  - src/checkout.txt\ncovered_paths:\n  - src/checkout.txt\nsource_hash: {aggregate}\nsources:\n  - path: src/checkout.txt\n    hash: {source_hash}\n---\n\n<!-- varde-spec:generated:start -->\n## Summary\n\nObserved checkout.\n<!-- varde-spec:generated:end -->\n\n## Notes\n"
        ),
    )
    .unwrap();
    spec
}

fn conclude(plan: &Path) -> Output {
    let root = plan
        .ancestors()
        .find(|ancestor| {
            ancestor
                .file_name()
                .is_some_and(|name| name == "memory-bank")
        })
        .and_then(Path::parent)
        .unwrap();
    common::isolate_memory(root)
        .arg("conclude")
        .arg(plan)
        .arg("--json")
        .output()
        .unwrap()
}

fn conclusion_file(root: &Path, slug: &str) -> Option<PathBuf> {
    let dir = root.join("memory-bank/knowledge/conclusions");
    fs::read_dir(dir)
        .ok()?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .find(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| {
                    name.ends_with(&format!("-{slug}.md"))
                        && name.as_bytes().get(4) == Some(&b'-')
                        && name.as_bytes().get(7) == Some(&b'-')
                })
        })
}

#[test]
fn conclusion_merges_contracts_without_rewriting_observed_specs() {
    let (root, plan_dir) = fixture("conclusion-contracts");
    write_delta(&plan_dir);
    let spec = write_fresh_spec(&root);
    let spec_before = fs::read(&spec).unwrap();
    let plan = write_plan(
        &plan_dir,
        "contract_deltas:\n  - delta.md\nobserved_specs:\n  - checkout\n",
        true,
    );

    let output = conclude(&plan);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let contract =
        fs::read_to_string(root.join("memory-bank/knowledge/contracts/checkout.md")).unwrap();
    assert!(contract.contains("## Requirement: submit-order"));
    assert_eq!(fs::read(&spec).unwrap(), spec_before);
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("status: completed")
    );
    let conclusion = fs::read_to_string(conclusion_file(&root, "feature").unwrap()).unwrap();
    assert!(conclusion.contains("plan: feature\n"));
    assert!(conclusion.contains("plan_revision:"));
    assert!(conclusion.contains("revision:"));

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn later_delta_modifies_an_existing_contract_revision() {
    let (root, plan_dir) = fixture("conclusion-contract-modification");
    write_delta(&plan_dir);
    let first = write_plan(&plan_dir, "contract_deltas:\n  - delta.md\n", true);
    assert!(conclude(&first).status.success());

    let contract = root.join("memory-bank/knowledge/contracts/checkout.md");
    let revision = varde_workflow_core::occ::version(&fs::read(&contract).unwrap());
    let second_dir = root.join("memory-bank/working/plans/group/feature-two");
    fs::create_dir_all(&second_dir).unwrap();
    fs::write(
        second_dir.join("delta.md"),
        format!(
            "---\ntype: contract-delta\nschema_version: 1\ncapability: checkout\nsource_plan: feature-two\nbase_revision: {revision}\n---\n\n## ADDED\n\n## MODIFIED\n\n### Requirement: submit-order\n\nGiven a valid cart, When checkout runs, Then one durable order exists.\n\n## REMOVED\n"
        ),
    )
    .unwrap();
    let second = write_plan(&second_dir, "contract_deltas:\n  - delta.md\n", true);
    assert!(conclude(&second).status.success());
    let updated = fs::read_to_string(contract).unwrap();
    assert!(updated.contains("one durable order exists"));

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn failed_prerequisite_preserves_every_core_artifact() {
    let (root, plan_dir) = fixture("conclusion-prerequisite");
    write_delta(&plan_dir);
    let spec = write_fresh_spec(&root);
    fs::write(root.join("src/checkout.txt"), "changed source\n").unwrap();
    let plan = write_plan(
        &plan_dir,
        "contract_deltas:\n  - delta.md\nobserved_specs:\n  - checkout\n",
        true,
    );
    let plan_before = fs::read(&plan).unwrap();
    let spec_before = fs::read(&spec).unwrap();

    let output = conclude(&plan);
    assert_eq!(output.status.code(), Some(1));
    assert_eq!(fs::read(&plan).unwrap(), plan_before);
    assert_eq!(fs::read(&spec).unwrap(), spec_before);
    assert!(
        !root
            .join("memory-bank/knowledge/contracts/checkout.md")
            .exists()
    );
    assert!(conclusion_file(&root, "feature").is_none());

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn interrupted_conclusion_recovers_exactly_once() {
    let (root, plan_dir) = fixture("conclusion-recovery");
    write_delta(&plan_dir);
    let plan = write_plan(&plan_dir, "contract_deltas:\n  - delta.md\n", true);
    let plan_before = fs::read(&plan).unwrap();
    #[cfg(unix)]
    let plan_mode = fs::metadata(&plan).unwrap().permissions().mode() & 0o7777;

    let output = common::isolate_memory(&root)
        .arg("conclude")
        .arg(&plan)
        .arg("--json")
        .env("VARDE_WORKFLOW_FAIL_AFTER_CONCLUSION_STAGE", "1")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert_eq!(fs::read(&plan).unwrap(), plan_before);

    #[cfg(unix)]
    let created_targets = {
        let journal: serde_json::Value = serde_json::from_slice(
            &fs::read(root.join(".varde-workflow-conclusion.json")).unwrap(),
        )
        .unwrap();
        let mut targets = Vec::new();
        for entry in journal["entries"].as_array().unwrap() {
            if entry["source_hash"].is_null() {
                let stage = Path::new(entry["staging"].as_str().unwrap());
                assert_eq!(
                    fs::metadata(stage).unwrap().permissions().mode() & 0o7777 & !0o600,
                    0
                );
                targets.push(PathBuf::from(entry["target"].as_str().unwrap()));
            }
        }
        assert!(!targets.is_empty());
        targets
    };

    let first = common::isolate_memory(&root)
        .arg("recover")
        .arg("--root")
        .arg(&root)
        .arg("--json")
        .output()
        .unwrap();
    assert!(first.status.success());
    assert_eq!(common::json_data(&first.stdout)["recovered"], true);
    let completed = fs::read(&plan).unwrap();
    #[cfg(unix)]
    {
        assert_eq!(
            fs::metadata(&plan).unwrap().permissions().mode() & 0o7777,
            plan_mode
        );
        for target in created_targets {
            assert_eq!(
                fs::metadata(target).unwrap().permissions().mode() & 0o7777 & !0o600,
                0
            );
        }
    }

    let second = common::isolate_memory(&root)
        .arg("recover")
        .arg("--root")
        .arg(&root)
        .arg("--json")
        .output()
        .unwrap();
    assert!(second.status.success());
    assert_eq!(common::json_data(&second.stdout)["recovered"], false);
    assert_eq!(fs::read(&plan).unwrap(), completed);

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn partially_committed_conclusion_recovers_remaining_writes() {
    let (root, plan_dir) = fixture("conclusion-partial-recovery");
    write_delta(&plan_dir);
    let plan = write_plan(&plan_dir, "contract_deltas:\n  - delta.md\n", true);

    let output = common::isolate_memory(&root)
        .arg("conclude")
        .arg(&plan)
        .arg("--json")
        .env("VARDE_WORKFLOW_FAIL_CONCLUSION_AFTER_RENAMES", "2")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(root.join(".varde-workflow-conclusion.json").exists());

    let recovery = common::isolate_memory(&root)
        .arg("recover")
        .arg("--root")
        .arg(&root)
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        recovery.status.success(),
        "{}",
        String::from_utf8_lossy(&recovery.stderr)
    );
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("status: completed")
    );
    assert!(conclusion_file(&root, "feature").is_some());

    fs::remove_dir_all(root).unwrap();
}

#[test]
#[cfg(unix)]
fn partial_recovery_rejects_broken_symlink_for_an_absent_target() {
    let (root, plan_dir) = fixture("conclusion-broken-symlink-recovery");
    let plan = write_plan(&plan_dir, "", true);
    let interrupted = common::isolate_memory(&root)
        .arg("conclude")
        .arg(&plan)
        .arg("--json")
        .env("VARDE_WORKFLOW_FAIL_CONCLUSION_AFTER_RENAMES", "1")
        .output()
        .unwrap();
    assert_eq!(interrupted.status.code(), Some(1));

    let journal_path = root.join(".varde-workflow-conclusion.json");
    let journal: serde_json::Value =
        serde_json::from_slice(&fs::read(&journal_path).unwrap()).unwrap();
    let unapplied_absent_target = journal["entries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|entry| {
            entry["source_hash"].is_null() && !Path::new(entry["target"].as_str().unwrap()).exists()
        })
        .expect("conclusion stages an output that did not exist before the transaction");
    let target = PathBuf::from(unapplied_absent_target["target"].as_str().unwrap());
    let dangling = target.with_file_name("missing-recovery-target");
    std::os::unix::fs::symlink(dangling, &target).unwrap();

    let rejected = common::isolate_memory(&root)
        .arg("recover")
        .arg("--root")
        .arg(&root)
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(rejected.status.code(), Some(3));
    assert!(journal_path.exists());
    assert!(
        fs::symlink_metadata(&target)
            .unwrap()
            .file_type()
            .is_symlink()
    );

    fs::remove_file(&target).unwrap();
    let recovered = common::isolate_memory(&root)
        .arg("recover")
        .arg("--root")
        .arg(&root)
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        recovered.status.success(),
        "{}",
        String::from_utf8_lossy(&recovered.stderr)
    );
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("status: completed")
    );
    assert!(!journal_path.exists());

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn conclusion_recovery_rejects_unsupported_journal_versions_without_writes() {
    struct FileSnapshot {
        target: PathBuf,
        target_before: Option<Vec<u8>>,
        stage: PathBuf,
        stage_before: Vec<u8>,
    }

    let (root, plan_dir) = fixture("conclusion-unsupported-version");
    write_delta(&plan_dir);
    let plan = write_plan(&plan_dir, "contract_deltas:\n  - delta.md\n", true);
    let plan_before = fs::read(&plan).unwrap();
    let interrupted = common::isolate_memory(&root)
        .arg("conclude")
        .arg(&plan)
        .arg("--json")
        .env("VARDE_WORKFLOW_FAIL_AFTER_CONCLUSION_STAGE", "1")
        .output()
        .unwrap();
    assert_eq!(interrupted.status.code(), Some(1));

    let journal_path = root.join(".varde-workflow-conclusion.json");
    let original_journal = fs::read(&journal_path).unwrap();
    let mut unsupported: serde_json::Value = serde_json::from_slice(&original_journal).unwrap();
    unsupported["version"] = 99.into();
    let unsupported_bytes = serde_json::to_vec_pretty(&unsupported).unwrap();
    let staged: Vec<FileSnapshot> = unsupported["entries"]
        .as_array()
        .unwrap()
        .iter()
        .map(|entry| {
            let target = PathBuf::from(entry["target"].as_str().unwrap());
            let stage = PathBuf::from(entry["staging"].as_str().unwrap());
            FileSnapshot {
                target: target.clone(),
                target_before: fs::read(&target).ok(),
                stage: stage.clone(),
                stage_before: fs::read(stage).unwrap(),
            }
        })
        .collect();
    fs::write(&journal_path, &unsupported_bytes).unwrap();

    let rejected = common::isolate_memory(&root)
        .arg("recover")
        .arg("--root")
        .arg(&root)
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(rejected.status.code(), Some(3));
    let envelope_bytes = if rejected.stdout.is_empty() {
        &rejected.stderr
    } else {
        &rejected.stdout
    };
    let envelope: serde_json::Value = serde_json::from_slice(envelope_bytes).unwrap();
    assert_eq!(envelope["data"]["error"]["code"], "conflict");
    assert_eq!(fs::read(&journal_path).unwrap(), unsupported_bytes);
    assert_eq!(fs::read(&plan).unwrap(), plan_before);
    for snapshot in &staged {
        assert_eq!(fs::read(&snapshot.target).ok(), snapshot.target_before);
        assert_eq!(fs::read(&snapshot.stage).unwrap(), snapshot.stage_before);
    }

    fs::write(&journal_path, original_journal).unwrap();
    let recovered = common::isolate_memory(&root)
        .arg("recover")
        .arg("--root")
        .arg(&root)
        .arg("--json")
        .output()
        .unwrap();
    assert!(recovered.status.success());
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("status: completed")
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn refreshed_observed_spec_allows_conclusion_after_staleness() {
    let (root, plan_dir) = fixture("conclusion-spec-refresh");
    let spec = write_fresh_spec(&root);
    let (plan, subject) =
        write_plan_and_subject(&plan_dir, "observed_specs:\n  - checkout\n", true);
    fs::write(root.join("src/checkout.txt"), "new checkout source\n").unwrap();
    common::review::approve_implementation(&root, &subject);
    assert_eq!(conclude(&plan).status.code(), Some(1));

    let source_hash = git_blob_hash(&fs::read(root.join("src/checkout.txt")).unwrap());
    let aggregate = git_blob_hash(format!("src/checkout.txt{source_hash}").as_bytes());
    fs::write(
        &spec,
        format!(
            "---\ntype: spec\nid: specs/checkout\ndomain: checkout\nsource_roots:\n  - src/checkout.txt\ncovered_paths:\n  - src/checkout.txt\nsource_hash: {aggregate}\nsources:\n  - path: src/checkout.txt\n    hash: {source_hash}\n---\n\n<!-- varde-spec:generated:start -->\n## Summary\n\nRegenerated checkout.\n<!-- varde-spec:generated:end -->\n\n## Notes\n"
        ),
    )
    .unwrap();
    assert!(conclude(&plan).status.success());
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("status: completed")
    );

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn added_or_removed_file_under_source_root_blocks_conclusion() {
    for change in ["added", "removed"] {
        let (root, plan_dir) = fixture(&format!("conclusion-coverage-{change}"));
        let spec = write_fresh_spec(&root);
        let original = fs::read_to_string(&spec).unwrap();
        let covered = if change == "removed" {
            let extra = root.join("src/extra.txt");
            fs::write(&extra, "extra\n").unwrap();
            assert!(
                Command::new("git")
                    .arg("add")
                    .arg("src/extra.txt")
                    .current_dir(&root)
                    .status()
                    .unwrap()
                    .success()
            );
            "covered_paths:\n  - src/checkout.txt\n  - src/extra.txt"
        } else {
            "covered_paths:\n  - src/checkout.txt"
        };
        fs::write(
            &spec,
            original
                .replace(
                    "source_roots:\n  - src/checkout.txt",
                    "source_roots:\n  - src",
                )
                .replace("covered_paths:\n  - src/checkout.txt", covered),
        )
        .unwrap();
        if change == "added" {
            fs::write(root.join("src/extra.txt"), "extra\n").unwrap();
        } else {
            fs::remove_file(root.join("src/extra.txt")).unwrap();
        }
        let plan = write_plan(&plan_dir, "observed_specs:\n  - checkout\n", true);
        let output = conclude(&plan);
        assert_eq!(output.status.code(), Some(1), "{change}");
        assert!(String::from_utf8_lossy(&output.stderr).contains("stale covered_paths"));
        fs::remove_dir_all(root).unwrap();
    }
}

#[test]
fn legacy_spec_without_coverage_is_stale() {
    let (root, plan_dir) = fixture("conclusion-legacy-spec");
    let spec = write_fresh_spec(&root);
    let text = fs::read_to_string(&spec).unwrap();
    fs::write(
        &spec,
        text.replace(
            "source_roots:\n  - src/checkout.txt\ncovered_paths:\n  - src/checkout.txt\n",
            "",
        ),
    )
    .unwrap();
    let plan = write_plan(&plan_dir, "observed_specs:\n  - checkout\n", true);
    let output = conclude(&plan);
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("source_roots"));
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn ignored_file_does_not_change_coverage() {
    let (root, plan_dir) = fixture("conclusion-ignored-coverage");
    let spec = write_fresh_spec(&root);
    let text = fs::read_to_string(&spec).unwrap();
    fs::write(
        &spec,
        text.replace(
            "source_roots:\n  - src/checkout.txt",
            "source_roots:\n  - src",
        ),
    )
    .unwrap();
    fs::write(root.join(".gitignore"), "src/ignored.txt\n").unwrap();
    fs::write(root.join("src/ignored.txt"), "ignored\n").unwrap();
    let plan = write_plan(&plan_dir, "observed_specs:\n  - checkout\n", true);
    let output = conclude(&plan);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn concurrent_post_actions_and_retries_preserve_successful_updates() {
    use fs4::FileExt;
    use std::process::Stdio;

    let (root, plan_dir) = fixture("post-action-concurrent");
    let plan = plan_dir.join("plan.md");
    fs::write(
        &plan,
        "---\ntype: plan\nid: feature\nstatus: completed\n---\n",
    )
    .unwrap();
    let post_dir = root.join("memory-bank/knowledge/workflow/post-conclusion");
    fs::create_dir_all(&post_dir).unwrap();
    let document = post_dir.join("feature.md");
    fs::write(&document, POST_ACTION_STATE).unwrap();
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(post_dir.join(".varde-workflow.lock"))
        .unwrap();
    FileExt::lock(&lock).unwrap();
    let mut children = Vec::new();
    for index in 0..12 {
        let mut command = common::isolate_memory(&root);
        command
            .arg("conclusion-action")
            .arg(&plan)
            .arg(["reflection", "friction", "handoff"][index % 3])
            .args(["--output", &format!("output-{index}"), "--json"])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        children.push(command.spawn().unwrap());
        let mut command = post_action_command(&root, &plan, "conclusion-retry");
        command.stdout(Stdio::piped()).stderr(Stdio::piped());
        children.push(command.spawn().unwrap());
    }
    // Queue contenders behind the existing write lock. The journal unit test
    // separately verifies preparation cannot run before acquiring that lock.
    std::thread::sleep(std::time::Duration::from_millis(300));
    for child in &mut children {
        assert!(child.try_wait().unwrap().is_none());
    }
    FileExt::unlock(&lock).unwrap();
    for child in children {
        let output = child.wait_with_output().unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        common::json_data(&output.stdout);
    }
    let status = post_action_command(&root, &plan, "conclusion-status")
        .output()
        .unwrap();
    let data = common::json_data(&status.stdout);
    assert_eq!(data["outputs"].as_array().unwrap().len(), 12);
    for index in 0..12 {
        assert!(
            data["outputs"]
                .as_array()
                .unwrap()
                .contains(&serde_json::json!(format!("output-{index}")))
        );
    }
    assert_eq!(data["attempts"], 12);
    assert_eq!(data["status"], "completed");
    for action in ["reflection", "friction", "handoff"] {
        assert_eq!(data["actions"][action], "completed");
    }
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn interrupted_post_action_transaction_is_recoverable() {
    let (root, plan_dir) = fixture("post-action-update-recovery");
    let plan = plan_dir.join("plan.md");
    fs::write(
        &plan,
        "---\ntype: plan\nid: feature\nstatus: completed\n---\n",
    )
    .unwrap();
    let post_dir = root.join("memory-bank/knowledge/workflow/post-conclusion");
    fs::create_dir_all(&post_dir).unwrap();
    let document = post_dir.join("feature.md");
    fs::write(&document, POST_ACTION_STATE).unwrap();
    let before = fs::read(&document).unwrap();
    let interrupted = post_action_command(&root, &plan, "conclusion-action")
        .args(["--output", "retained-output"])
        .env("VARDE_WORKFLOW_FAIL_AFTER_STAGE", "1")
        .output()
        .unwrap();
    assert!(!interrupted.status.success());
    assert_eq!(fs::read(&document).unwrap(), before);
    let blocked = post_action_command(&root, &plan, "conclusion-retry")
        .output()
        .unwrap();
    assert!(!blocked.status.success());
    assert_eq!(fs::read(&document).unwrap(), before);
    let recovered = common::isolate_memory(&root)
        .arg("recover")
        .arg("--root")
        .arg(&post_dir)
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        recovered.status.success(),
        "{}",
        String::from_utf8_lossy(&recovered.stderr)
    );
    assert_eq!(common::json_data(&recovered.stdout)["recovered"], true);
    let status = post_action_command(&root, &plan, "conclusion-status")
        .output()
        .unwrap();
    let data = common::json_data(&status.stdout);
    assert_eq!(data["outputs"], serde_json::json!(["retained-output"]));
    assert_eq!(data["actions"]["reflection"], "completed");
    assert!(
        post_action_command(&root, &plan, "conclusion-retry")
            .output()
            .unwrap()
            .status
            .success()
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn failed_post_action_is_visible_and_retryable() {
    let (root, plan_dir) = fixture("conclusion-post-action");
    let plan = write_plan(&plan_dir, "", true);
    let output = common::isolate_memory(&root)
        .arg("conclude")
        .arg(&plan)
        .arg("--json")
        .env("VARDE_WORKFLOW_FAIL_POST_ACTION", "reflection")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("status: completed")
    );

    let status = common::isolate_memory(&root)
        .arg("conclusion-status")
        .arg(&plan)
        .arg("--json")
        .output()
        .unwrap();
    let before = common::json_data(&status.stdout);
    assert_eq!(before["status"], "failed");
    assert_eq!(before["outputs"], serde_json::json!([]));

    let retry = common::isolate_memory(&root)
        .arg("conclusion-retry")
        .arg(&plan)
        .arg("--json")
        .output()
        .unwrap();
    assert!(retry.status.success());
    let data = common::json_data(&retry.stdout);
    assert_eq!(data["status"], "pending");
    assert_eq!(data["attempts"], 2);
    assert_eq!(data["outputs"], serde_json::json!([]));
    assert_eq!(data["actions"]["reflection"], "pending");

    for _ in 0..2 {
        let action = common::isolate_memory(&root)
            .arg("conclusion-action")
            .arg(&plan)
            .arg("reflection")
            .args(["--output", "memory-bank/knowledge/reflection.md", "--json"])
            .output()
            .unwrap();
        assert!(action.status.success());
    }
    for action in ["friction", "handoff"] {
        let output = common::isolate_memory(&root)
            .arg("conclusion-action")
            .arg(&plan)
            .arg(action)
            .arg("--json")
            .output()
            .unwrap();
        assert!(output.status.success());
    }
    let status = common::isolate_memory(&root)
        .arg("conclusion-status")
        .arg(&plan)
        .arg("--json")
        .output()
        .unwrap();
    let completed = common::json_data(&status.stdout);
    assert_eq!(completed["status"], "completed");
    assert_eq!(
        completed["outputs"],
        serde_json::json!(["memory-bank/knowledge/reflection.md"])
    );

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn accepted_findings_promote_with_queryable_provenance() {
    let (root, plan_dir) = fixture("conclusion-promotion");
    fs::write(
        plan_dir.join("finding.md"),
        "---\ntype: observation\nstatus: accepted\nsource_plan: feature\nsource_review: review-7\ndisposition: fixed\nstaleness: current\nresolution: guarded-write\ndestination: guarded-write\n---\n\nWrites need revision guards.\n",
    )
    .unwrap();
    let plan = write_plan(&plan_dir, "promotion_candidates:\n  - finding.md\n", true);
    assert!(conclude(&plan).status.success());

    for filter in [
        "source_plan=feature",
        "source_review=review-7",
        "disposition=fixed",
        "staleness=current",
        "resolution=guarded-write",
    ] {
        let output = common::isolate_memory(&root)
            .args(["concept", "search", "--bundle"])
            .arg(root.join("memory-bank/knowledge"))
            .args(["--field", filter, "--json"])
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{filter}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        let data = common::json_data(&output.stdout);
        assert_eq!(data.as_array().unwrap().len(), 1, "{filter}");
    }

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn portable_outputs_follow_configured_roots_without_rewriting_documents() {
    let (root, plan_dir) = fixture("portable-output");
    let plan = plan_dir.join("plan.md");
    fs::write(
        &plan,
        "---\ntype: plan\nid: feature\nstatus: completed\n---\n",
    )
    .unwrap();
    let knowledge = root.join("redirected-knowledge");
    let working = root.join("redirected-working");
    fs::create_dir_all(knowledge.join("workflow/post-conclusion")).unwrap();
    fs::create_dir_all(&working).unwrap();
    let document = knowledge.join("workflow/post-conclusion/feature.md");
    fs::write(&document, POST_ACTION_STATE).unwrap();
    let target = working.join("handoffs/result.md");
    let run = |operation: &str, output: Option<&str>, store: &Path| {
        let mut command = post_action_command(&root, &plan, operation);
        command
            .env("VARDE_WORKING_DIR", store)
            .env("VARDE_KNOWLEDGE_DIR", &knowledge);
        if let Some(output) = output {
            command.args(["--output", output]);
        }
        let result = command.output().unwrap();
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stdout)
        );
        common::json_data(&result.stdout)
    };
    let data = run(
        "conclusion-action",
        Some(target.to_str().unwrap()),
        &working,
    );
    assert_eq!(
        data["outputs"],
        serde_json::json!(["<working>/handoffs/result.md"])
    );
    let bytes = fs::read(&document).unwrap();
    let status = run("conclusion-status", None, &working);
    assert_eq!(status["output_references"][0]["available"], false);
    fs::create_dir_all(target.parent().unwrap()).unwrap();
    fs::write(&target, "authoritative").unwrap();
    assert_eq!(
        run("conclusion-status", None, &working)["output_references"][0]["available"],
        true
    );
    let moved = root.join("moved-working");
    fs::create_dir_all(moved.join("handoffs")).unwrap();
    fs::write(moved.join("handoffs/result.md"), "authoritative").unwrap();
    let status = run("conclusion-status", None, &moved);
    assert_eq!(
        status["output_references"][0]["path"],
        moved
            .join("handoffs/result.md")
            .canonicalize()
            .unwrap()
            .to_str()
            .unwrap()
    );
    assert_eq!(fs::read(&document).unwrap(), bytes);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn portable_outputs_replace_embedded_configured_paths_deepest_first() {
    let (root, plan_dir) = fixture("portable-output-embedded-roots");
    let plan = plan_dir.join("plan.md");
    fs::write(
        &plan,
        "---\ntype: plan\nid: feature\nstatus: completed\n---\n",
    )
    .unwrap();
    let working = root.join("redirected-working");
    fs::create_dir_all(&working).unwrap();
    let working = working.canonicalize().unwrap();
    let knowledge = working.join("redirected-knowledge");
    fs::create_dir_all(knowledge.join("workflow/post-conclusion")).unwrap();
    let knowledge = knowledge.canonicalize().unwrap();
    let document = knowledge.join("workflow/post-conclusion/feature.md");
    fs::write(&document, POST_ACTION_STATE).unwrap();

    let output = format!(
        "review: {}; decision: {}",
        working.join("reviews/result.md").display(),
        knowledge.join("decisions/result.md").display()
    );
    let result = post_action_command(&root, &plan, "conclusion-action")
        .env("VARDE_WORKING_DIR", &working)
        .env("VARDE_KNOWLEDGE_DIR", &knowledge)
        .arg("--output")
        .arg(&output)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stdout)
    );
    assert_eq!(
        common::json_data(&result.stdout)["outputs"],
        serde_json::json!([
            "review: <working>/reviews/result.md; decision: <knowledge>/decisions/result.md"
        ])
    );

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn portable_outputs_validate_before_mutation_and_preserve_labels() {
    let (root, plan_dir) = fixture("portable-validation");
    let plan = plan_dir.join("plan.md");
    fs::write(
        &plan,
        "---\ntype: plan\nid: feature\nstatus: completed\n---\n",
    )
    .unwrap();
    let post_dir = root.join("memory-bank/knowledge/workflow/post-conclusion");
    fs::create_dir_all(&post_dir).unwrap();
    let document = post_dir.join("feature.md");
    fs::write(&document, POST_ACTION_STATE).unwrap();
    let run = |value: &str| {
        post_action_command(&root, &plan, "conclusion-action")
            .args(["--output", value])
            .output()
            .unwrap()
    };
    for value in [
        "<working>/",
        "<working>/../secret",
        "<working>/a//b",
        "<unknown>/a",
        "<repo>/./file",
        "file:///private/result",
        "FILE:///private/result",
        "FiLe:///private/result",
        "/private/outside-stores/result",
    ] {
        let before = fs::read(&document).unwrap();
        assert!(!run(value).status.success(), "{value}");
        assert_eq!(fs::read(&document).unwrap(), before);
    }
    #[cfg(windows)]
    for value in ["<repo>/C:relative.md", "<working>/C:/absolute.md"] {
        let before = fs::read(&document).unwrap();
        assert!(!run(value).status.success(), "{value}");
        assert_eq!(fs::read(&document).unwrap(), before);
    }
    for value in [
        "reflection recorded",
        "memory-bank/knowledge/reflection.md",
        "<repo>/src/missing.rs",
        "<knowledge>/missing.md",
    ] {
        assert!(run(value).status.success(), "{value}");
    }
    let output = run(root.join("src/missing.rs").to_str().unwrap());
    let data = common::json_data(&output.stdout);
    assert_eq!(data["outputs"].as_array().unwrap().len(), 4);
    #[cfg(windows)]
    {
        let output = run(root.join("src/nested/result.md").to_str().unwrap());
        assert!(output.status.success());
        assert!(
            common::json_data(&output.stdout)["outputs"]
                .as_array()
                .unwrap()
                .contains(&serde_json::json!("<repo>/src/nested/result.md"))
        );
    }
    assert!(
        data["outputs"]
            .as_array()
            .unwrap()
            .contains(&serde_json::json!("reflection recorded"))
    );
    assert!(
        !fs::read_to_string(&document)
            .unwrap()
            .contains("output_references")
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
#[cfg(unix)]
fn portable_outputs_resolve_symlinks_and_prefer_deepest_roots() {
    use std::os::unix::fs::symlink;
    let (root, plan_dir) = fixture("portable-links");
    let plan = plan_dir.join("plan.md");
    fs::write(
        &plan,
        "---\ntype: plan\nid: feature\nstatus: completed\n---\n",
    )
    .unwrap();
    let working = root.join("store");
    let knowledge = working.join("knowledge");
    fs::create_dir_all(knowledge.join("workflow/post-conclusion")).unwrap();
    let document = knowledge.join("workflow/post-conclusion/feature.md");
    fs::write(&document, POST_ACTION_STATE).unwrap();
    fs::create_dir_all(working.join("real")).unwrap();
    symlink("real", working.join("alias")).unwrap();
    symlink("absent", working.join("dangling")).unwrap();
    symlink("loop", working.join("loop")).unwrap();
    symlink(&root, working.join("escape")).unwrap();
    let run = |value: &str| {
        post_action_command(&root, &plan, "conclusion-action")
            .env("VARDE_WORKING_DIR", &working)
            .env("VARDE_KNOWLEDGE_DIR", &knowledge)
            .args(["--output", value])
            .output()
            .unwrap()
    };
    for value in [
        working.join("alias/missing/file.md"),
        knowledge.join("new.md"),
    ] {
        assert!(run(value.to_str().unwrap()).status.success());
    }
    let status = post_action_command(&root, &plan, "conclusion-status")
        .env("VARDE_WORKING_DIR", &working)
        .env("VARDE_KNOWLEDGE_DIR", &knowledge)
        .output()
        .unwrap();
    assert_eq!(
        common::json_data(&status.stdout)["outputs"],
        serde_json::json!(["<knowledge>/new.md", "<working>/real/missing/file.md"])
    );
    for value in [
        "<working>/escape/file.md",
        "<working>/dangling/file.md",
        "<working>/loop/file.md",
    ] {
        let before = fs::read(&document).unwrap();
        assert!(!run(value).status.success(), "{value}");
        assert_eq!(fs::read(&document).unwrap(), before);
    }
    for value in [
        working.join("dangling/file.md"),
        working.join("loop/file.md"),
        working.join("missing/../loop/../file.md"),
    ] {
        assert!(!run(value.to_str().unwrap()).status.success());
    }
    // A once-valid reference can later become unsafe; status must not expose the outside target.
    fs::remove_dir(working.join("real")).unwrap();
    symlink(&root, working.join("real")).unwrap();
    let before = fs::read(&document).unwrap();
    let status = post_action_command(&root, &plan, "conclusion-status")
        .env("VARDE_WORKING_DIR", &working)
        .env("VARDE_KNOWLEDGE_DIR", &knowledge)
        .output()
        .unwrap();
    let data = common::json_data(&status.stdout);
    let invalid = &data["output_references"][1];
    assert_eq!(invalid["available"], false);
    assert!(invalid["path"].is_null());
    assert!(invalid["error"].is_string());
    assert_eq!(fs::read(&document).unwrap(), before);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn portable_repo_outputs_use_the_invoking_linked_checkout() {
    let (root, plan_dir) = fixture("portable-worktree");
    let plan = plan_dir.join("plan.md");
    fs::write(
        &plan,
        "---\ntype: plan\nid: feature\nstatus: completed\n---\n",
    )
    .unwrap();
    let post_dir = root.join("memory-bank/knowledge/workflow/post-conclusion");
    fs::create_dir_all(&post_dir).unwrap();
    fs::write(post_dir.join("feature.md"), POST_ACTION_STATE).unwrap();
    for args in [
        vec!["add", "."],
        vec![
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
    ] {
        assert!(
            Command::new("git")
                .current_dir(&root)
                .args(args)
                .output()
                .unwrap()
                .status
                .success()
        );
    }
    let checkout = root.join("linked");
    assert!(
        Command::new("git")
            .current_dir(&root)
            .args(["worktree", "add", "--detach"])
            .arg(&checkout)
            .output()
            .unwrap()
            .status
            .success()
    );
    let output = post_action_command(&root, &plan, "conclusion-action")
        .current_dir(&checkout)
        .arg("--output")
        .arg(checkout.join("result.md"))
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stdout)
    );
    assert_eq!(
        common::json_data(&output.stdout)["outputs"],
        serde_json::json!(["<repo>/result.md"])
    );
    let status = post_action_command(&root, &plan, "conclusion-status")
        .current_dir(&checkout)
        .output()
        .unwrap();
    assert_eq!(
        common::json_data(&status.stdout)["output_references"][0]["path"],
        checkout
            .canonicalize()
            .unwrap()
            .join("result.md")
            .to_str()
            .unwrap()
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn conclusion_and_action_use_linked_checkout_knowledge_for_external_plan() {
    let (root, _) = fixture("conclusion-linked-external-plan");
    for args in [
        vec!["add", "."],
        vec![
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
    ] {
        assert!(
            Command::new("git")
                .current_dir(&root)
                .args(args)
                .output()
                .unwrap()
                .status
                .success()
        );
    }
    let checkout = root.join("linked");
    assert!(
        Command::new("git")
            .current_dir(&root)
            .args(["worktree", "add", "--detach"])
            .arg(&checkout)
            .output()
            .unwrap()
            .status
            .success()
    );

    let working = root.join("external-working");
    let config = root.join("isolated-config");
    fs::create_dir_all(&config).unwrap();
    fs::write(
        config.join("config.toml"),
        format!(
            "[project.{}]\nworking = {}\n",
            serde_json::to_string(root.to_str().unwrap()).unwrap(),
            serde_json::to_string(working.to_str().unwrap()).unwrap(),
        ),
    )
    .unwrap();
    let plan = working.join("plans/feature/plan.md");
    fs::create_dir_all(plan.parent().unwrap()).unwrap();
    fs::write(
        &plan,
        "---\ntype: plan\nid: feature\nstatus: active\n---\n\n## Acceptance criteria\n\n- [x] behavior verified\n",
    )
    .unwrap();
    let env = [("VARDE_WORKING_DIR", working.as_path())];
    let subject = common::review::approve_plan_configured(&root, &plan, &config, &env);
    common::review::approve_implementation_configured(&root, &config, &env, &subject);

    let output = common::isolate_memory(&root)
        .current_dir(&checkout)
        .env("VARDE_CONFIG_DIR", &config)
        .env("VARDE_WORKING_DIR", &working)
        .args(["conclude", plan.to_str().unwrap(), "--json"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "stdout={}\nstderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let linked_conclusion = conclusion_file(&checkout, "feature").unwrap();
    assert!(linked_conclusion.is_file());
    assert!(conclusion_file(&root, "feature").is_none());
    let linked_promotion = checkout.join("memory-bank/knowledge/promotions/feature.md");
    let main_promotion = root.join("memory-bank/knowledge/promotions/feature.md");
    assert!(linked_promotion.is_file());
    assert!(!main_promotion.exists());
    let linked_post_action =
        checkout.join("memory-bank/knowledge/workflow/post-conclusion/feature.md");
    let main_post_action = root.join("memory-bank/knowledge/workflow/post-conclusion/feature.md");
    assert!(linked_post_action.is_file());
    assert!(!main_post_action.exists());

    let action = post_action_command(&root, &plan, "conclusion-action")
        .current_dir(&checkout)
        .env("VARDE_CONFIG_DIR", &config)
        .env("VARDE_WORKING_DIR", &working)
        .output()
        .unwrap();
    assert!(
        action.status.success(),
        "{}",
        String::from_utf8_lossy(&action.stdout)
    );
    assert!(
        fs::read_to_string(&linked_post_action)
            .unwrap()
            .contains("reflection: completed")
    );
    assert!(!main_post_action.exists());

    fs::remove_dir_all(root).unwrap();
}
