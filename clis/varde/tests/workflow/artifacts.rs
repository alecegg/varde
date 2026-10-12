use super::common;

use std::fs;

fn validate(path: &std::path::Path) -> serde_json::Value {
    let output = common::work_command()
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
        "---\nschema_version: 1\nartifact_type: plan\nid: example\nstatus: active\nrelationships: []\nprovenance:\n  source: human\n---\n## Acceptance criteria\n\n- [ ] done\n",
    )
    .unwrap();

    let first = validate(&versioned);
    assert_eq!(first["schema_version"], 1);
    assert_eq!(first["artifact_type"], "plan");
    assert_eq!(first["id"], "example");
    let revision = first["revision"].as_str().unwrap().to_string();

    fs::write(
        &versioned,
        "---\nschema_version: 1\nartifact_type: plan\nid: example\nstatus: active\nrelationships: []\nprovenance:\n  source: human\n---\nchanged\n\n## Acceptance criteria\n\n- [ ] done\n",
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
        "---\nstatus: backlog\ntitle: \"x\"\ntype: plan\ndepends_on: []\n---\n## Acceptance criteria\n\n- [ ] done\n",
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

    let output = common::work_command()
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

    let output = common::work_command()
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

fn sentences(n: usize) -> String {
    "This is one sentence. ".repeat(n)
}

fn validate_raw(path: &std::path::Path) -> (Option<i32>, serde_json::Value) {
    let output = common::work_command()
        .arg("validate")
        .arg(path)
        .arg("--json")
        .output()
        .unwrap();
    let envelope = serde_json::from_slice(&output.stdout).unwrap();
    (output.status.code(), envelope)
}

#[test]
fn plan_with_oversized_prose_unit_fails_text_audit() {
    let dir = common::temp_bundle("artifact-text-error");
    let plan = dir.join("plan.md");
    let body = sentences(6);
    fs::write(
        &plan,
        format!("---\nstatus: backlog\ntype: plan\ndepends_on: []\n---\n## Acceptance criteria\n\n- [ ] done\n\n{body}\n"),
    )
    .unwrap();

    let (code, envelope) = validate_raw(&plan);
    assert_eq!(code, Some(4));
    assert_eq!(envelope["data"]["error"]["code"], "validation_failed");
    let detail = &envelope["data"]["error"]["details"][0];
    assert_eq!(detail["field"], "text");
    assert!(detail["message"].as_str().unwrap().contains("unit"));

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn task_with_warning_only_unit_succeeds_with_text_warnings() {
    let dir = common::temp_bundle("artifact-text-warning");
    let task = dir.join("tasks/do-thing.md");
    fs::create_dir_all(task.parent().unwrap()).unwrap();
    let body = sentences(4);
    fs::write(
        &task,
        format!("---\ntype: task\nstatus: todo\ndepends_on: []\n---\n{body}\n"),
    )
    .unwrap();

    let (code, envelope) = validate_raw(&task);
    assert_eq!(code, Some(0));
    assert_eq!(envelope["data"]["valid"], true);
    let warnings = envelope["data"]["text_warnings"].as_array().unwrap();
    assert!(!warnings.is_empty());
    assert_eq!(warnings[0]["severity"], "warn");

    fs::remove_dir_all(dir).unwrap();
}

fn validate_text(path: &std::path::Path) -> std::process::Output {
    common::work_command()
        .arg("validate")
        .arg(path)
        .output()
        .unwrap()
}

#[test]
fn plan_with_long_unit_only_under_progress_is_valid() {
    let dir = common::temp_bundle("artifact-text-progress");
    let plan = dir.join("plan.md");
    let body = sentences(6);
    fs::write(
        &plan,
        format!("---\nstatus: backlog\ntype: plan\ndepends_on: []\n---\n## Acceptance criteria\n\n- [ ] done\n\n## Progress\n{body}\n"),
    )
    .unwrap();

    let (code, envelope) = validate_raw(&plan);
    assert_eq!(code, Some(0));
    assert!(envelope["data"].get("text_warnings").is_none());

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn clean_plan_omits_text_warnings() {
    let dir = common::temp_bundle("artifact-text-clean");
    let plan = dir.join("plan.md");
    fs::write(
        &plan,
        "---\nstatus: backlog\ntype: plan\ndepends_on: []\n---\n## Acceptance criteria\n\n- [ ] done\n\nShort body.\n",
    )
    .unwrap();

    let (code, envelope) = validate_raw(&plan);
    assert_eq!(code, Some(0));
    assert!(envelope["data"].get("text_warnings").is_none());

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn text_mode_prints_warn_lines_after_valid() {
    let dir = common::temp_bundle("artifact-text-warn-lines");
    let task = dir.join("tasks/do-thing.md");
    fs::create_dir_all(task.parent().unwrap()).unwrap();
    let body = sentences(4);
    fs::write(
        &task,
        format!("---\ntype: task\nstatus: todo\ndepends_on: []\n---\n{body}\n"),
    )
    .unwrap();

    let output = validate_text(&task);
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.starts_with("valid: "), "{stdout}");
    assert!(stdout.contains("warn: "), "{stdout}");
    assert!(stdout.contains("(unit, 4 sentences)"), "{stdout}");

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn text_mode_prints_error_diagnostic_to_stderr() {
    let dir = common::temp_bundle("artifact-text-error-stderr");
    let plan = dir.join("plan.md");
    let body = sentences(6);
    fs::write(
        &plan,
        format!("---\nstatus: backlog\ntype: plan\ndepends_on: []\n---\n## Acceptance criteria\n\n- [ ] done\n\n{body}\n"),
    )
    .unwrap();

    let output = validate_text(&plan);
    assert_eq!(output.status.code(), Some(4));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.starts_with("text: "), "{stderr}");
    assert!(stderr.contains("(unit, 6 sentences)"), "{stderr}");

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn text_mode_error_still_prints_warnings() {
    let dir = common::temp_bundle("artifact-text-error-warn");
    let plan = dir.join("plan.md");
    let long = sentences(6);
    let medium = sentences(4);
    fs::write(
        &plan,
        format!(
            "---\nstatus: backlog\ntype: plan\ndepends_on: []\n---\n## Acceptance criteria\n\n- [ ] done\n\n{long}\n\n## Notes\n{medium}\n"
        ),
    )
    .unwrap();

    let output = validate_text(&plan);
    assert_eq!(output.status.code(), Some(4));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("text: "), "{stderr}");
    assert!(stderr.contains("warn: "), "{stderr}");

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn non_plan_artifact_skips_text_audit() {
    let dir = common::temp_bundle("artifact-text-skip");
    let doc = dir.join("note.md");
    let body = sentences(6);
    fs::write(&doc, format!("---\ntype: note\n---\n{body}\n")).unwrap();

    let (code, envelope) = validate_raw(&doc);
    assert_eq!(code, Some(0));
    assert!(envelope["data"].get("text_warnings").is_none());

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn task_with_long_unit_only_under_level_four_progress_is_valid() {
    let dir = common::temp_bundle("artifact-text-task-progress");
    let task = dir.join("tasks/do-thing.md");
    fs::create_dir_all(task.parent().unwrap()).unwrap();
    let body = sentences(7);
    fs::write(
        &task,
        format!("---\ntype: task\nstatus: todo\ndepends_on: []\n---\n#### Progress\n{body}\n"),
    )
    .unwrap();

    let (code, _) = validate_raw(&task);
    assert_eq!(code, Some(0));

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn fence_opened_in_progress_does_not_hide_later_long_unit() {
    let dir = common::temp_bundle("artifact-text-progress-fence");
    let plan = dir.join("plan.md");
    let body = sentences(6);
    fs::write(
        &plan,
        format!(
            "---\nstatus: backlog\ntype: plan\ndepends_on: []\n---\n## Acceptance criteria\n\n- [ ] done\n\n## Progress\n```\ncode\n```\n## Notes\n{body}\n"
        ),
    )
    .unwrap();

    let (code, _) = validate_raw(&plan);
    assert_eq!(code, Some(4));

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn fenced_heading_inside_progress_does_not_end_section() {
    let dir = common::temp_bundle("artifact-text-progress-fenced-heading");
    let plan = dir.join("plan.md");
    let body = sentences(6);
    fs::write(
        &plan,
        format!(
            "---\nstatus: backlog\ntype: plan\ndepends_on: []\n---\n## Acceptance criteria\n\n- [ ] done\n\n## Progress\n```\n## Notes\n```\n{body}\n"
        ),
    )
    .unwrap();

    let (code, _) = validate_raw(&plan);
    assert_eq!(code, Some(0));

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn plan_validation_requires_acceptance_section_but_not_checked_criteria() {
    let dir = common::temp_bundle("artifact-acceptance");
    let plan_dir = dir.join("2026-09-24-acceptance");
    fs::create_dir_all(&plan_dir).unwrap();
    let plan = plan_dir.join("plan.md");
    let frontmatter = "---\nstatus: backlog\ntitle: \"x\"\ntype: plan\ndepends_on: []\n---\n";

    fs::write(&plan, format!("{frontmatter}body\n")).unwrap();
    let output = common::work_command()
        .arg("validate")
        .arg(&plan)
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(4));
    let envelope: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(envelope["data"]["error"]["details"][0]["field"], "body");

    fs::write(
        &plan,
        format!("{frontmatter}## Acceptance criteria\n\n- [ ] not yet\n"),
    )
    .unwrap();
    assert_eq!(validate(&plan)["artifact_type"], "plan");

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn generated_plan_field_must_be_a_list_of_strings() {
    let dir = common::temp_bundle("artifact-generated");
    let plan = dir.join("plan.md");
    let body = "## Acceptance criteria\n\n- [ ] done\n";

    fs::write(
        &plan,
        format!("---\ntype: plan\ngenerated: [build/index.json]\n---\n{body}"),
    )
    .unwrap();
    assert_eq!(validate_raw(&plan).0, Some(0));

    for value in ["build/index.json", "[build/index.json, 42]"] {
        fs::write(
            &plan,
            format!("---\ntype: plan\ngenerated: {value}\n---\n{body}"),
        )
        .unwrap();
        let (code, envelope) = validate_raw(&plan);
        assert_eq!(code, Some(4), "{value}");
        assert_eq!(
            envelope["data"]["error"]["details"][0]["field"], "generated",
            "{value}"
        );
    }

    fs::remove_dir_all(dir).unwrap();
}
