mod common;
use common::{MockHarness, write_output_skill};
use serde_json::{Value, json};
use std::{fs, path::Path};
use tempfile::tempdir;
fn read(path: &Path) -> Value {
    serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
}
fn trace() -> String {
    [json!({"type":"turn.started"}),json!({"type":"item.completed","item":{"type":"command_execution","command":"cat input","aggregated_output":"captured"}}),json!({"type":"item.completed","item":{"type":"agent_message","text":"done"}}),json!({"type":"turn.completed","usage":{"input_tokens":120,"cached_input_tokens":100,"output_tokens":30}})].iter().map(Value::to_string).collect::<Vec<_>>().join("\n")
}
fn run(trace: &str, exit: i32) -> tempfile::TempDir {
    let mock = MockHarness::new();
    let skill = tempdir().unwrap();
    let workspace = tempdir().unwrap();
    write_output_skill(
        skill.path(),
        r#"{"evals":[{"id":"one","prompt":"request","assertions":["done"],"verification_script":"verify.sh"}]}"#,
    );
    fs::write(
        skill.path().join("verify.sh"),
        r#"printf '%s' '{"results":[{"assertion":"done","verdict":"PASS","evidence":"yes"}]}'"#,
    )
    .unwrap();
    let input = mock.root().join("trace");
    fs::write(&input, trace).unwrap();
    mock.command(
        &input,
        exit,
        [
            "eval",
            "output",
            skill.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--no-baseline",
        ],
    )
    .assert()
    .success();
    workspace
}
#[test]
fn luna_trace_normalizes_usage_and_captured_tools() {
    let workspace = run(&trace(), 0);
    let dir = workspace
        .path()
        .join("iteration-1/eval-one/with_skill/run-1");
    assert_eq!(read(&dir.join("raw.json"))["result"], "done");
    assert_eq!(
        read(&dir.join("raw.json"))["messages"][0]["content"][0]["input"]["item"]["aggregated_output"],
        "captured"
    );
    assert_eq!(read(&dir.join("timing.json"))["tokens"], 150);
    assert_eq!(read(&dir.join("timing.json"))["model"], "gpt-6-luna");
    assert_eq!(read(&dir.join("grading.json"))["passed"], 1);
    assert!(dir.join("raw.jsonl").exists());
    assert_eq!(
        read(&workspace.path().join("iteration-1/benchmark.json"))["run_summary"]["with_skill"]["cost_usd"]
            ["total"],
        Value::Null
    );
}
#[test]
fn bad_traces_and_nonzero_exit_cannot_pass_verification() {
    for (trace, exit) in [
        ("not json".into(), 0),
        ("{\"type\":\"turn.started\"}".into(), 0),
        ("{\"type\":\"turn.failed\"}".into(), 0),
        (format!("{}\n{{\"type\":\"error\"}}", trace()), 0),
        (trace(), 1),
    ] {
        let workspace = run(&trace, exit);
        let dir = workspace
            .path()
            .join("iteration-1/eval-one/with_skill/run-1");
        assert_eq!(read(&dir.join("timing.json"))["outcome"], "failed");
        assert_eq!(read(&dir.join("grading.json"))["passed"], 0);
    }
}
#[test]
fn codex_judge_uses_override_model_read_only_and_rejects_failed_trace() {
    let mock = MockHarness::new();
    let skill = tempdir().unwrap();
    let workspace = tempdir().unwrap();
    write_output_skill(
        skill.path(),
        r#"{"evals":[{"id":"one","prompt":"request","assertions":["done"]}]}"#,
    );
    let cli = mock.bin_dir().join("mock-cli");
    fs::write(
        &cli,
        r#"#!/bin/bash
set -euo pipefail
printf '%s\n' "$@" >> "$ARGS"
prompt=$(cat)
if [[ "$prompt" == *'You are grading'* ]]; then cat "$JUDGE"; else cat "$MOCK_TRACE"; fi
"#,
    )
    .unwrap();
    let input = mock.root().join("input");
    fs::write(&input, trace()).unwrap();
    let judge = mock.root().join("judge");
    let passing_grade = json!({"results":[{"assertion":"done","verdict":"PASS"}]}).to_string();
    let judge_events = [
        json!({"type":"turn.started"}),
        json!({"type":"item.completed","item":{"type":"agent_message","text":passing_grade}}),
        json!({"type":"turn.failed"}),
    ];
    fs::write(
        &judge,
        judge_events
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n"),
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
            "--model",
            "run-model",
            "--judge-model",
            "judge-model",
        ],
    )
    .env("ARGS", workspace.path().join("args"))
    .env("JUDGE", judge)
    .assert()
    .success();
    let args = fs::read_to_string(workspace.path().join("args")).unwrap();
    let calls: Vec<_> = args.split("exec\n").skip(1).collect();
    assert_eq!(calls.len(), 2);
    // codex rejects --sandbox with --approve-for-me, which implies workspace-write.
    assert!(!calls[0].contains("--sandbox"));
    assert!(calls[0].contains("run-model"));
    assert!(calls[0].contains("--approve-for-me"));
    assert!(calls[1].contains("--sandbox\nread-only"));
    assert!(calls[1].contains("judge-model"));
    assert!(!calls[1].contains("--approve-for-me"));
    let dir = workspace
        .path()
        .join("iteration-1/eval-one/with_skill/run-1");
    assert_eq!(read(&dir.join("grading.json"))["passed"], 0);
    assert_eq!(read(&dir.join("grading.json"))["judge_outcome"], "failed");
    assert!(dir.join("judge-raw.jsonl").exists());
}
#[test]
fn missing_codex_never_falls_back_to_available_claude() {
    let mock = common::MockOutputClaude::new();
    let skill = tempdir().unwrap();
    write_output_skill(skill.path(), r#"{"evals":[{"prompt":"request"}]}"#);
    mock.command()
        .env("PATH", mock.root().join("bin"))
        .args(["eval", "output", skill.path().to_str().unwrap()])
        .assert()
        .failure()
        .stderr(predicates::str::contains("codex CLI is required"));
}

#[test]
fn both_configs_disable_host_and_project_skills_without_replacing_auth_home() {
    let mock = MockHarness::new();
    let skill = tempdir().unwrap();
    let workspace = tempdir().unwrap();
    let home = tempdir().unwrap();
    let codex_home = tempdir().unwrap();
    let template = tempdir().unwrap();
    write_output_skill(
        skill.path(),
        r#"{"evals":[{"id":"one","prompt":"request"}]}"#,
    );
    let host_skill = home.path().join(".agents/skills/host");
    let system_skill = codex_home.path().join("skills/.system/system");
    let project_skill = template.path().join(".agents/skills/leaked");
    for folder in [&host_skill, &system_skill, &project_skill] {
        fs::create_dir_all(folder).unwrap();
        fs::write(folder.join("SKILL.md"), "# Unrelated installed skill").unwrap();
    }
    std::os::unix::fs::symlink(&host_skill, home.path().join(".agents/skills/alias")).unwrap();
    fs::write(
        mock.bin_dir().join("mock-cli"),
        r#"#!/bin/bash
set -euo pipefail
printf 'CALL\n' >> "$ARGS"
printf '%s\n' "$@" >> "$ARGS"
printf 'AUTH_HOME=%s\n' "$CODEX_HOME" >> "$ARGS"
cat >/dev/null
cat "$MOCK_TRACE"
"#,
    )
    .unwrap();
    let input = mock.root().join("input");
    fs::write(&input, trace()).unwrap();
    mock.command(
        &input,
        0,
        [
            "eval",
            "output",
            skill.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--sandbox-dir",
            template.path().to_str().unwrap(),
        ],
    )
    .env("HOME", home.path())
    .env("CODEX_HOME", codex_home.path())
    .env("ARGS", workspace.path().join("args"))
    .assert()
    .success();
    let args = fs::read_to_string(workspace.path().join("args")).unwrap();
    let calls: Vec<_> = args.split("CALL\n").skip(1).collect();
    assert_eq!(calls.len(), 2);
    for call in calls {
        assert!(call.contains("project_doc_max_bytes=0"));
        assert!(call.contains("--ignore-user-config"));
        for feature in ["plugins", "hooks", "memories"] {
            assert!(call.contains(&format!("--disable\n{feature}\n")));
        }
        assert!(call.contains(&format!("AUTH_HOME={}\n", codex_home.path().display())));
        let disabled = call
            .lines()
            .find(|line| line.starts_with("skills.config="))
            .unwrap();
        for folder in [&host_skill, &system_skill] {
            assert!(disabled.contains(fs::canonicalize(folder).unwrap().to_str().unwrap()));
        }
        assert!(disabled.contains("/.agents/skills/leaked\",enabled=false}"));
        assert!(!disabled.contains(template.path().to_str().unwrap()));
        assert_eq!(
            disabled
                .matches(fs::canonicalize(&host_skill).unwrap().to_str().unwrap())
                .count(),
            1
        );
    }
}
