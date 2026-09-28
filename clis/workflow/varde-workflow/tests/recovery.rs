mod common;

use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

#[test]
fn interrupted_transition_recovers_exactly_once() {
    let root = common::temp_bundle("recovery");
    let artifact = root.join("plan.md");
    fs::write(&artifact, "---\ntype: plan\nstatus: backlog\n---\nbody\n").unwrap();
    #[cfg(unix)]
    fs::set_permissions(&artifact, fs::Permissions::from_mode(0o600)).unwrap();

    common::review::approve_plan(&root, &artifact);

    let interrupted = common::isolate_memory(&root)
        .args(["transition"])
        .arg(&artifact)
        .arg("active")
        .env("VARDE_WORKFLOW_FAIL_AFTER_STAGE", "1")
        .output()
        .unwrap();
    assert_eq!(interrupted.status.code(), Some(1));
    assert!(root.join(".varde-workflow-journal.json").exists());
    #[cfg(unix)]
    {
        let journal: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join(".varde-workflow-journal.json")).unwrap())
                .unwrap();
        let stage = std::path::Path::new(journal["staging"].as_str().unwrap());
        assert_eq!(
            fs::metadata(stage).unwrap().permissions().mode() & 0o7777,
            0o600
        );
    }

    let recover = || {
        common::isolate_memory(&root)
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
    #[cfg(unix)]
    assert_eq!(
        fs::metadata(&artifact).unwrap().permissions().mode() & 0o7777,
        0o600
    );

    let second = recover();
    assert!(second.status.success());
    assert_eq!(common::json_data(&second.stdout)["recovered"], false);
    assert_eq!(fs::read(&artifact).unwrap(), committed);

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn recovery_rejects_unsupported_journal_versions_without_touching_transaction() {
    let root = common::temp_bundle("recovery-unsupported-version");
    let artifact = root.join("plan.md");
    fs::write(&artifact, "---\ntype: plan\nstatus: backlog\n---\nbody\n").unwrap();
    common::review::approve_plan(&root, &artifact);

    let interrupted = common::isolate_memory(&root)
        .args(["transition", artifact.to_str().unwrap(), "active", "--json"])
        .env("VARDE_WORKFLOW_FAIL_AFTER_STAGE", "1")
        .output()
        .unwrap();
    assert_eq!(interrupted.status.code(), Some(1));
    let journal_path = root.join(".varde-workflow-journal.json");
    let original_journal = fs::read(&journal_path).unwrap();
    let mut unsupported: serde_json::Value = serde_json::from_slice(&original_journal).unwrap();
    unsupported["version"] = 99.into();
    let unsupported_bytes = serde_json::to_vec_pretty(&unsupported).unwrap();
    let stage = std::path::PathBuf::from(unsupported["staging"].as_str().unwrap());
    let stage_before = fs::read(&stage).unwrap();
    let artifact_before = fs::read(&artifact).unwrap();
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
    assert_eq!(fs::read(&artifact).unwrap(), artifact_before);
    assert_eq!(fs::read(&stage).unwrap(), stage_before);

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
        fs::read_to_string(&artifact)
            .unwrap()
            .contains("status: active")
    );
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
        "source_hash": varde_workflow_core::occ::version(b"outside"),
        "target_hash": varde_workflow_core::occ::version(b"replacement"),
        "recovery_action": "commit",
    });
    fs::write(
        root.join(".varde-workflow-journal.json"),
        serde_json::to_vec(&journal).unwrap(),
    )
    .unwrap();

    let output = common::isolate_memory(&root)
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
