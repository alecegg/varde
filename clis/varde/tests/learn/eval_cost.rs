use assert_cmd::Command;
use crate::common::{MockHarness, write_output_skill};
use serde_json::{Value, json};
use std::{fs, os::unix::fs::PermissionsExt, path::Path};
use tempfile::tempdir;

fn read(path: &Path) -> Value {
    serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
}

#[test]
fn collects_cost_and_tokens_from_evaluated_and_judge_traces() {
    let mock = MockHarness::new();
    let skill = tempdir().unwrap();
    let workspace = tempdir().unwrap();
    write_output_skill(
        skill.path(),
        r#"{"evals":[{"id":"one","prompt":"request","assertions":["done"]}]}"#,
    );
    let trace = mock.root().join("trace");
    let events = [
        json!({"type":"turn.started"}),
        json!({"type":"item.completed","item":{"type":"agent_message","text":"{\"results\":[{\"assertion\":\"done\",\"verdict\":\"PASS\",\"evidence\":\"yes\"}] }"}}),
        json!({"type":"turn.completed","usage":{"input_tokens":12,"cached_input_tokens":5,"output_tokens":7,"total_tokens":19,"total_cost_usd":0.012}}),
    ];
    fs::write(
        &trace,
        events
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n"),
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
            "--no-baseline",
        ],
    )
    .assert()
    .success();

    let benchmark = read(&workspace.path().join("iteration-1/benchmark.json"));
    let cost = &benchmark["result"]["runs"][0]["cost"];
    assert_eq!(cost["evaluated"], 0.012);
    assert_eq!(cost["judge"], 0.012);
    assert_eq!(cost["tokens"]["evaluated"], 19);
    assert_eq!(cost["tokens"]["judge"], 19);
}

#[test]
fn missing_trace_usage_is_unavailable_not_zero() {
    let mock = MockHarness::new();
    let skill = tempdir().unwrap();
    let workspace = tempdir().unwrap();
    write_output_skill(
        skill.path(),
        r#"{"evals":[{"id":"one","prompt":"request","assertions":[]}] }"#,
    );
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
            "--no-baseline",
        ],
    )
    .assert()
    .success();
    let benchmark = read(&workspace.path().join("iteration-1/benchmark.json"));
    let cost = &benchmark["result"]["runs"][0]["cost"];
    assert_eq!(cost["evaluated"], "unavailable");
    assert_eq!(cost["tokens"]["evaluated"], "unavailable");
}

#[test]
fn collects_claude_usage_from_json_traces() {
    let root = tempdir().unwrap();
    let bin = root.path().join("bin");
    fs::create_dir_all(&bin).unwrap();
    let skill = root.path().join("skill");
    fs::create_dir_all(&skill).unwrap();
    fs::write(skill.join("SKILL.md"), "---\nname: skill\ndescription: Test skill.\n---\n# Test skill\n").unwrap();
    fs::create_dir_all(skill.join("evals")).unwrap();
    fs::write(
        skill.join("evals/evals.json"),
        r#"{"evals":[{"id":"one","prompt":"request","assertions":["done"]}]}"#,
    )
    .unwrap();
    let eval_trace = root.path().join("evaluated.json");
    fs::write(
        &eval_trace,
        json!({"type":"result","subtype":"success","is_error":false,"result":"done","usage":{"input_tokens":10,"output_tokens":4},"total_cost_usd":0.02}).to_string(),
    )
    .unwrap();
    let judge_trace = root.path().join("judge.json");
    fs::write(
        &judge_trace,
        json!({"type":"result","subtype":"success","is_error":false,"result":"{\"results\":[{\"assertion\":\"done\",\"verdict\":\"PASS\",\"evidence\":\"yes\"}]}","usage":{"input_tokens":6,"output_tokens":3},"total_cost_usd":0.01}).to_string(),
    )
    .unwrap();
    let script = bin.join("claude");
    fs::write(
        &script,
        format!(
            "#!/bin/sh\ncase \"$2\" in *'You are grading'*) /bin/cat '{}' ;; *) /bin/cat '{}' ;; esac\n",
            judge_trace.display(),
            eval_trace.display()
        ),
    )
    .unwrap();
    let mut permissions = fs::metadata(&script).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&script, permissions).unwrap();
    let workspace = root.path().join("workspace");
    Command::cargo_bin("varde")
        .unwrap()
        .args([
            "learn",
            "eval",
            "output",
            skill.to_str().unwrap(),
            "--harness",
            "claude",
            "--workspace",
        ])
        .arg(&workspace)
        .args(["--no-baseline"])
        .env("PATH", &bin)
        .assert()
        .success();

    let benchmark = read(&workspace.join("iteration-1/benchmark.json"));
    assert_eq!(benchmark["harness"], "claude");
    let cost = &benchmark["result"]["runs"][0]["cost"];
    assert_eq!(cost["evaluated"], 0.02);
    assert_eq!(cost["judge"], 0.01);
    assert_eq!(cost["tokens"]["evaluated"], 14);
    assert_eq!(cost["tokens"]["judge"], 9);
}
