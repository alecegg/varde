//! Parity tests for `varde-learn eval trigger`, ported from
//! `skills/tests/trigger-evals.sh` for the claude, codex, and opencode
//! harnesses.

mod common;

use std::path::Path;
use std::time::{Duration, Instant};

use assert_cmd::Command;
use predicates::prelude::PredicateBooleanExt;
use predicates::str::contains;

use common::{MockHarness, write_queries, write_trace};

const HARNESSES: [&str; 3] = ["claude", "opencode", "codex"];

/// Full `eval trigger` args for `harness`, adding `--skill-path` (pointing
/// at `mock`'s fixture skill file) when the harness is codex.
fn trigger_args(mock: &MockHarness, harness: &str, queries: &Path, runs: &str) -> Vec<String> {
    let mut args = vec![
        "eval".to_string(),
        "trigger".to_string(),
        "fixture-skill".to_string(),
        queries.to_str().unwrap().to_string(),
        "--harness".to_string(),
        harness.to_string(),
        "--runs".to_string(),
        runs.to_string(),
    ];
    if harness == "codex" {
        args.push("--skill-path".to_string());
        args.push(mock.skill_path().to_str().unwrap().to_string());
    }
    args
}

fn process_group_alive(pgid: i32) -> bool {
    std::process::Command::new("sh")
        .arg("-c")
        .arg(format!("kill -0 -{pgid} 2>/dev/null"))
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

#[test]
fn timeout_kills_hanging_harness_process_group() {
    let mock = MockHarness::new();
    std::fs::write(
        mock.bin_dir().join("mock-cli"),
        "#!/bin/bash\necho $$ > \"$MOCK_PGID_FILE\"\nsleep 30 &\nwait\n",
    )
    .expect("write hanging mock");
    let pgid_file = mock.root().join("pgid");
    let queries = write_queries(mock.root(), true);
    let mut args = trigger_args(&mock, "claude", &queries, "1");
    args.extend(["--timeout-seconds".to_string(), "1".to_string()]);

    let started = Instant::now();
    mock.command(&mock.root().join("unused-trace.jsonl"), 0, args)
        .env("MOCK_PGID_FILE", &pgid_file)
        .assert()
        .code(2)
        .stderr(contains("claude CLI timed out after 1 seconds for query 1"));
    assert!(
        started.elapsed() < Duration::from_secs(5),
        "harness did not respect its one-second deadline"
    );

    let pgid: i32 = std::fs::read_to_string(&pgid_file)
        .expect("harness wrote its process-group id")
        .trim()
        .parse()
        .expect("process-group id is numeric");
    let cleanup_deadline = Instant::now() + Duration::from_secs(2);
    while process_group_alive(pgid) && Instant::now() < cleanup_deadline {
        std::thread::sleep(Duration::from_millis(10));
    }
    assert!(
        !process_group_alive(pgid),
        "timed-out harness process group {pgid} still has a live member"
    );
}

#[test]
fn trigger_timeout_must_be_positive() {
    let mock = MockHarness::new();
    let queries = write_queries(mock.root(), true);
    let mut args = trigger_args(&mock, "claude", &queries, "1");
    args.extend(["--timeout-seconds".to_string(), "0".to_string()]);

    mock.command(&mock.root().join("unused-trace.jsonl"), 0, args)
        .assert()
        .code(2)
        .stderr(contains("--timeout-seconds must be a positive integer"));
}

#[test]
// parity: fail "$harness $scenario expected pass, got $status: $(cat "$err")"
// parity: fail "$harness $scenario summary was wrong"
fn hit_true_passes() {
    for harness in HARNESSES {
        let mock = MockHarness::new();
        let skill_path = mock.skill_path();
        let trace = write_trace(mock.root(), harness, "hit", Some(&skill_path));
        let queries = write_queries(mock.root(), true);
        mock.command(&trace, 0, trigger_args(&mock, harness, &queries, "1"))
            .assert()
            .success()
            .stdout(contains("evals: pass=1 fail=0"));
    }
}

#[test]
fn large_valid_trace_preserves_hit_classification() {
    let mock = MockHarness::new();
    let trace = mock.root().join("large-claude.jsonl");
    let padding = "{\"type\":\"system\"}\n".repeat(10_000);
    let skill_event = r#"{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"fixture-skill"}}]}}"#;
    let result_event = r#"{"type":"result","subtype":"success","is_error":false}"#;
    std::fs::write(&trace, format!("{padding}{skill_event}\n{result_event}\n"))
        .expect("write large trace");
    let queries = write_queries(mock.root(), true);

    mock.command(&trace, 0, trigger_args(&mock, "claude", &queries, "1"))
        .assert()
        .success()
        .stdout(contains("evals: pass=1 fail=0"));
}

#[test]
fn oversized_harness_trace_is_rejected_with_size_limit() {
    let mock = MockHarness::new();
    let trace = mock.root().join("oversized-claude.jsonl");
    let mut file = std::fs::File::create(&trace).expect("create trace");
    let chunk = vec![b'x'; 8 * 1024];
    for _ in 0..(16 * 1024 * 1024 / chunk.len() + 1) {
        std::io::Write::write_all(&mut file, &chunk).expect("write oversized trace");
    }
    let queries = write_queries(mock.root(), true);

    mock.command(&trace, 0, trigger_args(&mock, "claude", &queries, "1"))
        .assert()
        .code(2)
        .stderr(contains("trace exceeded the 16 MiB limit"));
}

#[test]
fn oversized_harness_stderr_is_rejected_with_size_limit() {
    let mock = MockHarness::new();
    std::fs::write(
        mock.bin_dir().join("mock-cli"),
        "#!/bin/bash\nset -euo pipefail\ncat \"$MOCK_TRACE\" >&2\n",
    )
    .expect("write stderr mock");
    let trace = mock.root().join("oversized-stderr.txt");
    std::fs::write(&trace, vec![b'x'; 64 * 1024 + 1]).expect("write oversized stderr");
    let queries = write_queries(mock.root(), true);

    mock.command(&trace, 0, trigger_args(&mock, "claude", &queries, "1"))
        .assert()
        .code(2)
        .stderr(contains("Claude CLI stderr exceeded the 64 KiB limit"));
}

#[test]
fn closed_harness_pipes_still_wait_for_process_exit() {
    let mock = MockHarness::new();
    std::fs::write(
        mock.bin_dir().join("mock-cli"),
        "#!/bin/bash\nexec 1>&- 2>&-\nsleep 0.1\n",
    )
    .expect("write delayed mock");
    let trace = mock.root().join("unused-trace.jsonl");
    let queries = write_queries(mock.root(), true);

    mock.command(&trace, 0, trigger_args(&mock, "claude", &queries, "1"))
        .assert()
        .code(2)
        .stderr(contains("unusable Claude trace"));
}

#[test]
// parity: fail "$harness $scenario expected pass, got $status: $(cat "$err")"
// parity: fail "$harness $scenario summary was wrong"
fn miss_false_passes() {
    for harness in HARNESSES {
        let mock = MockHarness::new();
        let skill_path = mock.skill_path();
        let trace = write_trace(mock.root(), harness, "miss", Some(&skill_path));
        let queries = write_queries(mock.root(), false);
        mock.command(&trace, 0, trigger_args(&mock, harness, &queries, "1"))
            .assert()
            .success()
            .stdout(contains("evals: pass=1 fail=0"));
    }
}

#[test]
// parity: fail "$harness $scenario expected scored fail, got $status"
// parity: fail "$harness $scenario miss was not scored"
fn miss_true_scores_fail() {
    for harness in HARNESSES {
        let mock = MockHarness::new();
        let skill_path = mock.skill_path();
        let trace = write_trace(mock.root(), harness, "miss", Some(&skill_path));
        let queries = write_queries(mock.root(), true);
        mock.command(&trace, 0, trigger_args(&mock, harness, &queries, "1"))
            .assert()
            .code(1)
            .stdout(contains("evals: pass=0 fail=1"))
            .stdout(contains("FAIL [harness="));
    }
}

#[test]
// parity: fail "$harness $scenario expected trace rejection, got $status"
// parity: fail "$harness $scenario rejection was not explained"
// parity: fail "$harness $scenario leaked a Python traceback instead of a clean error"
fn unusable_traces_reject_with_exit_2() {
    for harness in HARNESSES {
        for scenario in ["invalid", "unknown", "auth", "incomplete"] {
            let mock = MockHarness::new();
            let skill_path = mock.skill_path();
            let trace = write_trace(mock.root(), harness, scenario, Some(&skill_path));
            let queries = write_queries(mock.root(), true);
            mock.command(&trace, 0, trigger_args(&mock, harness, &queries, "1"))
                .assert()
                .code(2)
                .stderr(contains("error:"))
                .stderr(contains("Traceback (most recent call last)").not())
                .stderr(contains("NameError").not());
        }
    }
}

#[test]
// parity: fail "$harness $scenario expected trace rejection, got $status"
// parity: fail "$harness $scenario rejection was not explained"
fn nonzero_cli_exit_rejects_with_exit_2() {
    for harness in HARNESSES {
        let mock = MockHarness::new();
        let skill_path = mock.skill_path();
        let trace = write_trace(mock.root(), harness, "hit", Some(&skill_path));
        let queries = write_queries(mock.root(), true);
        mock.command(&trace, 7, trigger_args(&mock, harness, &queries, "1"))
            .assert()
            .code(2)
            .stderr(contains("error:"));
    }
}

#[test]
// parity: fail "runner accepted an implicit harness"
// parity: fail "missing --harness diagnostic was unclear"
fn missing_harness_exits_2_with_diagnostic() {
    let mock = MockHarness::new();
    let queries = write_queries(mock.root(), true);
    Command::cargo_bin("varde-learn")
        .unwrap()
        .env("PATH", mock.path_with_mock())
        .args([
            "eval",
            "trigger",
            "fixture-skill",
            queries.to_str().unwrap(),
            "--runs",
            "1",
        ])
        .assert()
        .code(2)
        .stderr(contains("--harness"));
}

#[test]
// parity: fail "help omitted the required harness flag"
fn trigger_help_mentions_harness_flag() {
    Command::cargo_bin("varde-learn")
        .unwrap()
        .args(["eval", "trigger", "--help"])
        .assert()
        .success()
        .stdout(contains("--harness"));
}

#[test]
// parity: fail "help omitted the Codex proxy limitation"
fn eval_help_mentions_codex_proxy_limitation() {
    Command::cargo_bin("varde-learn")
        .unwrap()
        .args(["eval", "--help"])
        .assert()
        .success()
        .stdout(contains("Codex"));
}

/// Not ported from the shell tests directly: `--skill-path` is a Codex-only
/// flag there (the shell runner has no equivalent claude/opencode case).
/// This is a task requirement (see eval-trigger-claude-opencode.md), not a
/// shell parity port.
#[test]
fn skill_path_is_rejected_for_claude_and_opencode() {
    for harness in ["claude", "opencode"] {
        let mock = MockHarness::new();
        let trace = write_trace(mock.root(), harness, "hit", None);
        let queries = write_queries(mock.root(), true);
        mock.command(
            &trace,
            0,
            [
                "eval",
                "trigger",
                "fixture-skill",
                queries.to_str().unwrap(),
                "--harness",
                harness,
                "--runs",
                "1",
                "--skill-path",
                "/tmp/does-not-matter/SKILL.md",
            ],
        )
        .assert()
        .code(2)
        .stderr(contains("--skill-path"));
    }
}

/// Confirms the claude/opencode path needs no `jq` (the shell runner's one
/// hard dependency beyond the harness CLI): PATH holds only the mock-cli
/// directory plus `/bin`, where the mock's own `bash`/`cat` live but jq
/// (installed under `/usr/bin` on this machine) does not.
#[test]
fn claude_hit_runs_with_only_mock_cli_on_path() {
    let mock = MockHarness::new();
    let trace = write_trace(mock.root(), "claude", "hit", None);
    let queries = write_queries(mock.root(), true);
    let path =
        std::env::join_paths([mock.bin_dir().to_path_buf(), "/bin".into()]).expect("join PATH");
    assert!(
        !path
            .to_string_lossy()
            .split(':')
            .any(|dir| std::path::Path::new(dir).join("jq").is_file()),
        "test PATH must not resolve jq"
    );
    Command::cargo_bin("varde-learn")
        .unwrap()
        .env_clear()
        .env("PATH", path)
        .env("MOCK_TRACE", &trace)
        .env("MOCK_EXIT", "0")
        .args([
            "eval",
            "trigger",
            "fixture-skill",
            queries.to_str().unwrap(),
            "--harness",
            "claude",
            "--runs",
            "1",
        ])
        .assert()
        .success()
        .stdout(contains("evals: pass=1 fail=0"));
}

#[test]
// parity: fail "Codex accepted a missing --skill-path"
// parity: fail "missing --skill-path diagnostic was unclear"
fn codex_missing_skill_path_exits_2_with_diagnostic() {
    let mock = MockHarness::new();
    let queries = write_queries(mock.root(), true);
    mock.command(
        &mock.root().join("unused-trace.jsonl"),
        0,
        [
            "eval",
            "trigger",
            "fixture-skill",
            queries.to_str().unwrap(),
            "--harness",
            "codex",
            "--runs",
            "1",
        ],
    )
    .assert()
    .code(2)
    .stderr(contains("--skill-path"));
}

/// Codex-only fixture (ported from run-evals.sh's
/// `run_case codex auth-text true reject`): an authentication-gated
/// agent_message with no `turn.failed` event.
#[test]
// parity: fail "$harness $scenario expected trace rejection, got $status"
// parity: fail "$harness $scenario rejection was not explained"
fn codex_auth_text_response_rejects_with_exit_2() {
    let mock = MockHarness::new();
    let skill_path = mock.skill_path();
    let trace = write_trace(mock.root(), "codex", "auth-text", Some(&skill_path));
    let queries = write_queries(mock.root(), true);
    mock.command(&trace, 0, trigger_args(&mock, "codex", &queries, "1"))
        .assert()
        .code(2)
        .stderr(contains("error:"));
}

/// Not ported from the shell tests: `run-evals.sh` requires `--skill-path`
/// to already be absolute. `varde-learn` resolves a relative `--skill-path`
/// against the process cwd instead.
#[test]
fn codex_relative_skill_path_is_resolved_against_cwd() {
    let mock = MockHarness::new();
    // Canonicalize: `std::env::current_dir()` resolves symlinks (notably
    // macOS's /tmp -> /private/tmp), so the fixture must embed the same
    // canonical path `resolve_codex_skill_path` will compute.
    let skill_path = mock
        .skill_path()
        .canonicalize()
        .expect("canonicalize skill path");
    let root = mock.root().canonicalize().expect("canonicalize root");
    let trace = write_trace(mock.root(), "codex", "hit", Some(&skill_path));
    let queries = write_queries(mock.root(), true);
    Command::cargo_bin("varde-learn")
        .unwrap()
        .current_dir(&root)
        .env("PATH", mock.path_with_mock())
        .env("MOCK_TRACE", &trace)
        .env("MOCK_EXIT", "0")
        .args([
            "eval",
            "trigger",
            "fixture-skill",
            queries.to_str().unwrap(),
            "--harness",
            "codex",
            "--runs",
            "1",
            "--skill-path",
            "skill target/SKILL.md",
        ])
        .assert()
        .success()
        .stdout(contains("evals: pass=1 fail=0"));
}
