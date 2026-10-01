//! Reviewer-owned fixture evidence through the public CLI, never a gate bypass.

use serde_json::{Value, json};
use std::fs;
use std::path::Path;

fn run(root: &Path, config: &Path, env: &[(&str, &Path)], args: &[&str]) -> Value {
    let output = super::isolate_memory(root)
        .args(args)
        .env("VARDE_CONFIG_DIR", config)
        .envs(env.iter().copied())
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "status={:?}\nstdout={}\nstderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    super::json_data(&output.stdout)
}

pub fn approve_plan(root: &Path, plan: &Path) -> String {
    approve_plan_with_final_review(root, plan, false)
}

pub fn approve_plan_with_final_review(root: &Path, plan: &Path, required: bool) -> String {
    approve_plan_configured_with_risk(root, plan, &root.join("isolated-config"), &[], required)
}

pub fn approve_plan_configured(
    root: &Path,
    plan: &Path,
    config: &Path,
    env: &[(&str, &Path)],
) -> String {
    approve_plan_configured_with_risk(root, plan, config, env, false)
}

/// Approves a `tier_confirmed: true` implementation record against a
/// subject's current state, using the same config/env as its pre-edit
/// approval. `complete`/`conclude` now always require this record (no
/// grandfathering), and it must be re-approved whenever the subject's
/// scoped source changes after an earlier approval, or the record goes
/// stale.
pub fn approve_implementation_configured(
    root: &Path,
    config: &Path,
    env: &[(&str, &Path)],
    subject: &str,
) {
    approve_phase(root, config, env, subject, "implementation", true);
}

fn approve_plan_configured_with_risk(
    root: &Path,
    plan: &Path,
    config: &Path,
    env: &[(&str, &Path)],
    required: bool,
) -> String {
    fs::create_dir_all(root.join("src")).unwrap();
    fs::create_dir_all(config).unwrap();
    let created = run(
        root,
        config,
        env,
        &[
            "review",
            "init",
            "--plan",
            plan.to_str().unwrap(),
            "--repository",
            root.to_str().unwrap(),
            "--scope",
            "src",
            "--json",
        ],
    );
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    approve_phase(root, config, env, subject, "pre-edit", required);
    subject.to_owned()
}

pub fn approve_implementation(root: &Path, subject: &str) {
    approve_implementation_configured(root, &root.join("isolated-config"), &[], subject);
}

fn approve_phase(
    root: &Path,
    config: &Path,
    env: &[(&str, &Path)],
    subject: &str,
    phase: &str,
    required: bool,
) {
    let inspection = run(
        root,
        config,
        env,
        &[
            "review",
            "inspect",
            "--subject",
            subject,
            "--phase",
            phase,
            "--json",
        ],
    );
    let mut record = json!({
        "schema_version": 1, "subject_id": subject, "phase": phase,
        "reviewer": { "identity": "fixture-reviewer", "provenance": "integration-test" },
        "verdict": "approved", "unresolved_choices": [],
        "contract_fingerprint": inspection["contract_fingerprint"],
        "baseline_id": inspection["baseline_id"],
        "verification_approach": "Run the existing CLI integration scenario.",
        "verification_rationale": "The isolated fixture exercises the intended workflow.",
        "verification_expected_results": "The approved transition preserves its existing assertions.",
        "structural_risk": if required { "high" } else { "low" },
        "structural_risk_rationale": "Only isolated fixture source is covered.",
        "implementation_review_required": required,
        "rationale": "The fixture contract has no unresolved choices."
    });
    if phase == "implementation" {
        record["change_fingerprint"] = inspection["change_fingerprint"].clone();
        record["coverage"] = json!("entire-subject-change");
        record["tier_confirmed"] = json!(true);
    }
    let record_path = config.join("fixture-review-record.json");
    fs::write(&record_path, serde_json::to_vec_pretty(&record).unwrap()).unwrap();
    run(
        root,
        config,
        env,
        &[
            "review",
            "record",
            "--subject",
            subject,
            "--expected-version",
            inspection["version"].as_str().unwrap(),
            "--file",
            record_path.to_str().unwrap(),
            "--json",
        ],
    );
}
