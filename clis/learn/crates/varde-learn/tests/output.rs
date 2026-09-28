//! Parity tests for `varde-learn eval output`, ported from
//! `skills/tests/output-evals.sh`: the runner's validation, sandboxing,
//! with/without-skill runs and per-run artifacts, timeout outcome
//! persistence, deterministic `verification_script` grading, the LLM judge,
//! and `benchmark.json` aggregation.
//!
//! Excluded from `// parity:` coverage: `"runner help omits a required
//! dependency"` asserts on `run-output-evals.sh --help`'s text mentioning
//! its `jq`/`claude`/`perl` dependency check — fixture plumbing specific to
//! that shell script's own `--help` output, with no equivalent dependency
//! list in this CLI (`varde-learn` only shells out to `claude`, checked via
//! `cli_available()`, not `--help` text).

mod common;

use std::path::Path;

use predicates::str::contains;
use serde_json::Value;
use tempfile::tempdir;

use common::{MockOutputClaude, write_output_skill};

fn read_json(path: &Path) -> Value {
    let text = std::fs::read_to_string(path)
        .unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|err| panic!("parse {}: {err}", path.display()))
}

fn single_eval_json(id: &str) -> String {
    format!(r#"{{"skill_name":"fixture","evals":[{{"id":"{id}","prompt":"test"}}]}}"#)
}

/// Runs a single `--no-baseline` eval with two assertions under
/// `MOCK_MODE=<mode>`, with a fixed judge verdict (first PASS, second FAIL)
/// so every mode's benchmark aggregate is graded the same way and only its
/// token/cost reporting differs. Returns `(benchmark.json, run-1
/// timing.json)`. Mirrors the `run_fixture()` helper and its shared judge
/// response in `skills/tests/output-evals.sh`.
fn run_token_mode_fixture(mode: &str) -> (Value, Value) {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(
        skill_dir.path(),
        r#"{"skill_name":"fixture","evals":[{"id":"one","prompt":"test","assertions":["first","second"]}]}"#,
    );
    let judge_response = skill_dir.path().join("judge-response.json");
    std::fs::write(
        &judge_response,
        r#"{"type":"result","subtype":"success","is_error":false,"result":"{\"results\":[{\"assertion\":\"first\",\"verdict\":\"PASS\",\"evidence\":\"yes\"},{\"assertion\":\"second\",\"verdict\":\"FAIL\",\"evidence\":\"no\"}]}"}"#,
    )
    .expect("judge response fixture");
    let workspace = tempdir().expect("tempdir");

    mock.command()
        .env("MOCK_MODE", mode)
        .env("MOCK_JUDGE_RESPONSE_FILE", &judge_response)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
        ])
        .assert()
        .success();

    let benchmark = read_json(&workspace.path().join("iteration-1/benchmark.json"));
    let timing = read_json(
        &workspace
            .path()
            .join("iteration-1/eval-one/with_skill/run-1/timing.json"),
    );
    (benchmark, timing)
}

#[test]
fn malformed_claude_output_cannot_pass_verification() {
    let mock = MockOutputClaude::new();
    let skill = tempdir().unwrap();
    write_output_skill(
        skill.path(),
        r#"{"skill_name":"fixture","evals":[{"id":"one","prompt":"test","assertions":["verified"],"verification_script":"evals/verify.sh"}]}"#,
    );
    std::fs::write(
        skill.path().join("evals/verify.sh"),
        r#"printf ran > "$VARDE_TEST_VALIDATION_MARKER"
printf '%s\n' '{"results":[{"assertion":"verified","verdict":"PASS","evidence":"always passes"}]}'
"#,
    )
    .unwrap();
    let workspace = tempdir().unwrap();
    let response = mock.root().join("response.txt");
    let marker = mock.root().join("verified");
    for (text, valid) in [
        ("invalid-json", false),
        ("", false),
        ("null", false),
        ("[]", false),
        (r#"{"result":"text"}"#, false),
        (
            r#"{"type":"result","subtype":"success","is_error":true,"result":"error"}"#,
            false,
        ),
        (
            r#"{"type":"result","subtype":"error_max_turns","is_error":false,"result":"incomplete"}"#,
            false,
        ),
        (
            r#"{"type":"result","subtype":"success","is_error":false,"result":"valid"}"#,
            true,
        ),
    ] {
        std::fs::write(&response, text).unwrap();
        mock.command()
            .env("MOCK_OUTPUT_RESPONSE_FILE", &response)
            .env("VARDE_TEST_VALIDATION_MARKER", &marker)
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
        let timing = read_json(&run.join("timing.json"));
        let grading = read_json(&run.join("grading.json"));
        assert_eq!(
            timing["outcome"],
            if valid { "completed" } else { "failed" },
            "{text}"
        );
        assert_eq!(grading["passed"], u32::from(valid), "{text}");
        assert_eq!(
            marker.exists(),
            valid,
            "invalid response must not invoke verifier"
        );
        assert_eq!(std::fs::read_to_string(run.join("raw.json")).unwrap(), text);
        if valid {
            assert!(timing["trace_error"].is_null());
        } else {
            assert!(timing["trace_error"].is_string());
        }
        std::fs::remove_dir_all(workspace.path().join("iteration-1")).unwrap();
    }
}

#[test]
fn unsuccessful_claude_judge_cannot_supply_pass_results() {
    let mock = MockOutputClaude::new();
    let skill = tempdir().unwrap();
    write_output_skill(
        skill.path(),
        r#"{"skill_name":"fixture","evals":[{"id":"one","prompt":"test","assertions":["first"]}]}"#,
    );
    let response = mock.root().join("judge.json");
    let raw = serde_json::json!({
        "type":"result","subtype":"success","is_error":true,
        "result":serde_json::json!({"results":[{"assertion":"first","verdict":"PASS","evidence":"invalid judge"}]}).to_string()
    }).to_string();
    std::fs::write(&response, &raw).unwrap();
    let workspace = tempdir().unwrap();
    mock.command()
        .env("MOCK_JUDGE_RESPONSE_FILE", &response)
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
    assert_eq!(read_json(&run.join("timing.json"))["outcome"], "completed");
    let grading = read_json(&run.join("grading.json"));
    assert_eq!(grading["judge_outcome"], "failed");
    assert_eq!(grading["passed"], 0);
    assert_eq!(
        std::fs::read_to_string(run.join("judge-raw.json")).unwrap(),
        raw
    );
}

#[test]
// parity: "measured fixture changed pass-rate reporting" (timing.json half of it — grading owns pass rate)
// parity: "measured fixture omits total tokens or retains unused timing details"
fn measured_run_writes_timing_and_transcript() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(skill_dir.path(), &single_eval_json("one"));
    let workspace = tempdir().expect("tempdir");

    mock.command()
        .env("MOCK_MODE", "measured")
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--no-baseline",
        ])
        .assert()
        .success();

    let run_dir = workspace
        .path()
        .join("iteration-1/eval-one/with_skill/run-1");
    let timing = read_json(&run_dir.join("timing.json"));
    assert_eq!(timing["duration_ms"], 1000);
    assert_eq!(timing["tokens"], 280);
    assert_eq!(timing["outcome"], "completed");
    assert_eq!(timing["exit_code"], 0);
    assert_eq!(timing["timeout_seconds"], 300);
    assert!(timing.get("usage").is_none());

    let transcript =
        std::fs::read_to_string(run_dir.join("outputs/transcript.txt")).expect("transcript");
    assert_eq!(transcript, "fixture output");
    let root_transcript =
        std::fs::read_to_string(run_dir.join("transcript.txt")).expect("root transcript");
    assert_eq!(root_transcript, "fixture output");
}

#[test]
// parity: "evaluated run did not disable installed skills"
// parity: "evaluated run did not isolate setting sources"
// parity: "evaluated run used unexpected setting sources"
// parity: "evaluated run did not enable safe automatic tools"
fn claude_args_isolate_settings_and_disable_slash_commands() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(skill_dir.path(), &single_eval_json("one"));
    let workspace = tempdir().expect("tempdir");
    let args_file = workspace.path().join("args.txt");

    mock.command()
        .env("MOCK_MODE", "measured")
        .env("MOCK_ARGS_FILE", &args_file)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--no-baseline",
        ])
        .assert()
        .success();

    let recorded = std::fs::read_to_string(&args_file).expect("args file");
    let lines: Vec<&str> = recorded.lines().collect();
    assert!(
        lines.contains(&"--disable-slash-commands"),
        "missing --disable-slash-commands: {lines:?}"
    );
    assert!(
        lines.contains(&"--setting-sources"),
        "missing --setting-sources: {lines:?}"
    );
    assert!(
        lines.contains(&"project,local"),
        "missing project,local: {lines:?}"
    );
    assert!(lines.contains(&"auto"), "missing auto: {lines:?}");
}

#[test]
// parity: "with-skill runs did not receive the skill snapshot"
// parity: "baseline runs unexpectedly received the skill snapshot"
fn with_skill_runs_receive_add_dir_baseline_does_not() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(skill_dir.path(), &single_eval_json("one"));
    let workspace = tempdir().expect("tempdir");
    let configs_file = workspace.path().join("configs.txt");

    mock.command()
        .env("MOCK_MODE", "measured")
        .env("MOCK_CONFIGS_FILE", &configs_file)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
        ])
        .assert()
        .success();

    let recorded = std::fs::read_to_string(&configs_file).expect("configs file");
    let lines: Vec<&str> = recorded.lines().collect();
    assert_eq!(lines, vec!["with_skill", "without_skill"]);
}

#[test]
// parity: "Claude cwd was not recorded"
// parity: "Claude ran from HOME instead of a sandbox"
// parity: "Claude cwd was outside the temporary directory"
// parity: "multiple eval runs reused the same sandbox cwd"
// parity: "expected four fresh Claude sandbox cwd values"
fn every_run_gets_a_fresh_sandbox_outside_home() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(skill_dir.path(), &single_eval_json("one"));
    let workspace = tempdir().expect("tempdir");
    let cwd_file = workspace.path().join("cwds.txt");

    mock.command()
        .env("MOCK_MODE", "measured")
        .env("MOCK_CWD_FILE", &cwd_file)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--runs",
            "2",
        ])
        .assert()
        .success();

    let recorded = std::fs::read_to_string(&cwd_file).expect("cwd file");
    let cwds: Vec<&str> = recorded.lines().collect();
    assert_eq!(cwds.len(), 4, "expected four fresh sandbox cwds: {cwds:?}");
    if let Ok(home) = std::env::var("HOME") {
        for cwd in &cwds {
            assert_ne!(*cwd, home, "claude ran from HOME instead of a sandbox");
        }
    }
    let unique: std::collections::HashSet<&&str> = cwds.iter().collect();
    assert_eq!(
        unique.len(),
        4,
        "a sandbox cwd was reused across runs: {cwds:?}"
    );
}

#[test]
// parity: "zero timeout succeeded"
fn timeout_seconds_zero_is_rejected() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(skill_dir.path(), &single_eval_json("one"));

    mock.command()
        .env("MOCK_MODE", "measured")
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--timeout-seconds",
            "0",
        ])
        .assert()
        .code(2)
        .stderr(contains("--timeout-seconds must be a positive integer"));
}

#[test]
fn zero_runs_is_rejected() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().unwrap();
    write_output_skill(skill_dir.path(), &single_eval_json("one"));

    mock.command()
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--runs",
            "0",
        ])
        .assert()
        .code(2)
        .stderr(contains("--runs must be a positive integer"));
}

#[test]
fn unsafe_eval_ids_are_rejected_before_model_call() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().unwrap();
    let workspace = tempdir().unwrap();
    let calls = workspace.path().join("calls.txt");

    for id in ["", ".", "..", "x/../../escape", "x\\y", "line\nbreak"] {
        let evals = serde_json::json!({
            "skill_name": "fixture",
            "evals": [{"id": id, "prompt": "test"}],
        });
        write_output_skill(skill_dir.path(), &evals.to_string());
        mock.command()
            .env("MOCK_CWD_FILE", &calls)
            .args([
                "eval",
                "output",
                "--harness",
                "claude",
                skill_dir.path().to_str().unwrap(),
                "--workspace",
                workspace.path().to_str().unwrap(),
                "--no-baseline",
            ])
            .assert()
            .code(2)
            .stderr(contains("invalid eval id"));
        assert!(!calls.exists(), "unsafe ID reached model: {id:?}");
    }
}

#[test]
fn duplicate_eval_ids_are_rejected_before_model_call() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().unwrap();
    write_output_skill(
        skill_dir.path(),
        r#"{"skill_name":"fixture","evals":[{"id":"one","prompt":"first"},{"id":"one","prompt":"second"}]}"#,
    );
    let workspace = tempdir().unwrap();
    let calls = workspace.path().join("calls.txt");

    mock.command()
        .env("MOCK_CWD_FILE", &calls)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--no-baseline",
        ])
        .assert()
        .code(2)
        .stderr(contains("duplicate eval id: one"));
    assert!(!calls.exists(), "duplicate ID reached model");
}

#[test]
// parity: "missing declared input did not abort the eval"
// parity: "missing input reached a Claude model call"
// parity: "missing input failure did not identify the eval input"
fn missing_input_file_aborts_before_model_call() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(
        skill_dir.path(),
        r#"{"skill_name":"fixture","evals":[{"id":"missing","prompt":"test","files":["absent.txt"]}]}"#,
    );
    let workspace = tempdir().expect("tempdir");
    let cwd_file = workspace.path().join("calls.txt");

    mock.command()
        .env("MOCK_MODE", "measured")
        .env("MOCK_CWD_FILE", &cwd_file)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--no-baseline",
        ])
        .assert()
        .code(2)
        .stderr(contains("input file not found for eval missing:"));

    assert!(
        !cwd_file.exists(),
        "missing input reached a Claude model call"
    );
}

#[test]
// parity: "traversal input path did not abort the eval"
// parity: "traversal input reached a Claude model call"
// parity: "traversal input failure did not identify the path boundary"
fn traversal_input_file_aborts_before_model_call() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(
        skill_dir.path(),
        r#"{"skill_name":"fixture","evals":[{"id":"traversal","prompt":"test","files":["../outside.txt"]}]}"#,
    );
    let workspace = tempdir().expect("tempdir");
    let cwd_file = workspace.path().join("calls.txt");

    mock.command()
        .env("MOCK_MODE", "measured")
        .env("MOCK_CWD_FILE", &cwd_file)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--no-baseline",
        ])
        .assert()
        .code(2)
        .stderr(contains(
            "input file not found for eval traversal must stay inside the skill directory",
        ));

    assert!(
        !cwd_file.exists(),
        "traversal input reached a Claude model call"
    );
}

#[test]
// parity: "unknown evaluation selection succeeded"
fn unknown_eval_selection_is_rejected() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(skill_dir.path(), &single_eval_json("one"));

    mock.command()
        .env("MOCK_MODE", "measured")
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--eval",
            "missing",
            "--no-baseline",
        ])
        .assert()
        .code(2)
        .stderr(contains("evaluation not found: missing"));
}

#[test]
// parity: "evaluation selection ran an unselected case"
// parity: "evaluation selection skipped the requested case"
// parity: "repeatable evaluation selection omitted a requested case"
fn eval_selection_runs_only_requested_cases() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(
        skill_dir.path(),
        r#"{"skill_name":"fixture","evals":[{"id":"one","prompt":"test"},{"id":"two","prompt":"test"}]}"#,
    );

    let single_workspace = tempdir().expect("tempdir");
    mock.command()
        .env("MOCK_MODE", "measured")
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            single_workspace.path().to_str().unwrap(),
            "--eval",
            "two",
            "--no-baseline",
        ])
        .assert()
        .success();
    assert!(
        !single_workspace
            .path()
            .join("iteration-1/eval-one")
            .exists()
    );
    assert!(
        single_workspace
            .path()
            .join("iteration-1/eval-two/with_skill/run-1/timing.json")
            .exists()
    );

    let multi_workspace = tempdir().expect("tempdir");
    mock.command()
        .env("MOCK_MODE", "measured")
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            multi_workspace.path().to_str().unwrap(),
            "--eval",
            "one",
            "--eval",
            "two",
            "--no-baseline",
        ])
        .assert()
        .success();
    assert!(
        multi_workspace
            .path()
            .join("iteration-1/eval-one/with_skill/run-1/timing.json")
            .exists()
    );
    assert!(
        multi_workspace
            .path()
            .join("iteration-1/eval-two/with_skill/run-1/timing.json")
            .exists()
    );
}

#[test]
// parity: "evaluated timeout evidence is missing"
// parity: "evaluated timeout is not distinguished from grading failures"
// parity: "benchmark summary omits evaluated timeouts"
fn timed_out_run_persists_outcome_and_conventional_exit_code() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(
        skill_dir.path(),
        r#"{"skill_name":"fixture","evals":[{"id":"one","prompt":"test","assertions":["first","second"]}]}"#,
    );
    let workspace = tempdir().expect("tempdir");

    mock.command()
        .env("MOCK_MODE", "measured")
        .env("MOCK_TIMEOUT", "1")
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--timeout-seconds",
            "1",
            "--no-baseline",
        ])
        .assert()
        .success();

    let run_dir = workspace
        .path()
        .join("iteration-1/eval-one/with_skill/run-1");
    let timing = read_json(&run_dir.join("timing.json"));
    assert_eq!(timing["outcome"], "timed_out");
    assert_eq!(timing["exit_code"], 142);
    assert_eq!(timing["timeout_seconds"], 1);

    let grading = read_json(&run_dir.join("grading.json"));
    assert_eq!(grading["run_outcome"], "timed_out");
    assert_eq!(grading["passed"], 0);
    assert_eq!(grading["total"], 2);
    for result in grading["results"].as_array().expect("results array") {
        assert_eq!(result["verdict"], "FAIL");
        assert_eq!(
            result["evidence"],
            "Evaluated run timed out after 1 seconds"
        );
    }

    let benchmark = read_json(&workspace.path().join("iteration-1/benchmark.json"));
    assert_eq!(
        benchmark["run_summary"]["with_skill"]["outcomes"]["timed_out"],
        1
    );
}

#[test]
// parity: "evaluated timeout left a surviving descendant"
fn evaluated_timeout_leaves_no_surviving_descendant() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(skill_dir.path(), &single_eval_json("one"));
    let workspace = tempdir().expect("tempdir");
    let marker = workspace.path().join("descendant-marker");

    mock.command()
        .env("MOCK_MODE", "measured")
        .env("MOCK_TIMEOUT", "1")
        .env("MOCK_DESCENDANT_MARKER", &marker)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--timeout-seconds",
            "1",
            "--no-baseline",
        ])
        .assert()
        .success();

    std::thread::sleep(std::time::Duration::from_secs(2));
    assert!(
        !marker.exists(),
        "evaluated timeout left a surviving descendant"
    );
}

#[test]
// parity: "judge timeout aborted the runner"
// parity: "judge timeout evidence is missing"
// parity: "benchmark summary omits judge timeouts"
fn judge_timeout_does_not_abort_the_runner() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(
        skill_dir.path(),
        r#"{"skill_name":"fixture","evals":[{"id":"one","prompt":"test","assertions":["first"]}]}"#,
    );
    let workspace = tempdir().expect("tempdir");

    mock.command()
        .env("MOCK_MODE", "measured")
        .env("MOCK_JUDGE_TIMEOUT", "1")
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--timeout-seconds",
            "1",
            "--no-baseline",
        ])
        .assert()
        .success();

    let run_dir = workspace
        .path()
        .join("iteration-1/eval-one/with_skill/run-1");
    let grading = read_json(&run_dir.join("grading.json"));
    assert_eq!(grading["run_outcome"], "completed");
    assert_eq!(grading["judge_outcome"], "timed_out");

    let benchmark = read_json(&workspace.path().join("iteration-1/benchmark.json"));
    assert_eq!(
        benchmark["run_summary"]["with_skill"]["outcomes"]["judge_timed_out"],
        1
    );
}

#[test]
// parity: "deterministic and judge results were not merged"
// parity: "filesystem verification evidence was not preserved"
// parity: "baseline did not run with setup and verification scripts"
// parity: "baseline verification evidence was not preserved"
// parity: "judge received deterministic assertions"
// parity: "judge raw output was not preserved"
// parity: "sandbox template state leaked between runs"
// parity: "repeated deterministic runs were not aggregated"
fn verification_script_and_judge_results_are_merged_across_repeated_runs_and_baseline() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    std::fs::create_dir_all(skill_dir.path().join("evals/scripts")).expect("mkdir scripts");
    std::fs::write(skill_dir.path().join("SKILL.md"), "# Fixture skill\n").expect("SKILL.md");
    std::fs::write(
        skill_dir.path().join("evals/evals.json"),
        r#"{"skill_name":"fixture","evals":[{"id":"verified","prompt":"test deterministic grading","assertions":["filesystem artifact exists","transcript assertion passes"],"verification_script":"evals/scripts/verify.sh"}]}"#,
    )
    .expect("evals.json");
    std::fs::write(
        skill_dir.path().join("evals/scripts/verify.sh"),
        "#!/usr/bin/env bash\n\
         set -euo pipefail\n\
         if [ -f filesystem-artifact.txt ]; then\n\
         printf '%s\\n' '{\"results\":[{\"assertion\":\"filesystem artifact exists\",\"verdict\":\"PASS\",\"evidence\":\"filesystem-artifact.txt exists\"}]}'\n\
         else\n\
         printf '%s\\n' '{\"results\":[{\"assertion\":\"filesystem artifact exists\",\"verdict\":\"FAIL\",\"evidence\":\"filesystem-artifact.txt is missing\"}]}'\n\
         fi\n",
    )
    .expect("verify.sh");

    let judge_response = skill_dir.path().join("judge-response.json");
    std::fs::write(
        &judge_response,
        r#"{"type":"result","subtype":"success","is_error":false,"result":"{\"results\":[{\"assertion\":\"transcript assertion passes\",\"verdict\":\"PASS\",\"evidence\":\"fixture output\"}]}"}"#,
    )
    .expect("judge response fixture");

    let workspace = tempdir().expect("tempdir");
    mock.command()
        .env("MOCK_MODE", "verify")
        .env("MOCK_JUDGE_RESPONSE_FILE", &judge_response)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--runs",
            "2",
        ])
        .assert()
        .success();

    for run in [1, 2] {
        for cfg in ["with_skill", "without_skill"] {
            let run_dir = workspace
                .path()
                .join(format!("iteration-1/eval-verified/{cfg}/run-{run}"));
            let grading = read_json(&run_dir.join("grading.json"));
            assert_eq!(grading["total"], 2, "{cfg} run {run}");
            assert_eq!(grading["passed"], 2, "{cfg} run {run}");
            assert_eq!(
                grading["results"]
                    .as_array()
                    .expect("results array")
                    .iter()
                    .map(|r| r["assertion"].as_str().unwrap_or_default())
                    .collect::<Vec<_>>(),
                vec!["filesystem artifact exists", "transcript assertion passes"],
                "{cfg} run {run}"
            );

            let verification = read_json(&run_dir.join("verification.json"));
            assert_eq!(
                verification["results"][0]["verdict"], "PASS",
                "{cfg} run {run}"
            );

            let judge_grading = read_json(&run_dir.join("judge-grading.json"));
            assert_eq!(
                judge_grading["results"],
                serde_json::json!([{
                    "assertion": "transcript assertion passes",
                    "verdict": "PASS",
                    "evidence": "fixture output",
                }]),
                "{cfg} run {run}: judge received deterministic assertions"
            );
            assert!(
                run_dir.join("judge-raw.json").exists(),
                "{cfg} run {run}: judge raw output was not preserved"
            );
        }
    }

    let benchmark = read_json(&workspace.path().join("iteration-1/benchmark.json"));
    assert_eq!(benchmark["run_summary"]["with_skill"]["runs"], 2);
}

#[test]
// coverage: --sandbox-dir input validation (not exercised as a `fail "..."`
// case in skills/tests/output-evals.sh, which only ever passes a valid
// standalone template).
fn sandbox_dir_must_exist_and_must_not_be_a_linked_worktree() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    write_output_skill(skill_dir.path(), &single_eval_json("one"));

    mock.command()
        .env("MOCK_MODE", "measured")
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--sandbox-dir",
            "/nonexistent/sandbox/dir/for/test",
            "--no-baseline",
        ])
        .assert()
        .code(2)
        .stderr(contains("sandbox dir not found"));

    let worktree_like = tempdir().expect("tempdir");
    std::fs::write(worktree_like.path().join(".git"), "gitdir: /elsewhere\n")
        .expect("write .git file");
    mock.command()
        .env("MOCK_MODE", "measured")
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--sandbox-dir",
            worktree_like.path().to_str().unwrap(),
            "--no-baseline",
        ])
        .assert()
        .code(2)
        .stderr(contains("not a linked worktree"));
}

#[test]
// parity: cp -R preserves symlinks
fn sandbox_dir_symlinks_are_preserved_not_followed() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    std::fs::create_dir_all(skill_dir.path().join("evals/scripts")).expect("mkdir scripts");
    std::fs::write(skill_dir.path().join("SKILL.md"), "# Fixture skill\n").expect("SKILL.md");
    std::fs::write(
        skill_dir.path().join("evals/evals.json"),
        r#"{"skill_name":"fixture","evals":[{"id":"verified","prompt":"test","setup_script":"evals/scripts/setup.sh"}]}"#,
    )
    .expect("evals.json");
    std::fs::write(
        skill_dir.path().join("evals/scripts/setup.sh"),
        "#!/usr/bin/env bash\n\
         set -euo pipefail\n\
         [[ -L linked-dir ]]\n\
         [[ -L linked-file.txt ]]\n\
         [[ -d linked-dir ]]\n\
         [[ -f linked-file.txt ]]\n\
         printf setup-ok > \"$EVAL_RUN_DIR/setup-marker.txt\"\n",
    )
    .expect("setup.sh");

    let sandbox_template = tempdir().expect("tempdir");
    let real_dir = sandbox_template.path().join("real-dir");
    std::fs::create_dir_all(&real_dir).expect("mkdir real-dir");
    std::fs::write(real_dir.join("inside.txt"), "inside").expect("write inside.txt");
    let real_file = sandbox_template.path().join("real-file.txt");
    std::fs::write(&real_file, "real").expect("write real-file.txt");
    std::os::unix::fs::symlink(&real_dir, sandbox_template.path().join("linked-dir"))
        .expect("symlink dir");
    std::os::unix::fs::symlink(&real_file, sandbox_template.path().join("linked-file.txt"))
        .expect("symlink file");

    let workspace = tempdir().expect("tempdir");
    mock.command()
        .env("MOCK_MODE", "measured")
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--sandbox-dir",
            sandbox_template.path().to_str().unwrap(),
            "--no-baseline",
        ])
        .assert()
        .success();

    let run_dir = workspace
        .path()
        .join("iteration-1/eval-verified/with_skill/run-1");
    let marker = std::fs::read_to_string(run_dir.join("setup-marker.txt")).expect("setup marker");
    assert_eq!(marker, "setup-ok");
}

#[test]
// parity: "deterministic and judge results were not merged" (setup_script
// half — this task ports `setup_script` execution, not verification/judge
// merging, which `eval-output-grading` owns)
// parity: "sandbox template state leaked between runs"
fn setup_script_seeds_sandbox_from_template_and_runs_before_model_call() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    std::fs::create_dir_all(skill_dir.path().join("evals/scripts")).expect("mkdir scripts");
    std::fs::write(skill_dir.path().join("SKILL.md"), "# Fixture skill\n").expect("SKILL.md");
    std::fs::write(skill_dir.path().join("seeded.txt"), "declared-input").expect("seeded.txt");
    std::fs::write(
        skill_dir.path().join("evals/evals.json"),
        r#"{"skill_name":"fixture","evals":[{"id":"verified","prompt":"test","files":["seeded.txt"],"setup_script":"evals/scripts/setup.sh"}]}"#,
    )
    .expect("evals.json");
    std::fs::write(
        skill_dir.path().join("evals/scripts/setup.sh"),
        "#!/usr/bin/env bash\n\
         set -euo pipefail\n\
         [[ \"$EVAL_ID\" == verified ]]\n\
         [[ -f seeded.txt ]]\n\
         [[ \"$(cat seeded.txt)\" == declared-input ]]\n\
         [[ -f template-input.txt ]]\n\
         [[ ! -f prior-run.txt ]]\n\
         [[ -f \"$EVAL_SKILL_DIR/evals/evals.json\" ]]\n\
         printf done > prior-run.txt\n\
         printf setup-ok > \"$EVAL_RUN_DIR/setup-marker.txt\"\n",
    )
    .expect("setup.sh");

    let sandbox_template = tempdir().expect("tempdir");
    std::fs::write(
        sandbox_template.path().join("template-input.txt"),
        "template",
    )
    .expect("template file");

    let workspace = tempdir().expect("tempdir");
    let cwd_file = workspace.path().join("cwds.txt");
    mock.command()
        .env("MOCK_MODE", "measured")
        .env("MOCK_CWD_FILE", &cwd_file)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--sandbox-dir",
            sandbox_template.path().to_str().unwrap(),
            "--runs",
            "2",
            "--no-baseline",
        ])
        .assert()
        .success();

    for run in [1, 2] {
        let run_dir = workspace
            .path()
            .join(format!("iteration-1/eval-verified/with_skill/run-{run}"));
        let marker = std::fs::read_to_string(run_dir.join("setup-marker.txt"))
            .unwrap_or_else(|err| panic!("run {run} setup marker: {err}"));
        assert_eq!(marker, "setup-ok");
        assert!(run_dir.join("setup.txt").exists());
    }
    let calls = std::fs::read_to_string(&cwd_file).expect("cwd file");
    assert_eq!(calls.lines().count(), 2, "both runs should reach claude");
}

#[test]
// coverage: `setup_script` failure aborts the run before the model call
// (not covered by an existing `output-evals.sh` fail string).
fn setup_script_failure_aborts_before_model_call() {
    let mock = MockOutputClaude::new();
    let skill_dir = tempdir().expect("tempdir");
    std::fs::create_dir_all(skill_dir.path().join("evals/scripts")).expect("mkdir scripts");
    std::fs::write(skill_dir.path().join("SKILL.md"), "# Fixture skill\n").expect("SKILL.md");
    std::fs::write(
        skill_dir.path().join("evals/evals.json"),
        r#"{"skill_name":"fixture","evals":[{"id":"one","prompt":"test","setup_script":"evals/scripts/setup.sh"}]}"#,
    )
    .expect("evals.json");
    std::fs::write(
        skill_dir.path().join("evals/scripts/setup.sh"),
        "#!/usr/bin/env bash\nexit 1\n",
    )
    .expect("setup.sh");

    let workspace = tempdir().expect("tempdir");
    let cwd_file = workspace.path().join("calls.txt");
    mock.command()
        .env("MOCK_MODE", "measured")
        .env("MOCK_CWD_FILE", &cwd_file)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill_dir.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--no-baseline",
        ])
        .assert()
        .code(2)
        .stderr(contains(
            "setup_script failed for eval one, with_skill run 1",
        ));

    assert!(!cwd_file.exists(), "setup_script failure reached claude");
    assert!(
        workspace
            .path()
            .join("iteration-1/eval-one/with_skill/run-1/setup.txt")
            .exists(),
        "setup.txt should be written even when setup_script fails"
    );
}

#[test]
// parity: "measured fixture changed pass-rate reporting"
// parity: "measured fixture changed timing reporting"
// parity: "measured fixture changed baseline reporting"
// parity: "measured fixture changed delta reporting"
// parity: "measured fixture omits aggregate cost"
// parity: "measured fixture omits successful assertion totals"
// parity: "measured fixture reports incorrect token efficiency"
// parity: "measured fixture changed token reporting"
fn measured_fixture_aggregates_pass_rate_tokens_cost_and_efficiency() {
    let (benchmark, _timing) = run_token_mode_fixture("measured");
    let with_skill = &benchmark["run_summary"]["with_skill"];
    assert_eq!(with_skill["pass_rate"]["mean"], 0.5);
    assert_eq!(with_skill["tokens"]["mean"], 280.0);
    assert_eq!(with_skill["time_seconds"]["mean"], 1.0);
    assert_eq!(
        with_skill["cost_usd"],
        serde_json::json!({"mean": 0.25, "total": 0.25, "measured_runs": 1})
    );
    assert_eq!(with_skill["successful_assertions"]["total"], 1);
    assert_eq!(
        with_skill["token_efficiency"]["successful_assertions_per_1000_tokens"],
        3.5714
    );
    assert_eq!(with_skill["token_efficiency"]["status"], "measured");

    let without_skill = &benchmark["run_summary"]["without_skill"];
    assert_eq!(without_skill["pass_rate"]["mean"], 0.5);

    let delta = &benchmark["run_summary"]["delta"];
    assert_eq!(delta["pass_rate"], 0.0);
    assert_eq!(delta["tokens"], 0.0);
    assert_eq!(delta["time_seconds"], 0.0);
    assert_eq!(delta["cost_usd"], 0.0);
}

#[test]
// parity: "unavailable fixture does not report missing token usage"
// parity: "unavailable fixture reports misleading token efficiency"
fn unavailable_fixture_aggregates_tokens_and_efficiency_as_unavailable() {
    let (benchmark, _timing) = run_token_mode_fixture("unavailable");
    let with_skill = &benchmark["run_summary"]["with_skill"];
    assert_eq!(
        with_skill["tokens"],
        serde_json::json!({"mean": null, "total": null, "measured_runs": 0, "unavailable_runs": 1})
    );
    assert_eq!(
        with_skill["token_efficiency"],
        serde_json::json!({"status": "unavailable", "successful_assertions_per_1000_tokens": null})
    );
}

#[test]
// parity: "zero fixture is not retained as measured usage"
// parity: "zero token usage is not distinguished in per-run timing"
// parity: "zero fixture is not distinguished from unavailable usage"
fn zero_fixture_is_retained_as_measured_usage_but_zero_efficiency() {
    let (benchmark, timing) = run_token_mode_fixture("zero");
    let with_skill = &benchmark["run_summary"]["with_skill"];
    assert_eq!(
        with_skill["tokens"],
        serde_json::json!({"mean": 0.0, "total": 0, "measured_runs": 1, "unavailable_runs": 0})
    );
    assert_eq!(timing["tokens"], 0);
    assert!(timing.get("usage").is_none());
    assert!(timing.get("cost_usd").is_none());
    assert_eq!(
        with_skill["token_efficiency"],
        serde_json::json!({"status": "zero_tokens", "successful_assertions_per_1000_tokens": null})
    );
}

#[test]
// parity: "null token fields are not reported as unavailable"
// parity: "null token usage is not distinguished in per-run timing"
// parity: "null token fields report misleading token efficiency"
fn null_token_fixture_is_reported_as_unavailable() {
    let (benchmark, timing) = run_token_mode_fixture("null");
    let with_skill = &benchmark["run_summary"]["with_skill"];
    assert_eq!(
        with_skill["tokens"],
        serde_json::json!({"mean": null, "total": null, "measured_runs": 0, "unavailable_runs": 1})
    );
    assert!(timing["tokens"].is_null());
    assert!(timing.get("usage").is_none());
    assert!(timing.get("cost_usd").is_none());
    assert_eq!(
        with_skill["token_efficiency"],
        serde_json::json!({"status": "unavailable", "successful_assertions_per_1000_tokens": null})
    );
}

#[test]
// parity: "failed agent output aborts unavailable usage reporting"
// parity: "failed agent output retains unused timing details"
fn failed_agent_output_aggregates_tokens_as_unavailable() {
    let (benchmark, timing) = run_token_mode_fixture("fail");
    let with_skill = &benchmark["run_summary"]["with_skill"];
    assert_eq!(
        with_skill["tokens"],
        serde_json::json!({"mean": null, "total": null, "measured_runs": 0, "unavailable_runs": 1})
    );
    assert!(timing["tokens"].is_null());
    assert!(timing.get("usage").is_none());
    assert!(timing.get("cost_usd").is_none());
}
