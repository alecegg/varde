mod common;

use sha1::{Digest, Sha1};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

fn git_blob_hash(bytes: &[u8]) -> String {
    let mut hasher = Sha1::new();
    hasher.update(format!("blob {}\0", bytes.len()).as_bytes());
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

fn fixture(tag: &str) -> (PathBuf, PathBuf) {
    let root = common::temp_bundle(tag);
    fs::create_dir_all(root.join("memory-bank/knowledge")).unwrap();
    fs::write(
        root.join("memory-bank/knowledge/index.md"),
        "---\nokf_version: 0.2\n---\n",
    )
    .unwrap();
    let plan_dir = root.join("memory-bank/working/plans/group/feature");
    fs::create_dir_all(&plan_dir).unwrap();
    (root, plan_dir)
}

fn write_plan(plan_dir: &Path, extra: &str, checked: bool) -> PathBuf {
    let mark = if checked { "x" } else { " " };
    let path = plan_dir.join("plan.md");
    fs::write(
        &path,
        format!(
            "---\ntype: plan\nstatus: active\n{extra}---\n\n## Acceptance criteria\n\n- [{mark}] behavior verified\n"
        ),
    )
    .unwrap();
    path
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
            "---\ntype: spec\nid: specs/checkout\ndomain: checkout\nsource_hash: {aggregate}\nsources:\n  - path: src/checkout.txt\n    hash: {source_hash}\n---\n\n<!-- varde-spec:generated:start -->\n## Summary\n\nObserved checkout.\n<!-- varde-spec:generated:end -->\n\n## Notes\n"
        ),
    )
    .unwrap();
    spec
}

fn conclude(plan: &Path) -> Output {
    Command::new(common::bin())
        .arg("conclude")
        .arg(plan)
        .arg("--json")
        .output()
        .unwrap()
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
    assert!(
        root.join("memory-bank/knowledge/conclusions/feature.md")
            .exists()
    );
    let conclusion =
        fs::read_to_string(root.join("memory-bank/knowledge/conclusions/feature.md")).unwrap();
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
    let revision = okf_core::occ::version(&fs::read(&contract).unwrap());
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
    assert!(
        !root
            .join("memory-bank/knowledge/conclusions/feature.md")
            .exists()
    );

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn interrupted_conclusion_recovers_exactly_once() {
    let (root, plan_dir) = fixture("conclusion-recovery");
    write_delta(&plan_dir);
    let plan = write_plan(&plan_dir, "contract_deltas:\n  - delta.md\n", true);
    let plan_before = fs::read(&plan).unwrap();

    let output = Command::new(common::bin())
        .arg("conclude")
        .arg(&plan)
        .arg("--json")
        .env("VARDE_WORKFLOW_FAIL_AFTER_CONCLUSION_STAGE", "1")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert_eq!(fs::read(&plan).unwrap(), plan_before);

    let first = Command::new(common::bin())
        .arg("recover")
        .arg("--root")
        .arg(&root)
        .arg("--json")
        .output()
        .unwrap();
    assert!(first.status.success());
    assert_eq!(common::json_data(&first.stdout)["recovered"], true);
    let completed = fs::read(&plan).unwrap();

    let second = Command::new(common::bin())
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

    let output = Command::new(common::bin())
        .arg("conclude")
        .arg(&plan)
        .arg("--json")
        .env("VARDE_WORKFLOW_FAIL_CONCLUSION_AFTER_RENAMES", "2")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(root.join(".varde-workflow-conclusion.json").exists());

    let recovery = Command::new(common::bin())
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
    assert!(
        root.join("memory-bank/knowledge/conclusions/feature.md")
            .exists()
    );

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn refreshed_observed_spec_allows_conclusion_after_staleness() {
    let (root, plan_dir) = fixture("conclusion-spec-refresh");
    let spec = write_fresh_spec(&root);
    let plan = write_plan(&plan_dir, "observed_specs:\n  - checkout\n", true);
    fs::write(root.join("src/checkout.txt"), "new checkout source\n").unwrap();
    assert_eq!(conclude(&plan).status.code(), Some(1));

    let source_hash = git_blob_hash(&fs::read(root.join("src/checkout.txt")).unwrap());
    let aggregate = git_blob_hash(format!("src/checkout.txt{source_hash}").as_bytes());
    fs::write(
        &spec,
        format!(
            "---\ntype: spec\nid: specs/checkout\ndomain: checkout\nsource_hash: {aggregate}\nsources:\n  - path: src/checkout.txt\n    hash: {source_hash}\n---\n\n<!-- varde-spec:generated:start -->\n## Summary\n\nRegenerated checkout.\n<!-- varde-spec:generated:end -->\n\n## Notes\n"
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
fn failed_post_action_is_visible_and_retryable() {
    let (root, plan_dir) = fixture("conclusion-post-action");
    let plan = write_plan(&plan_dir, "", true);
    let output = Command::new(common::bin())
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

    let status = Command::new(common::bin())
        .arg("conclusion-status")
        .arg(&plan)
        .arg("--json")
        .output()
        .unwrap();
    let before = common::json_data(&status.stdout);
    assert_eq!(before["status"], "failed");
    assert_eq!(before["outputs"], serde_json::json!([]));

    let retry = Command::new(common::bin())
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
        let action = Command::new(common::bin())
            .arg("conclusion-action")
            .arg(&plan)
            .arg("reflection")
            .args(["--output", "memory-bank/knowledge/reflection.md", "--json"])
            .output()
            .unwrap();
        assert!(action.status.success());
    }
    for action in ["friction", "handoff"] {
        let output = Command::new(common::bin())
            .arg("conclusion-action")
            .arg(&plan)
            .arg(action)
            .arg("--json")
            .output()
            .unwrap();
        assert!(output.status.success());
    }
    let status = Command::new(common::bin())
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
        let output = Command::new(common::bin())
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
