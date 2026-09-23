mod common;

use std::fs;
use std::process::Command;

fn write_plan(
    root: &std::path::Path,
    name: &str,
    artifact_type: &str,
    status: &str,
) -> std::path::PathBuf {
    let directory = root.join("memory-bank/working/plans/group").join(name);
    fs::create_dir_all(&directory).unwrap();
    let path = directory.join("plan.md");
    fs::write(
        &path,
        format!("---\ntype: {artifact_type}\nstatus: {status}\n---\nbody\n"),
    )
    .unwrap();
    path
}

#[test]
fn project_schema_accepts_new_artifact_types() {
    let root = common::temp_bundle("workflow-schema-addition");
    let schema_dir = root.join("memory-bank/knowledge/workflow");
    fs::create_dir_all(&schema_dir).unwrap();
    fs::write(
        schema_dir.join("schema.yml"),
        "schema_version: 1\nartifact_types:\n  proposal:\n    initial_state: draft\n    states: [approved, draft]\n    completion_states: [approved]\n    transitions:\n      draft: [approved]\n      approved: []\n",
    )
    .unwrap();
    let plan = write_plan(&root, "proposal-one", "proposal", "draft");

    let output = Command::new(common::bin())
        .args(["graph"])
        .arg(&plan)
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(
        data["schema"]["artifact_types"]["proposal"]["initial_state"],
        "draft"
    );
    assert_eq!(data["nodes"][0]["artifact_type"], "proposal");

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn project_schema_rejects_core_replacements() {
    let root = common::temp_bundle("workflow-schema-replacement");
    let schema_dir = root.join("memory-bank/knowledge/workflow");
    fs::create_dir_all(&schema_dir).unwrap();
    fs::write(
        schema_dir.join("schema.yml"),
        "schema_version: 1\nartifact_types:\n  plan:\n    initial_state: new\n    states: [new]\n    completion_states: [new]\n    transitions:\n      new: []\n",
    )
    .unwrap();
    let plan = write_plan(&root, "plan-one", "plan", "backlog");

    let output = Command::new(common::bin())
        .args(["graph"])
        .arg(&plan)
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    let envelope: serde_json::Value = serde_json::from_slice(&output.stderr).unwrap();
    assert_eq!(envelope["data"]["error"]["code"], "internal");
    assert!(
        envelope["data"]["error"]["message"]
            .as_str()
            .unwrap()
            .contains("cannot replace core")
    );

    fs::remove_dir_all(root).unwrap();
}
