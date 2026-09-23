mod common;

use std::fs;
use std::process::Command;

fn plan(
    root: &std::path::Path,
    name: &str,
    status: &str,
    dependencies: &[&str],
) -> std::path::PathBuf {
    let directory = root.join("memory-bank/working/plans/group").join(name);
    fs::create_dir_all(&directory).unwrap();
    let path = directory.join("plan.md");
    let depends_on = if dependencies.is_empty() {
        String::new()
    } else {
        format!(
            "depends_on:\n{}",
            dependencies
                .iter()
                .map(|item| format!("  - {item}\n"))
                .collect::<String>()
        )
    };
    fs::write(
        &path,
        format!("---\ntype: plan\nstatus: {status}\n{depends_on}---\nbody\n"),
    )
    .unwrap();
    path
}

fn run(command: &str, path: &std::path::Path) -> serde_json::Value {
    let output = Command::new(common::bin())
        .arg(command)
        .arg(path)
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    common::json_data(&output.stdout)
}

#[test]
fn graph_and_readiness_are_deterministic() {
    let root = common::temp_bundle("workflow-graph");
    plan(&root, "foundation", "completed", &[]);
    let target = plan(&root, "feature", "backlog", &["foundation"]);

    let graph = run("graph", &target);
    assert_eq!(graph["root_id"], "feature");
    assert_eq!(graph["nodes"].as_array().unwrap().len(), 2);
    assert_eq!(
        graph["edges"],
        serde_json::json!([{
            "from": "feature",
            "relationship": "depends_on",
            "to": "foundation"
        }])
    );
    assert_eq!(graph["blockers"], serde_json::json!([]));

    let readiness = run("readiness", &target);
    assert_eq!(readiness["ready"], true);
    assert_eq!(
        readiness["actions"],
        serde_json::json!(["active", "blocked"])
    );

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn readiness_reports_incomplete_and_missing_dependencies() {
    let root = common::temp_bundle("workflow-blockers");
    plan(&root, "foundation", "active", &[]);
    let target = plan(&root, "feature", "backlog", &["foundation", "missing"]);

    let readiness = run("readiness", &target);
    assert_eq!(readiness["ready"], false);
    assert_eq!(readiness["actions"], serde_json::json!(["blocked"]));
    assert_eq!(readiness["blockers"].as_array().unwrap().len(), 2);
    assert_eq!(readiness["blockers"][0]["code"], "dependency_incomplete");
    assert_eq!(readiness["blockers"][1]["code"], "dependency_missing");

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn dependency_references_resolve_versioned_artifact_ids() {
    let root = common::temp_bundle("workflow-versioned-ids");
    let dependency = plan(&root, "foundation", "completed", &[]);
    fs::write(
        &dependency,
        "---\nschema_version: 1\nartifact_type: plan\nid: plan-foundation\nstatus: completed\nrelationships: []\nprovenance: {}\n---\nbody\n",
    )
    .unwrap();
    let target = plan(&root, "feature", "backlog", &["foundation"]);

    let graph = run("graph", &target);
    assert_eq!(graph["edges"][0]["to"], "plan-foundation");
    assert_eq!(graph["blockers"], serde_json::json!([]));

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn graph_rejects_duplicate_artifact_ids() {
    let root = common::temp_bundle("workflow-duplicate-ids");
    let first = plan(&root, "first", "completed", &[]);
    let second = plan(&root, "second", "completed", &[]);
    for path in [&first, &second] {
        fs::write(
            path,
            "---\nschema_version: 1\nartifact_type: plan\nid: duplicate\nstatus: completed\nrelationships: []\nprovenance: {}\n---\nbody\n",
        )
        .unwrap();
    }
    let target = plan(&root, "feature", "backlog", &["first", "second"]);

    let output = Command::new(common::bin())
        .arg("graph")
        .arg(&target)
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    let envelope: serde_json::Value = serde_json::from_slice(&output.stderr).unwrap();
    assert!(
        envelope["data"]["error"]["message"]
            .as_str()
            .unwrap()
            .contains("duplicate workflow artifact id")
    );

    fs::remove_dir_all(root).unwrap();
}
