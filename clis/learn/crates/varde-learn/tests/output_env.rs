mod common;
use common::{MockHarness, write_output_skill};
use serde_json::json;
use std::fs;
use tempfile::tempdir;

#[test]
fn case_env_is_shared_by_setup_harness_verifier_and_fresh_for_every_run() {
    let mock = MockHarness::new();
    let skill = tempdir().unwrap();
    let workspace = tempdir().unwrap();
    let personal = tempdir().unwrap();
    let log = workspace.path().join("env.log");
    write_output_skill(
        skill.path(),
        &json!({"evals":[{
            "id":"env", "prompt":"request", "assertions":["isolated"],
            "env":{"VARDE_WORKING_DIR":"{sandbox}/working", "VARDE_CONFIG_DIR":"{sandbox}/config", "VARDE_KNOWLEDGE_DIR":"{sandbox}/knowledge", "VARDE_LEARN_STORE":"{sandbox}/learn"},
            "setup_script":"setup.sh", "verification_script":"verify.sh"
        }]})
        .to_string(),
    );
    let record = r#"test "$VARDE_WORKING_DIR" = "$PWD/working"
test "$VARDE_CONFIG_DIR" = "$PWD/config"
test "$VARDE_KNOWLEDGE_DIR" = "$PWD/knowledge"
test "$VARDE_LEARN_STORE" = "$PWD/learn"
test "$CODEX_HOME" = "$EXPECTED_AUTH"
printf '%s|%s\n' "$PHASE" "$VARDE_WORKING_DIR" >> "$ENV_LOG"
mkdir -p "$VARDE_WORKING_DIR"
"#;
    fs::write(
        skill.path().join("setup.sh"),
        format!("set -euo pipefail\nPHASE=setup\n{record}"),
    )
    .unwrap();
    fs::write(skill.path().join("verify.sh"), format!("set -euo pipefail\nPHASE=verify\n{record}\nprintf '%s' '{{\"results\":[{{\"assertion\":\"isolated\",\"verdict\":\"PASS\"}}]}}'\n")).unwrap();
    fs::write(mock.bin_dir().join("mock-cli"), format!("#!/bin/bash\nset -euo pipefail\nPHASE=harness\n{record}\ncat >/dev/null\ncat \"$MOCK_TRACE\"\n")).unwrap();
    let trace = mock.root().join("trace");
    fs::write(
        &trace,
        "{\"type\":\"turn.started\"}\n{\"type\":\"turn.completed\"}\n",
    )
    .unwrap();
    mock.command(
        &trace,
        0,
        [
            "eval",
            "output",
            skill.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--runs",
            "2",
        ],
    )
    .env("VARDE_WORKING_DIR", personal.path())
    .env("VARDE_CONFIG_DIR", personal.path())
    .env("VARDE_KNOWLEDGE_DIR", personal.path())
    .env("VARDE_LEARN_STORE", personal.path())
    .env("ENV_LOG", &log)
    .env("CODEX_HOME", personal.path())
    .env("EXPECTED_AUTH", personal.path())
    .assert()
    .success();
    let text = fs::read_to_string(log).unwrap();
    let lines: Vec<_> = text.lines().collect();
    assert_eq!(lines.len(), 12);
    let mut roots = std::collections::HashSet::new();
    for phases in lines.chunks(3) {
        let root = phases[0].strip_prefix("setup|").unwrap();
        assert_eq!(phases[1], format!("harness|{root}"));
        assert_eq!(phases[2], format!("verify|{root}"));
        assert!(roots.insert(root));
    }
    assert_eq!(fs::read_dir(personal.path()).unwrap().count(), 0);
}

#[test]
fn invalid_case_environment_is_rejected_before_launch() {
    for env in [
        json!([]),
        json!(null),
        json!({"BAD-KEY":"x"}),
        json!({"1BAD":"x"}),
        json!({"EVAL_ID":"x"}),
        json!({"OK":3}),
        json!({"OK":"x\u{0000}y"}),
    ] {
        let mock = MockHarness::new();
        let skill = tempdir().unwrap();
        let workspace = tempdir().unwrap();
        write_output_skill(
            skill.path(),
            &json!({"evals":[{"prompt":"request", "env":env}]}).to_string(),
        );
        let launched = workspace.path().join("launched");
        fs::write(
            mock.bin_dir().join("mock-cli"),
            "#!/bin/bash\ntouch \"$LAUNCHED\"\n",
        )
        .unwrap();
        mock.command(
            &mock.root().join("unused"),
            0,
            [
                "eval",
                "output",
                skill.path().to_str().unwrap(),
                "--workspace",
                workspace.path().to_str().unwrap(),
            ],
        )
        .env("LAUNCHED", &launched)
        .assert()
        .failure();
        assert!(!launched.exists());
    }
}

#[test]
fn case_overrides_do_not_reach_judge() {
    let mock = MockHarness::new();
    let skill = tempdir().unwrap();
    let workspace = tempdir().unwrap();
    write_output_skill(
        skill.path(),
        &json!({"evals":[{
            "id":"judge", "prompt":"request", "assertions":["done"],
            "env":{"CASE_SETTING":"case {literal}"}
        }]})
        .to_string(),
    );
    fs::write(
        mock.bin_dir().join("mock-cli"),
        r#"#!/bin/bash
set -euo pipefail
prompt=$(cat)
if [[ "$prompt" == *'You are grading'* ]]; then
  test "$CASE_SETTING" = inherited
  cat "$JUDGE_TRACE"
else
  test "$CASE_SETTING" = 'case {literal}'
  cat "$MOCK_TRACE"
fi
"#,
    )
    .unwrap();
    let input = mock.root().join("trace");
    fs::write(
        &input,
        "{\"type\":\"turn.started\"}\n{\"type\":\"turn.completed\"}\n",
    )
    .unwrap();
    let judge = mock.root().join("judge");
    let grade =
        json!({"results":[{"assertion":"done", "verdict":"PASS", "evidence":"mock"}]}).to_string();
    fs::write(
        &judge,
        format!(
            "{{\"type\":\"turn.started\"}}\n{}\n{}\n",
            json!({"type":"item.completed", "item":{"type":"agent_message", "text":grade}}),
            json!({"type":"turn.completed"})
        ),
    )
    .unwrap();
    mock.command(
        &input,
        0,
        [
            "eval",
            "output",
            skill.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--no-baseline",
        ],
    )
    .env("CASE_SETTING", "inherited")
    .env("JUDGE_TRACE", judge)
    .assert()
    .success();
    let grading: serde_json::Value = serde_json::from_slice(
        &fs::read(
            workspace
                .path()
                .join("iteration-1/eval-judge/with_skill/run-1/grading.json"),
        )
        .unwrap(),
    )
    .unwrap();
    assert_eq!(grading["passed"], 1);
    assert_eq!(grading["judge_outcome"], "completed");
}
