//! Shared mock-CLI test harness, ported from `skills/tests/trigger-evals.sh`.
//!
//! `MockHarness` writes the same `mock-cli` script (plus `claude`/`codex`/
//! `opencode` symlinks) that the shell fixtures used, so `tests/trigger.rs`
//! and any later `eval output` tests can prepend the same `bin/` dir to
//! `PATH` and drive the mock through `MOCK_TRACE`/`MOCK_EXIT`. `skill_path()`
//! mirrors the shell fixtures' `$TEST_ROOT/skill target/SKILL.md` (the space
//! in the directory name exercises quoting).
//!
//! `cargo test` compiles this module once per integration-test binary
//! (`trigger.rs`, `output.rs`, ...), each of which uses only a subset of it;
//! allow dead code here rather than in each binary that imports it.
#![allow(dead_code)]

use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};

use assert_cmd::Command;
use serde_json::{Value, json};
use tempfile::TempDir;

// Fixed shebang path (not `#!/usr/bin/env bash`) so the mock still runs
// under a PATH that holds only `bin_dir` — see
// `claude_hit_runs_with_only_mock_cli_on_path` in tests/trigger.rs.
const MOCK_CLI: &str = r#"#!/bin/bash
set -euo pipefail
case "${0##*/}" in
  claude) [[ "${1:-}" == -p && "${3:-}" == --output-format && "${4:-}" == stream-json && "${5:-}" == --verbose ]] || exit 90 ;;
  codex) [[ "${1:-}" == exec && "${2:-}" == --json ]] || exit 90 ;;
  opencode) [[ "${1:-}" == run && "${2:-}" == --format && "${3:-}" == json ]] || exit 90 ;;
esac
cat "$MOCK_TRACE"
exit "${MOCK_EXIT:-0}"
"#;

pub struct MockHarness {
    root: TempDir,
    bin_dir: PathBuf,
}

impl MockHarness {
    pub fn new() -> Self {
        let root = TempDir::new().expect("tempdir");
        let bin_dir = root.path().join("bin");
        std::fs::create_dir_all(&bin_dir).expect("mkdir bin");

        let mock_cli = bin_dir.join("mock-cli");
        std::fs::write(&mock_cli, MOCK_CLI).expect("write mock-cli");
        let mut perms = std::fs::metadata(&mock_cli)
            .expect("stat mock-cli")
            .permissions();
        perms.set_mode(0o755);
        std::fs::set_permissions(&mock_cli, perms).expect("chmod mock-cli");

        for name in ["claude", "codex", "opencode"] {
            symlink("mock-cli", bin_dir.join(name)).expect("symlink mock cli");
        }

        Self { root, bin_dir }
    }

    pub fn root(&self) -> &Path {
        self.root.path()
    }

    pub fn bin_dir(&self) -> &Path {
        &self.bin_dir
    }

    /// `bin_dir` prepended to the current process's `PATH`.
    pub fn path_with_mock(&self) -> std::ffi::OsString {
        let existing = std::env::var_os("PATH").unwrap_or_default();
        let paths = std::iter::once(self.bin_dir.clone()).chain(std::env::split_paths(&existing));
        std::env::join_paths(paths).expect("join PATH")
    }

    /// A `varde-learn` invocation with `PATH`, `MOCK_TRACE`, and `MOCK_EXIT`
    /// wired to this harness.
    pub fn command<I, S>(&self, trace: &Path, mock_exit: i32, args: I) -> Command
    where
        I: IntoIterator<Item = S>,
        S: AsRef<std::ffi::OsStr>,
    {
        let mut cmd = Command::cargo_bin("varde-learn").expect("varde-learn binary");
        cmd.env("PATH", self.path_with_mock());
        cmd.env("MOCK_TRACE", trace);
        cmd.env("MOCK_EXIT", mock_exit.to_string());
        cmd.args(args);
        cmd
    }

    /// The Codex proxy's target file, created on first use. Mirrors
    /// `skills/tests/trigger-evals.sh`'s `$TEST_ROOT/skill target/SKILL.md`.
    pub fn skill_path(&self) -> PathBuf {
        let dir = self.root.path().join("skill target");
        std::fs::create_dir_all(&dir).expect("mkdir skill dir");
        let path = dir.join("SKILL.md");
        if !path.exists() {
            std::fs::write(&path, "# Target skill\n").expect("write skill file");
        }
        path
    }
}

fn append_line(file: &mut std::fs::File, value: Value) {
    writeln!(file, "{value}").expect("write trace line");
}

/// Writes a `harness:scenario` fixture trace, mirroring `write_trace()` in
/// `skills/tests/trigger-evals.sh`. `skill_path` is required for the
/// codex `hit`/`miss` scenarios (embedded in the fixture's
/// `command_execution` command) and ignored otherwise.
pub fn write_trace(
    dir: &Path,
    harness: &str,
    scenario: &str,
    skill_path: Option<&Path>,
) -> PathBuf {
    let path = dir.join(format!("{harness}-{scenario}.jsonl"));
    let mut file = std::fs::File::create(&path).expect("create trace file");
    match (harness, scenario) {
        ("claude", "hit") => {
            append_line(&mut file, json!({"type": "system", "subtype": "init"}));
            append_line(
                &mut file,
                json!({
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "fixture-skill"}}]}
                }),
            );
            append_line(
                &mut file,
                json!({"type": "result", "subtype": "success", "is_error": false, "result": "done"}),
            );
        }
        ("claude", "miss") => {
            append_line(&mut file, json!({"type": "system", "subtype": "init"}));
            append_line(
                &mut file,
                json!({"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}),
            );
            append_line(
                &mut file,
                json!({"type": "result", "subtype": "success", "is_error": false, "result": "done"}),
            );
        }
        ("claude", "invalid") => {
            writeln!(file, "not json").expect("write invalid trace");
        }
        ("claude", "unknown") => {
            append_line(&mut file, json!({"type": "future_event"}));
        }
        ("claude", "auth") => {
            append_line(&mut file, json!({"type": "system", "subtype": "init"}));
            append_line(
                &mut file,
                json!({
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "Not logged in \u{b7} Please run /login"}]}
                }),
            );
            append_line(
                &mut file,
                json!({"type": "result", "subtype": "success", "is_error": true, "result": "Not logged in"}),
            );
        }
        ("claude", "incomplete") => {
            append_line(&mut file, json!({"type": "system", "subtype": "init"}));
            append_line(
                &mut file,
                json!({"type": "assistant", "message": {"content": [{"type": "text", "text": "still running"}]}}),
            );
        }
        ("opencode", "hit") => {
            append_line(
                &mut file,
                json!({"type": "step_start", "part": {"type": "step-start"}}),
            );
            append_line(
                &mut file,
                json!({
                    "type": "tool_use",
                    "part": {"type": "tool", "tool": "skill", "state": {"status": "completed", "input": {"id": "fixture-skill"}}}
                }),
            );
            append_line(
                &mut file,
                json!({"type": "step_finish", "part": {"type": "step-finish", "reason": "tool-calls"}}),
            );
            append_line(
                &mut file,
                json!({"type": "step_start", "part": {"type": "step-start"}}),
            );
            append_line(
                &mut file,
                json!({"type": "text", "part": {"type": "text", "text": "done", "time": {"start": 1, "end": 2}}}),
            );
        }
        ("opencode", "miss") => {
            append_line(
                &mut file,
                json!({"type": "step_start", "part": {"type": "step-start"}}),
            );
            append_line(
                &mut file,
                json!({"type": "text", "part": {"type": "text", "text": "done"}}),
            );
            append_line(
                &mut file,
                json!({"type": "step_finish", "part": {"type": "step-finish", "reason": "stop"}}),
            );
        }
        ("opencode", "invalid") => {
            writeln!(file, "not json").expect("write invalid trace");
        }
        ("opencode", "unknown") => {
            append_line(&mut file, json!({"type": "future_event"}));
        }
        ("opencode", "auth") => {
            append_line(
                &mut file,
                json!({"type": "step_start", "part": {"type": "step-start"}}),
            );
            append_line(
                &mut file,
                json!({
                    "type": "text",
                    "part": {"type": "text", "text": "Not logged in \u{b7} Please run /login", "time": {"start": 1, "end": 2}}
                }),
            );
        }
        ("opencode", "incomplete") => {
            append_line(
                &mut file,
                json!({"type": "step_start", "part": {"type": "step-start"}}),
            );
        }
        ("codex", "hit") | ("codex", "miss") => {
            let skill_path = skill_path.expect("codex hit/miss fixtures need a skill_path");
            let command = match scenario {
                "hit" => format!("cat \"{}\"", skill_path.display()),
                _ => "printf hello".to_string(),
            };
            append_line(
                &mut file,
                json!({"type": "thread.started", "thread_id": "thread-fixture"}),
            );
            append_line(&mut file, json!({"type": "turn.started"}));
            append_line(
                &mut file,
                json!({
                    "type": "item.completed",
                    "item": {"id": "item-1", "type": "command_execution", "command": command, "exit_code": 0, "status": "completed"}
                }),
            );
            append_line(
                &mut file,
                json!({
                    "type": "item.completed",
                    "item": {"id": "item-2", "type": "agent_message", "text": "done"}
                }),
            );
            append_line(
                &mut file,
                json!({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
            );
        }
        ("codex", "invalid") => {
            writeln!(file, "not json").expect("write invalid trace");
        }
        ("codex", "unknown") => {
            append_line(
                &mut file,
                json!({"type": "thread.started", "thread_id": "thread-fixture"}),
            );
            append_line(&mut file, json!({"type": "future_event"}));
        }
        ("codex", "auth") => {
            append_line(
                &mut file,
                json!({"type": "thread.started", "thread_id": "thread-fixture"}),
            );
            append_line(&mut file, json!({"type": "turn.started"}));
            append_line(
                &mut file,
                json!({"type": "turn.failed", "error": {"message": "Not logged in"}}),
            );
        }
        ("codex", "auth-text") => {
            append_line(
                &mut file,
                json!({"type": "thread.started", "thread_id": "thread-fixture"}),
            );
            append_line(&mut file, json!({"type": "turn.started"}));
            append_line(
                &mut file,
                json!({
                    "type": "item.completed",
                    "item": {"id": "item-1", "type": "agent_message", "text": "Not logged in \u{b7} Please run /login"}
                }),
            );
            append_line(
                &mut file,
                json!({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
            );
        }
        ("codex", "incomplete") => {
            append_line(
                &mut file,
                json!({"type": "thread.started", "thread_id": "thread-fixture"}),
            );
            append_line(&mut file, json!({"type": "turn.started"}));
        }
        _ => panic!("unknown fixture {harness}:{scenario}"),
    }
    path
}

pub fn write_queries(dir: &Path, want: bool) -> PathBuf {
    let path = dir.join("query.json");
    let content = json!([{"query": "fixture query", "should_trigger": want}]);
    std::fs::write(&path, content.to_string()).expect("write queries");
    path
}

// A distinct mock `claude` for `eval output` tests: `run-output-evals.sh`'s
// `claude -p <prompt> --output-format json --disable-slash-commands
// --setting-sources project,local --permission-mode auto [--add-dir DIR]`
// shape differs from the trigger harness's `stream-json --verbose` shape
// above, so it gets its own `bin/claude`, driven entirely through env vars
// (no positional-argument scenarios) so `tests/output.rs` can compose
// exactly the observation each case needs. The judge call (`grade.rs`'s
// `run_llm_judge`) reuses this same mock, distinguished by its prompt (`$2`)
// containing "You are grading", mirroring `skills/tests/output-evals.sh`'s
// mock `claude`.
const MOCK_CLI_OUTPUT: &str = r#"#!/bin/bash
set -euo pipefail
if [[ -n "${MOCK_CWD_FILE:-}" ]]; then
  printf '%s\n' "$PWD" >> "$MOCK_CWD_FILE"
fi
has_add_dir=0
for arg in "$@"; do
  [[ "$arg" != "--add-dir" ]] || has_add_dir=1
done
if [[ -n "${MOCK_ARGS_FILE:-}" ]]; then
  printf '%s\n' "$@" > "$MOCK_ARGS_FILE"
fi
if [[ -n "${MOCK_CONFIGS_FILE:-}" ]]; then
  if [[ "$has_add_dir" == 1 ]]; then
    printf '%s\n' with_skill >> "$MOCK_CONFIGS_FILE"
  else
    printf '%s\n' without_skill >> "$MOCK_CONFIGS_FILE"
  fi
fi

if [[ "${2:-}" == *"You are grading"* ]]; then
  if [[ -n "${MOCK_JUDGE_ARGS_FILE:-}" ]]; then
    printf '%s\n' "$2" > "$MOCK_JUDGE_ARGS_FILE"
  fi
  if [[ "${MOCK_JUDGE_TIMEOUT:-0}" == 1 ]]; then
    sleep 2
  fi
  if [[ "${MOCK_JUDGE_EXIT:-0}" != 0 ]]; then
    exit "$MOCK_JUDGE_EXIT"
  fi
  if [[ -n "${MOCK_JUDGE_RESPONSE_FILE:-}" ]]; then
    cat "$MOCK_JUDGE_RESPONSE_FILE"
  else
    printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"result":"{\"results\":[]}"}'
  fi
  exit 0
fi

if [[ -n "${MOCK_OUTPUT_RESPONSE_FILE:-}" ]]; then
  cat "$MOCK_OUTPUT_RESPONSE_FILE"
  exit 0
fi

if [[ "${MOCK_TIMEOUT:-0}" == 1 ]]; then
  if [[ -n "${MOCK_DESCENDANT_MARKER:-}" ]]; then
    ( trap '' TERM; sleep 2; printf survived > "$MOCK_DESCENDANT_MARKER" ) &
  fi
  sleep 2
  printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"result":"late output","duration_ms":2000,"usage":{"input_tokens":10,"output_tokens":10}}'
  exit 0
fi

if [[ "${MOCK_MODE:-}" == verify ]]; then
  printf done > filesystem-artifact.txt
fi

case "${MOCK_MODE:-measured}" in
  measured)
    printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"result":"fixture output","duration_ms":1000,"total_cost_usd":0.25,"usage":{"input_tokens":120,"output_tokens":80,"cache_creation_input_tokens":30,"cache_read_input_tokens":50}}'
    ;;
  zero)
    printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"result":"fixture output","duration_ms":1000,"usage":{"input_tokens":0,"output_tokens":0}}'
    ;;
  null)
    printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"result":"fixture output","duration_ms":1000,"usage":{"input_tokens":null,"output_tokens":null}}'
    ;;
  unavailable)
    printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"result":"fixture output","duration_ms":1000}'
    ;;
  verify)
    printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"result":"fixture output","duration_ms":1000,"usage":{"input_tokens":10,"output_tokens":10}}'
    ;;
  fail)
    exit 1
    ;;
  *)
    printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"result":"fixture output","duration_ms":1000,"usage":{"input_tokens":10,"output_tokens":10}}'
    ;;
esac
"#;

pub struct MockOutputClaude {
    root: TempDir,
    bin_dir: PathBuf,
}

impl MockOutputClaude {
    pub fn new() -> Self {
        let root = TempDir::new().expect("tempdir");
        let bin_dir = root.path().join("bin");
        std::fs::create_dir_all(&bin_dir).expect("mkdir bin");

        let claude = bin_dir.join("claude");
        std::fs::write(&claude, MOCK_CLI_OUTPUT).expect("write mock claude");
        let mut perms = std::fs::metadata(&claude)
            .expect("stat mock claude")
            .permissions();
        perms.set_mode(0o755);
        std::fs::set_permissions(&claude, perms).expect("chmod mock claude");

        Self { root, bin_dir }
    }

    pub fn root(&self) -> &Path {
        self.root.path()
    }

    /// `bin_dir` prepended to the current process's `PATH`.
    pub fn path_with_mock(&self) -> std::ffi::OsString {
        let existing = std::env::var_os("PATH").unwrap_or_default();
        let paths = std::iter::once(self.bin_dir.clone()).chain(std::env::split_paths(&existing));
        std::env::join_paths(paths).expect("join PATH")
    }

    /// A `varde-learn eval output` invocation with `PATH` wired to this
    /// mock `claude`.
    pub fn command(&self) -> Command {
        let mut cmd = Command::cargo_bin("varde-learn").expect("varde-learn binary");
        cmd.env("PATH", self.path_with_mock());
        cmd
    }
}

/// Writes a minimal skill fixture (`SKILL.md` + `evals/evals.json`) at
/// `dir`, ready for `eval output`. `evals_json` is the full evals.json text.
pub fn write_output_skill(dir: &Path, evals_json: &str) {
    std::fs::create_dir_all(dir.join("evals")).expect("mkdir evals");
    std::fs::write(dir.join("SKILL.md"), "# Fixture skill\n").expect("write SKILL.md");
    std::fs::write(dir.join("evals/evals.json"), evals_json).expect("write evals.json");
}
