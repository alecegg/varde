use serde_json::Value;
use tempfile::tempdir;

use crate::common::{MockOutputClaude, write_output_skill};

fn run_fixture(message: &str, setup_failure: bool) -> (Value, Value) {
    let mock = MockOutputClaude::new();
    let skill = tempdir().unwrap();
    let setup = if setup_failure {
        r#", "setup_script":"evals/setup.sh""#
    } else {
        ""
    };
    write_output_skill(
        skill.path(),
        &format!(
            r#"{{"skill_name":"fixture","evals":[{{"id":"one","prompt":"test","assertions":["completed"]{setup}}}]}}"#
        ),
    );
    if setup_failure {
        std::fs::write(skill.path().join("evals/setup.sh"), "exit 1\n").unwrap();
    }
    let workspace = tempdir().unwrap();
    let evaluated = mock.root().join("evaluated.json");
    std::fs::write(
        &evaluated,
        serde_json::json!({"type":"result","subtype":"success","is_error":false,"result":message})
            .to_string(),
    )
    .unwrap();
    let judge = mock.root().join("judge.json");
    std::fs::write(
        &judge,
        serde_json::json!({"type":"result","subtype":"success","is_error":false,"result":serde_json::json!({"results":[{"assertion":"completed","verdict":"PASS","evidence":"fixture"}]}).to_string()}).to_string(),
    )
    .unwrap();

    mock.command()
        .env("MOCK_OUTPUT_RESPONSE_FILE", &evaluated)
        .env("MOCK_JUDGE_RESPONSE_FILE", &judge)
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
    let timing: Value =
        serde_json::from_slice(&std::fs::read(run.join("timing.json")).unwrap()).unwrap();
    let benchmark: Value = serde_json::from_slice(
        &std::fs::read(workspace.path().join("iteration-1/benchmark.json")).unwrap(),
    )
    .unwrap();
    (timing, benchmark)
}

#[test]
fn ordinary_result_text_with_blocking_phrases_is_not_blocked() {
    for (trace, reason) in [
        ("sandbox denial: operation not permitted", "sandbox_denial"),
        ("reviewer failed to launch", "reviewer_launch_failure"),
        ("tool failed to launch", "tool_launch_failure"),
        ("stale approval", "stale_approval"),
        ("application unavailable", "unavailable_app"),
    ] {
        let (timing, benchmark) = run_fixture(trace, false);
        assert!(
            timing["blocked_reason"].is_null(),
            "trace: {trace} ({reason})"
        );
        assert_eq!(benchmark["result"]["runs"][0]["status"], "pass");
    }

    let (timing, benchmark) = run_fixture("completed", true);
    assert_eq!(timing["blocked_reason"], "fixture_setup_failure");
    assert_eq!(benchmark["result"]["runs"][0]["status"], "inconclusive");
}
