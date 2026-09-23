mod common;

use std::fs;
use std::process::Command;

#[test]
fn interrupted_migration_recovers_exactly_once() {
    let root = common::temp_bundle("recovery");
    let artifact = root.join("legacy.md");
    fs::write(&artifact, "---\ntype: reference\n---\nbody\n").unwrap();

    let interrupted = Command::new(common::bin())
        .arg("migrate")
        .arg(&artifact)
        .arg("--apply")
        .env("VARDE_WORKFLOW_FAIL_AFTER_STAGE", "1")
        .output()
        .unwrap();
    assert!(!interrupted.status.success());
    assert!(root.join(".varde-workflow-journal.json").exists());

    let recover = || {
        Command::new(common::bin())
            .arg("recover")
            .arg("--root")
            .arg(&root)
            .arg("--json")
            .output()
            .unwrap()
    };
    let first = recover();
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    assert_eq!(common::json_data(&first.stdout)["recovered"], true);
    assert!(!root.join(".varde-workflow-journal.json").exists());
    let committed = fs::read(&artifact).unwrap();

    let second = recover();
    assert!(second.status.success());
    assert_eq!(common::json_data(&second.stdout)["recovered"], false);
    assert_eq!(fs::read(&artifact).unwrap(), committed);

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn recovery_rejects_journal_paths_outside_root() {
    let root = common::temp_bundle("recovery-containment");
    let outside = root.with_extension("outside.md");
    let stage = root.with_extension("stage.md");
    fs::write(&outside, b"outside").unwrap();
    fs::write(&stage, b"replacement").unwrap();
    let journal = serde_json::json!({
        "version": 1,
        "phase": "staged",
        "target": outside,
        "staging": stage,
        "source_hash": okf_core::occ::version(b"outside"),
        "target_hash": okf_core::occ::version(b"replacement"),
        "recovery_action": "commit",
    });
    fs::write(
        root.join(".varde-workflow-journal.json"),
        serde_json::to_vec(&journal).unwrap(),
    )
    .unwrap();

    let output = Command::new(common::bin())
        .arg("recover")
        .arg("--root")
        .arg(&root)
        .arg("--json")
        .output()
        .unwrap();
    assert!(!output.status.success());
    let envelope: serde_json::Value = serde_json::from_slice(&output.stderr).unwrap();
    assert_eq!(envelope["data"]["error"]["code"], "internal");
    assert_eq!(fs::read(&outside).unwrap(), b"outside");

    fs::remove_dir_all(&root).unwrap();
    fs::remove_file(outside).unwrap();
    fs::remove_file(stage).unwrap();
}
