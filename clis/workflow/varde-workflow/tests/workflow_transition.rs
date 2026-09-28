mod common;

use std::fs;

#[test]
#[cfg(unix)]
fn transition_preserves_existing_permission_bits() {
    use std::os::unix::fs::PermissionsExt;
    let root = common::temp_bundle("transition-permissions");
    for mode in [0o600, 0o640, 0o750, 0o440] {
        let target = plan(&root, &format!("mode-{mode:o}"), "backlog", None);
        fs::set_permissions(&target, fs::Permissions::from_mode(mode)).unwrap();
        let output = common::isolate_memory(&root)
            .arg("transition")
            .arg(&target)
            .args(["blocked", "--json"])
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(
            fs::read_to_string(&target)
                .unwrap()
                .contains("status: blocked")
        );
        assert_eq!(
            fs::metadata(&target).unwrap().permissions().mode() & 0o7777,
            mode
        );
    }
    fs::remove_dir_all(root).unwrap();
}

fn plan(
    root: &std::path::Path,
    name: &str,
    status: &str,
    dependency: Option<&str>,
) -> std::path::PathBuf {
    let directory = root.join("memory-bank/working/plans/group").join(name);
    fs::create_dir_all(&directory).unwrap();
    let path = directory.join("plan.md");
    let depends_on = dependency
        .map(|value| format!("depends_on:\n  - {value}\n"))
        .unwrap_or_default();
    fs::write(
        &path,
        format!("---\ntype: plan\nstatus: {status}\n{depends_on}---\nbody\n"),
    )
    .unwrap();
    path
}

#[test]
fn blocked_transition_preserves_source_bytes() {
    let root = common::temp_bundle("workflow-transition-blocked");
    plan(&root, "foundation", "active", None);
    let target = plan(&root, "feature", "backlog", Some("foundation"));
    let before = fs::read(&target).unwrap();

    let output = common::isolate_memory(&root)
        .args(["transition"])
        .arg(&target)
        .arg("active")
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(4));
    let envelope: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(envelope["data"]["error"]["code"], "workflow_blocked");
    assert_eq!(
        envelope["data"]["error"]["details"]["blockers"][0]["code"],
        "dependency_incomplete"
    );
    assert_eq!(fs::read(&target).unwrap(), before);

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn valid_transition_commits_recoverably() {
    let root = common::temp_bundle("workflow-transition-valid");
    let target = plan(&root, "feature", "backlog", None);
    common::review::approve_plan(&root, &target);

    let output = common::isolate_memory(&root)
        .args(["transition"])
        .arg(&target)
        .arg("active")
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["previous_state"], "backlog");
    assert_eq!(data["state"], "active");
    let content = fs::read_to_string(&target).unwrap();
    assert!(content.contains("status: active"));
    assert!(
        !target
            .parent()
            .unwrap()
            .join(".varde-workflow-journal.json")
            .exists()
    );

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn blocker_state_remains_available_when_dependencies_block() {
    let root = common::temp_bundle("workflow-transition-blocker-state");
    plan(&root, "foundation", "active", None);
    let target = plan(&root, "feature", "backlog", Some("foundation"));

    let output = common::isolate_memory(&root)
        .args(["transition"])
        .arg(&target)
        .arg("blocked")
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        fs::read_to_string(&target)
            .unwrap()
            .contains("status: blocked")
    );

    fs::remove_dir_all(root).unwrap();
}
