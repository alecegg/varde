mod common;

use std::fs;
use std::process::Command;

fn validate(path: &std::path::Path) -> serde_json::Value {
    let output = Command::new(common::bin())
        .arg("validate")
        .arg(path)
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    common::json_data(&output.stdout)["artifact"].clone()
}

#[test]
fn versioned_artifacts_have_deterministic_envelopes() {
    let dir = common::temp_bundle("artifact-envelopes");
    let versioned = dir.join("plan.md");
    fs::write(
        &versioned,
        "---\nschema_version: 1\nartifact_type: plan\nid: example\nstatus: active\nrelationships: []\nprovenance:\n  source: human\n---\nbody\n",
    )
    .unwrap();

    let first = validate(&versioned);
    assert_eq!(first["schema_version"], 1);
    assert_eq!(first["artifact_type"], "plan");
    assert_eq!(first["id"], "example");
    let revision = first["revision"].as_str().unwrap().to_string();

    fs::write(
        &versioned,
        "---\nschema_version: 1\nartifact_type: plan\nid: example\nstatus: active\nrelationships: []\nprovenance:\n  source: human\n---\nchanged\n",
    )
    .unwrap();
    let edited = validate(&versioned);
    assert_eq!(edited["id"], "example");
    assert_ne!(edited["revision"], revision);

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn template_frontmatter_artifacts_derive_their_envelope() {
    let dir = common::temp_bundle("artifact-template-frontmatter");
    let plan_dir = dir.join("2026-09-24-example");
    fs::create_dir_all(plan_dir.join("tasks")).unwrap();
    let plan = plan_dir.join("plan.md");
    fs::write(
        &plan,
        "---\nstatus: backlog\ntitle: \"x\"\ntype: plan\ndepends_on: []\n---\nbody\n",
    )
    .unwrap();
    let task = plan_dir.join("tasks/do-thing.md");
    fs::write(
        &task,
        "---\ntype: task\nstatus: todo\ndepends_on: []\n---\nbody\n",
    )
    .unwrap();

    let plan_envelope = validate(&plan);
    assert_eq!(plan_envelope["artifact_type"], "plan");
    assert_eq!(plan_envelope["id"], "2026-09-24-example");
    assert_eq!(plan_envelope["status"], "backlog");
    assert!(plan_envelope.get("legacy").is_none());
    assert!(plan_envelope.get("migration_required").is_none());

    let task_envelope = validate(&task);
    assert_eq!(task_envelope["artifact_type"], "task");
    assert_eq!(task_envelope["id"], "do-thing");

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn validation_reports_fields_without_mutating_invalid_bytes() {
    let dir = common::temp_bundle("artifact-validation");
    let artifact = dir.join("invalid.md");
    let bytes = b"---\nschema_version: 1\nartifact_type: plan\n---\nbody\n";
    fs::write(&artifact, bytes).unwrap();

    let output = Command::new(common::bin())
        .arg("validate")
        .arg(&artifact)
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(4));
    let envelope: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(envelope["ok"], false);
    assert_eq!(envelope["data"]["error"]["code"], "validation_failed");
    assert_eq!(envelope["data"]["error"]["details"][0]["field"], "id");
    assert_eq!(fs::read(&artifact).unwrap(), bytes);

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn validation_rejects_incorrect_envelope_field_shapes() {
    let dir = common::temp_bundle("artifact-shapes");
    let artifact = dir.join("invalid-shapes.md");
    fs::write(
        &artifact,
        "---\nschema_version: 1\nartifact_type: plan\nid: example\nstatus: []\nrelationships: wrong\nprovenance: wrong\n---\nbody\n",
    )
    .unwrap();

    let output = Command::new(common::bin())
        .arg("validate")
        .arg(&artifact)
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(4));
    let envelope: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let fields: Vec<_> = envelope["data"]["error"]["details"]
        .as_array()
        .unwrap()
        .iter()
        .map(|item| item["field"].as_str().unwrap())
        .collect();
    assert_eq!(fields, ["provenance", "relationships", "status"]);

    fs::remove_dir_all(dir).unwrap();
}
