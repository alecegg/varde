mod common;

use std::fs;
use std::process::Command;

fn inspect(path: &std::path::Path) -> serde_json::Value {
    let output = Command::new(common::bin())
        .arg("inspect")
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
fn versioned_and_legacy_artifacts_have_deterministic_envelopes() {
    let dir = common::temp_bundle("artifact-envelopes");
    let versioned = dir.join("plan.md");
    fs::write(
        &versioned,
        "---\nschema_version: 1\nartifact_type: plan\nid: example\nstatus: active\nrelationships: []\nprovenance:\n  source: human\n---\nbody\n",
    )
    .unwrap();

    let first = inspect(&versioned);
    assert_eq!(first["schema_version"], 1);
    assert_eq!(first["artifact_type"], "plan");
    assert_eq!(first["id"], "example");
    assert_eq!(first["legacy"], false);
    let revision = first["revision"].as_str().unwrap().to_string();

    fs::write(
        &versioned,
        "---\nschema_version: 1\nartifact_type: plan\nid: example\nstatus: active\nrelationships: []\nprovenance:\n  source: human\n---\nchanged\n",
    )
    .unwrap();
    let edited = inspect(&versioned);
    assert_eq!(edited["id"], "example");
    assert_ne!(edited["revision"], revision);

    let legacy = dir.join("legacy.md");
    fs::write(
        &legacy,
        "---\ntype: decision\nstatus: stable\n---\nlegacy\n",
    )
    .unwrap();
    let legacy_first = inspect(&legacy);
    let legacy_second = inspect(&legacy);
    assert_eq!(legacy_first, legacy_second);
    assert_eq!(legacy_first["legacy"], true);
    assert_eq!(legacy_first["migration_required"], true);

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
