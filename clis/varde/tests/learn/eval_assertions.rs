use serde_json::Value;
use tempfile::tempdir;

use crate::common::{MockOutputClaude, write_output_skill};

#[test]
fn failed_deterministic_assertion_overrides_passing_judge() {
    let mock = MockOutputClaude::new();
    let skill = tempdir().unwrap();
    write_output_skill(
        skill.path(),
        r#"{"skill_name":"fixture","evals":[{"id":"one","prompt":"test","assertions":["works"],"assert":[{"kind":"file_contains","path":"answer.txt","contains":"expected"}]}]}"#,
    );
    let judge = skill.path().join("judge.json");
    std::fs::write(&judge, r#"{"type":"result","subtype":"success","is_error":false,"result":"{\"results\":[{\"assertion\":\"works\",\"verdict\":\"PASS\",\"evidence\":\"looks good\"}]}"}"#).unwrap();
    let workspace = tempdir().unwrap();
    mock.command()
        .env("MOCK_JUDGE_RESPONSE_FILE", judge)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--no-baseline",
        ])
        .assert()
        .success();

    let run = workspace
        .path()
        .join("iteration-1/eval-one/with_skill/run-1");
    let grading: Value =
        serde_json::from_slice(&std::fs::read(run.join("grading.json")).unwrap()).unwrap();
    assert_eq!(grading["passed"], 1);
    assert_eq!(grading["total"], 2);
    let deterministic = &grading["results"][1];
    assert_eq!(deterministic["verdict"], "FAIL");
    let artifact: Value =
        serde_json::from_slice(&std::fs::read(run.join("assertions.json")).unwrap()).unwrap();
    assert_eq!(artifact["results"][0]["passed"], false);
}

#[test]
fn shipped_eval_assertions_use_required_fields_for_each_kind() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../skills");
    let required = [
        ("file_contains", &["path", "contains"][..]),
        ("file_absent", &["path"][..]),
        ("command_exit", &["command", "exit_code"][..]),
        ("event_order", &["events"][..]),
        ("no_write_outside", &["allowed_paths"][..]),
    ];
    let mut suites = 0;
    for skill in std::fs::read_dir(&root).unwrap().flatten() {
        let path = skill.path().join("evals/evals.json");
        if !path.is_file() {
            continue;
        }
        suites += 1;
        let value: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        for assertion in value["evals"]
            .as_array()
            .into_iter()
            .flatten()
            .flat_map(|eval| eval["assert"].as_array().into_iter().flatten())
        {
            let kind = assertion["kind"].as_str().expect("assertion kind");
            let fields = required
                .iter()
                .find(|(candidate, _)| *candidate == kind)
                .unwrap_or_else(|| panic!("unknown assertion kind {kind} in {}", path.display()));
            for field in fields.1 {
                assert!(
                    assertion.get(*field).is_some(),
                    "{kind} missing {field} in {}",
                    path.display()
                );
            }
        }
    }
    assert!(
        suites > 0,
        "no shipped eval suites found at {}",
        root.display()
    );
}
