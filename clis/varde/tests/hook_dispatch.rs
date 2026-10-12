//! `varde hook post-tool-use` and `hook session-start`: configured providers.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use tempfile::TempDir;

struct Env {
    root: TempDir,
}

impl Env {
    fn new(config: &str) -> Self {
        let root = TempDir::new().unwrap();
        fs::create_dir_all(root.path().join("config")).unwrap();
        fs::create_dir_all(root.path().join("toz")).unwrap();
        fs::create_dir_all(root.path().join("repo")).unwrap();
        let config = config.replace("{ROOT}", &root.path().display().to_string());
        fs::write(root.path().join("config/config.toml"), config).unwrap();
        Env { root }
    }

    fn path(&self, name: &str) -> PathBuf {
        self.root.path().join(name)
    }

    fn run(&self, args: &[&str], stdin: &str) -> Output {
        let mut child = Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(args)
            .current_dir(self.path("repo"))
            .env("HOME", self.root.path())
            .env("VARDE_CONFIG_DIR", self.path("config"))
            .env("VARDE_TOZ_CONFIG_DIR", self.path("toz"))
            .env_remove("TOZ_CONFIG_DIR")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        // A dispatcher with nothing to run exits without reading stdin.
        let _ = child.stdin.take().unwrap().write_all(stdin.as_bytes());
        child.wait_with_output().unwrap()
    }
}

fn large_payload() -> String {
    let stdout: Vec<String> = (0..4000)
        .map(|n| format!("line {n:06} build output ok warning: unused variable x"))
        .collect();
    serde_json::json!({
        "hook_event_name": "PostToolUse",
        "session_id": "t",
        "tool_name": "Bash",
        "tool_input": {"command": "make"},
        "tool_response": {"stdout": stdout.join("\n"), "stderr": "", "interrupted": false},
    })
    .to_string()
}

fn write_block(path: &Path, text: &str) {
    fs::write(path, text).unwrap();
}

fn context(output: &Output) -> String {
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["hookSpecificOutput"]["hookEventName"], "SessionStart");
    value["hookSpecificOutput"]["additionalContext"]
        .as_str()
        .unwrap()
        .to_string()
}

fn session_note_path(context: &str) -> PathBuf {
    let line = context
        .lines()
        .find(|line| line.starts_with("varde session notes: "))
        .expect(context);
    PathBuf::from(line.trim_start_matches("varde session notes: "))
}

fn session_state_path(env: &Env) -> PathBuf {
    fs::read_dir(env.path("config/sessions"))
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .find(|path| {
            path.extension()
                .is_some_and(|extension| extension == "json")
        })
        .unwrap()
}

const POST: [&str; 4] = ["hook", "post-tool-use", "--harness", "claude"];
const START: [&str; 4] = ["hook", "session-start", "--harness", "claude"];

fn write_inbox(env: &Env, lines: &[&str]) {
    let dir = env.path("working/.cache/inbox");
    fs::create_dir_all(&dir).unwrap();
    fs::write(
        dir.join("messages.jsonl"),
        format!("{}\n", lines.join("\n")),
    )
    .unwrap();
}

#[test]
fn user_prompt_submit_adds_the_unread_one_liners_once_per_harness() {
    let env = Env::new("[default]\nworking = \"{ROOT}/working\"\n");
    write_inbox(
        &env,
        &[
            r#"{"ts":"t","from":"orch","to":"main","kind":"done","text":"wave published"}"#,
            r#"{"ts":"t","from":"watch","to":"main","kind":"stale","text":"plan needs attention"}"#,
            r#"{"ts":"t","from":"watch","to":"main","kind":"merge-ready","text":"ready to merge"}"#,
        ],
    );
    let first = env.run(&["hook", "user-prompt-submit", "--harness", "claude"], "");
    assert!(first.status.success(), "{first:?}");
    let value: serde_json::Value = serde_json::from_slice(&first.stdout).unwrap();
    assert_eq!(
        value["hookSpecificOutput"]["hookEventName"],
        "UserPromptSubmit"
    );
    assert!(
        value["hookSpecificOutput"]["additionalContext"]
            .as_str()
            .unwrap()
            .contains("inbox: orch done: wave published")
    );
    let context = value["hookSpecificOutput"]["additionalContext"]
        .as_str()
        .unwrap();
    assert!(
        context.contains("inbox: watch stale: plan needs attention"),
        "{context}"
    );
    assert!(
        context.contains("inbox: watch merge-ready: ready to merge"),
        "{context}"
    );
    let second = env.run(&["hook", "user-prompt-submit", "--harness", "claude"], "");
    assert!(second.status.success(), "{second:?}");
    assert!(second.stdout.is_empty(), "{second:?}");

    // Pi gets the same one-liners as plain stdout, not a JSON envelope.
    write_inbox(
        &env,
        &[r#"{"ts":"t","from":"a","to":"main","kind":"info","text":"plain"}"#],
    );
    let pi = env.run(&["hook", "user-prompt-submit", "--harness", "pi"], "");
    assert!(pi.status.success(), "{pi:?}");
    let text = String::from_utf8(pi.stdout).unwrap();
    assert_eq!(text.trim(), "inbox: a info: plain");
    assert!(!text.contains("hookSpecificOutput"));
}

#[test]
fn user_prompt_submit_with_an_empty_provider_list_prints_nothing() {
    let env = Env::new(
        "[default]\nworking = \"{ROOT}/working\"\n[hooks.user_prompt_submit]\nproviders = []\n",
    );
    write_inbox(
        &env,
        &[r#"{"ts":"t","from":"orch","to":"main","kind":"done","text":"wave published"}"#],
    );
    let output = env.run(&["hook", "user-prompt-submit", "--harness", "claude"], "");
    assert!(output.status.success(), "{output:?}");
    assert!(output.stdout.is_empty(), "{output:?}");
}

#[test]
fn default_post_tool_use_captures_a_large_result() {
    let env = Env::new("");
    let output = env.run(&POST, &large_payload());
    assert!(output.status.success(), "{output:?}");
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["hookSpecificOutput"]["hookEventName"], "PostToolUse");
}

#[test]
fn empty_post_tool_use_provider_list_captures_nothing() {
    let env = Env::new("[hooks.post_tool_use]\nproviders = []\n");
    let output = env.run(&POST, &large_payload());
    assert!(output.status.success(), "{output:?}");
    assert!(output.stdout.is_empty());
    assert!(output.stderr.is_empty());
}

#[test]
fn unknown_post_tool_use_provider_is_a_notice() {
    let env = Env::new("[hooks.post_tool_use]\nproviders = [\"bogus\", \"capture\"]\n");
    let output = env.run(&POST, &large_payload());
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("unknown provider `bogus`"));
    assert!(!output.stdout.is_empty());
}

#[test]
fn bad_harness_is_a_usage_error() {
    let env = Env::new("");
    let output = env.run(&["hook", "post-tool-use", "--harness", "vim"], "");
    assert_eq!(output.status.code(), Some(2));
}

#[test]
fn event_help_exits_zero_without_a_harness() {
    let env = Env::new("");
    for event in ["session-start", "post-tool-use", "user-prompt-submit"] {
        for flag in ["--help", "-h"] {
            let output = env.run(&["hook", event, flag], "");
            assert!(output.status.success(), "{event} {flag}: {output:?}");
            let text = String::from_utf8_lossy(&output.stdout);
            assert!(text.contains("--harness"), "{text}");
        }
    }
}

#[test]
fn oversized_post_tool_use_payload_gives_empty_output_and_exit_zero() {
    let env = Env::new("");
    let output = env.run(&POST, &" ".repeat(8 * 1024 * 1024 + 4096));
    assert!(output.status.success(), "{output:?}");
    assert!(output.stdout.is_empty());
}

#[test]
fn toz_note_appears_only_when_no_target_holds_the_block() {
    let env = Env::new(
        "[hooks.session_start]\nproviders = [\"toz_note\"]\n[instructions]\ntargets = [\"{ROOT}/a.md\", \"{ROOT}/b.md\"]\n",
    );
    let (a, b) = (env.path("a.md"), env.path("b.md"));
    let marker = "<!-- varde:start -->\nbrief\n<!-- varde:end -->\n";

    // Neither target exists.
    assert!(context(&env.run(&START, "")).contains("varde-toz"));

    // A start marker without its end marker is not a block.
    write_block(&a, "<!-- varde:start -->\nbrief\n");
    write_block(&b, "plain\n");
    assert!(context(&env.run(&START, "")).contains("varde-toz"));

    // One target with a paired block is enough.
    write_block(&b, marker);
    assert!(context(&env.run(&START, "")).is_empty());
}

#[test]
fn unknown_provider_gives_a_notice_and_the_others_still_run() {
    let env = Env::new("[hooks.session_start]\nproviders = [\"bogus\", \"toz_note\"]\n");
    let output = env.run(&START, "");
    assert!(output.status.success());
    let text = context(&output);
    assert!(text.contains("unknown provider `bogus` skipped"), "{text}");
    assert!(text.contains("varde-toz"), "{text}");
}

#[test]
fn session_start_is_one_payload_per_harness() {
    let env = Env::new("[hooks.session_start]\nproviders = [\"toz_note\"]\n");
    let plain = env.run(&["hook", "session-start", "--harness", "pi"], "");
    let text = String::from_utf8(plain.stdout).unwrap();
    assert!(text.contains("varde-toz") && !text.contains("hookSpecificOutput"));
    let codex = env.run(
        &["hook", "session-start", "--harness=codex"],
        r#"{"session_id":"claude-session"}"#,
    );
    let text = context(&codex);
    assert!(text.contains("varde-toz"));
    assert!(text.contains("varde session: claude-session"));
    assert!(text.contains("varde session notes:"));
    let note_path = session_note_path(&text);
    assert_eq!(note_path.file_name().unwrap(), "notes.md");
    assert_eq!(
        note_path
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .file_name()
            .unwrap(),
        "session-notes"
    );
    for harness in ["opencode", "pi"] {
        let output = env.run(
            &["hook", "session-start", "--harness", harness],
            r#"{"session_id":"other-session"}"#,
        );
        let text = String::from_utf8(output.stdout).unwrap();
        assert!(text.contains("varde session: other-session"), "{text}");
        assert!(text.contains("varde session notes:"), "{text}");
    }
}

#[test]
fn legacy_state_path_is_kept_before_migration_and_old_field_still_loads() {
    let env = Env::new("");
    let session_id = "legacy-before-migration";
    let initial = context(&env.run(&START, &format!(r#"{{"session_id":"{session_id}"}}"#)));
    let new_path = session_note_path(&initial);
    let old_path = new_path
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("handoffs")
        .join(new_path.parent().unwrap().file_name().unwrap())
        .join("handoff.md");
    fs::create_dir_all(old_path.parent().unwrap()).unwrap();
    fs::write(&old_path, "legacy note\n").unwrap();
    fs::write(
        session_state_path(&env),
        serde_json::json!({
            "harness": "claude",
            "session_id": session_id,
            "handoff_path": old_path,
            "above_threshold": false,
        })
        .to_string(),
    )
    .unwrap();

    let resumed = context(&env.run(&START, &format!(r#"{{"session_id":"{session_id}"}}"#)));

    assert_eq!(session_note_path(&resumed), old_path);
    let state: serde_json::Value =
        serde_json::from_slice(&fs::read(session_state_path(&env)).unwrap()).unwrap();
    assert_eq!(state["notes_path"], old_path.to_string_lossy().as_ref());
}

#[test]
fn vanished_legacy_state_path_repoints_to_the_migrated_note() {
    let env = Env::new("");
    let session_id = "legacy-after-migration";
    let initial = context(&env.run(&START, &format!(r#"{{"session_id":"{session_id}"}}"#)));
    let new_path = session_note_path(&initial);
    let old_path = new_path
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("handoffs")
        .join(new_path.parent().unwrap().file_name().unwrap())
        .join("handoff.md");
    fs::create_dir_all(old_path.parent().unwrap()).unwrap();
    fs::write(&old_path, "migrated note\n").unwrap();
    fs::write(
        session_state_path(&env),
        serde_json::json!({
            "harness": "claude",
            "session_id": session_id,
            "handoff_path": old_path,
            "above_threshold": false,
        })
        .to_string(),
    )
    .unwrap();
    fs::create_dir_all(new_path.parent().unwrap()).unwrap();
    fs::rename(&old_path, &new_path).unwrap();
    fs::remove_dir(old_path.parent().unwrap()).unwrap();

    let resumed = context(&env.run(&START, &format!(r#"{{"session_id":"{session_id}"}}"#)));

    assert_eq!(session_note_path(&resumed), new_path);
    assert_eq!(fs::read_to_string(&new_path).unwrap(), "migrated note\n");
    let state: serde_json::Value =
        serde_json::from_slice(&fs::read(session_state_path(&env)).unwrap()).unwrap();
    assert_eq!(state["notes_path"], new_path.to_string_lossy().as_ref());
}

#[test]
fn claude_session_start_includes_session_id_when_present() {
    let env = Env::new("");
    let with_id = context(&env.run(&START, r#"{"session_id":"claude-session-123"}"#));
    assert!(
        with_id.contains("varde session: claude-session-123"),
        "{with_id}"
    );

    let without_id = context(&env.run(&START, "{}"));
    assert!(!without_id.contains("varde session:"), "{without_id}");
}

fn usage_payload(session_id: &str, input: u64) -> String {
    serde_json::json!({
        "session_id": session_id,
        "model": {"id":"test-model", "contextWindow":1000000},
        "usage": {"input":input, "output":0, "cacheRead":0, "cacheWrite":0}
    })
    .to_string()
}

#[test]
fn handoff_nudges_once_per_crossing_and_reuses_the_reserved_path() {
    let env = Env::new(
        "[hooks.post_tool_use]\nproviders = [\"context_handoff\"]\n[session]\nhandoff_at_tokens = 300\n",
    );
    let run = |input| {
        env.run(
            &["hook", "post-tool-use", "--harness", "pi"],
            &usage_payload("session-crossing", input),
        )
    };
    assert!(run(200).stdout.is_empty());
    let first = run(300);
    let first_json: serde_json::Value = serde_json::from_slice(&first.stdout).unwrap();
    let first_context = first_json["additionalContext"].as_str().unwrap();
    assert!(first_context.contains("Context reached 300 tokens (threshold 300)."));
    let path = first_context
        .split(" at ")
        .nth(1)
        .unwrap()
        .split(" and advise")
        .next()
        .unwrap();
    assert!(run(800).stdout.is_empty());
    assert!(run(299).stdout.is_empty());
    let second = run(300);
    let second_json: serde_json::Value = serde_json::from_slice(&second.stdout).unwrap();
    assert!(
        second_json["additionalContext"]
            .as_str()
            .unwrap()
            .contains(path)
    );
}

#[test]
fn zero_handoff_threshold_disables_nudge() {
    let disabled = Env::new(
        "[hooks.post_tool_use]\nproviders = [\"context_handoff\"]\n[session]\nhandoff_at_tokens = 0\n",
    );
    let output = disabled.run(
        &["hook", "post-tool-use", "--harness", "pi"],
        &usage_payload("disabled", 900_000),
    );
    assert!(output.status.success());
    assert!(output.stdout.is_empty());
}

#[test]
fn handoff_threshold_works_without_a_context_window() {
    let env = Env::new(
        "[hooks.post_tool_use]\nproviders = [\"context_handoff\"]\n[session]\nhandoff_at_tokens = 100\n",
    );
    let run = |input| {
        let mut payload: serde_json::Value =
            serde_json::from_str(&usage_payload("no-window", input)).unwrap();
        payload["model"]
            .as_object_mut()
            .unwrap()
            .remove("contextWindow");
        env.run(
            &["hook", "post-tool-use", "--harness", "pi"],
            &payload.to_string(),
        )
    };
    assert!(run(99).stdout.is_empty());
    let output = run(100);
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let context = value["additionalContext"].as_str().unwrap();
    assert!(context.contains("Context reached 100 tokens (threshold 100)."));
    assert!(context.contains("Create or refresh the session note at "));
    assert!(context.contains("and advise the user to compact."));
}

#[test]
fn new_session_notes_threshold_wins_over_the_legacy_key() {
    let env = Env::new(
        "[hooks.post_tool_use]\nproviders = [\"session_notes\"]\n[session]\nnotes_at_tokens = 300\nhandoff_at_tokens = 100\n",
    );
    let run = |input| {
        env.run(
            &["hook", "post-tool-use", "--harness", "pi"],
            &usage_payload("new-threshold-wins", input),
        )
    };

    assert!(run(100).stdout.is_empty());
    let output = run(300);
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(
        value["additionalContext"]
            .as_str()
            .unwrap()
            .contains("Context reached 300 tokens (threshold 300).")
    );
}

#[test]
fn invalid_handoff_at_tokens_uses_default_with_notice() {
    for (kind, setting) in [
        ("negative", "handoff_at_tokens = -1"),
        ("float", "handoff_at_tokens = 250000.0"),
        ("non-integer", "handoff_at_tokens = \"250000\""),
    ] {
        let config = format!(
            "[hooks.post_tool_use]\nproviders = [\"context_handoff\"]\n[session]\n{setting}\n"
        );
        let env = Env::new(&config);
        let run = |input| {
            env.run(
                &["hook", "post-tool-use", "--harness", "pi"],
                &usage_payload(&format!("invalid-{kind}"), input),
            )
        };
        assert!(run(249_999).stdout.is_empty(), "{kind}");
        let output = run(250_000);
        assert!(output.status.success());
        assert!(
            String::from_utf8_lossy(&output.stderr).contains("invalid [session].handoff_at_tokens"),
            "{kind}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(!output.stdout.is_empty(), "{kind}");
    }
}

#[test]
fn concurrent_crossing_hooks_emit_one_nudge() {
    let env = Env::new(
        "[hooks.post_tool_use]\nproviders = [\"context_handoff\"]\n[session]\nhandoff_at_tokens = 1\n",
    );
    let payload = usage_payload("parallel-session", 900);
    let outputs = std::thread::scope(|scope| {
        (0..2)
            .map(|_| {
                let payload = &payload;
                scope.spawn(|| env.run(&["hook", "post-tool-use", "--harness", "pi"], payload))
            })
            .map(|handle| handle.join().unwrap())
            .collect::<Vec<_>>()
    });
    assert_eq!(
        outputs
            .iter()
            .filter(|output| !output.stdout.is_empty())
            .count(),
        1
    );
}

#[test]
fn model_or_window_change_does_not_reset_above_threshold_state() {
    let env = Env::new(
        "[hooks.post_tool_use]\nproviders = [\"context_handoff\"]\n[session]\nhandoff_at_tokens = 300\n",
    );
    let first = env.run(
        &["hook", "post-tool-use", "--harness", "pi"],
        &usage_payload("model-reset", 900),
    );
    assert!(!first.stdout.is_empty());
    let mut changed: serde_json::Value =
        serde_json::from_str(&usage_payload("model-reset", 900)).unwrap();
    changed["model"]["id"] = serde_json::json!("other-model");
    changed["model"]["contextWindow"] = serde_json::json!(2000);
    let second = env.run(
        &["hook", "post-tool-use", "--harness", "pi"],
        &changed.to_string(),
    );
    assert!(second.stdout.is_empty());
}

#[test]
fn capture_and_handoff_share_one_hook_response() {
    let env = Env::new("");
    let transcript = env.path(".claude/projects/project/session.jsonl");
    fs::create_dir_all(transcript.parent().unwrap()).unwrap();
    fs::write(
        &transcript,
        format!(
            "{}\n",
            serde_json::json!({
                "type":"assistant",
                "message":{
                    "role":"assistant",
                    "model":"claude-opus-4-6",
                    "usage":{"input_tokens":400000,"output_tokens":0}
                }
            })
        ),
    )
    .unwrap();
    let mut payload: serde_json::Value = serde_json::from_str(&large_payload()).unwrap();
    payload["session_id"] = serde_json::json!("capture-and-handoff");
    payload["transcript_path"] = serde_json::json!(transcript);
    let output = env.run(&POST, &payload.to_string());
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let context = value["hookSpecificOutput"]["additionalContext"]
        .as_str()
        .unwrap();
    assert!(
        context.contains("Create or refresh the session note"),
        "{context}"
    );
    assert!(
        value["hookSpecificOutput"]
            .get("updatedToolOutput")
            .is_some()
    );
}

const HANDOFF_CONFIG: &str = "[hooks.post_tool_use]\nproviders = [\"context_handoff\"]\n";

fn nudged(output: &Output) -> bool {
    String::from_utf8_lossy(&output.stdout).contains("Context reached")
}

#[test]
fn claude_subagent_payload_does_not_consume_the_crossing() {
    let env = Env::new(HANDOFF_CONFIG);
    let transcript = env.path(".claude/projects/project/session.jsonl");
    fs::create_dir_all(transcript.parent().unwrap()).unwrap();
    fs::write(
        &transcript,
        format!(
            "{}\n",
            serde_json::json!({
                "type":"assistant",
                "message":{"role":"assistant","model":"claude-opus-4-6",
                    "usage":{"input_tokens":260000,"output_tokens":0}}
            })
        ),
    )
    .unwrap();
    let mut payload = serde_json::json!({
        "session_id": "claude-subagent",
        "transcript_path": transcript,
        "tool_name": "Bash",
        "tool_input": {"command": "true"},
        "tool_response": {"stdout": "", "stderr": "", "interrupted": false},
        "agent_id": "agent-abc123",
        "agent_type": "Explore",
    });
    assert!(!nudged(&env.run(&POST, &payload.to_string())));
    payload.as_object_mut().unwrap().remove("agent_id");
    payload.as_object_mut().unwrap().remove("agent_type");
    assert!(nudged(&env.run(&POST, &payload.to_string())));
    assert!(!nudged(&env.run(&POST, &payload.to_string())));
}

#[test]
fn codex_nested_token_count_nudges_at_ninety_percent_of_the_window() {
    let env = Env::new(HANDOFF_CONFIG);
    let rollout = env.path(".codex/sessions/2026/10/10/rollout-fixture.jsonl");
    fs::create_dir_all(rollout.parent().unwrap()).unwrap();
    let write = |input: u64| {
        fs::write(
            &rollout,
            format!(
                "{}\n",
                serde_json::json!({
                    "type":"event_msg",
                    "payload":{"type":"token_count","info":{
                        "last_token_usage":{"input_tokens":input,"output_tokens":3},
                        "total_token_usage":{"input_tokens":input,"output_tokens":3},
                        "model_context_window":258400
                    }}
                })
            ),
        )
        .unwrap();
    };
    let run = || {
        let payload = serde_json::json!({
            "session_id": "codex-window",
            "transcript_path": rollout,
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "tool_response": {"stdout": "", "stderr": "", "interrupted": false},
        });
        env.run(
            &["hook", "post-tool-use", "--harness", "codex"],
            &payload.to_string(),
        )
    };
    write(232_559);
    assert!(!nudged(&run()));
    write(232_560);
    let output = run();
    assert!(nudged(&output));
    assert!(String::from_utf8_lossy(&output.stdout).contains("threshold 232560"));
}

#[test]
fn opencode_direct_usage_nudges_again_after_a_drop() {
    let env = Env::new(HANDOFF_CONFIG);
    let run = |input: u64| {
        let payload = serde_json::json!({
            "session_id": "opencode-cycle",
            "context_usage": {
                "usage": {"input": input, "output": 0, "reasoning": 0, "cacheRead": 0, "cacheWrite": 0},
                "model": {"id": "test-model"}
            }
        });
        env.run(
            &["hook", "post-tool-use", "--harness", "opencode"],
            &payload.to_string(),
        )
    };
    assert!(!nudged(&run(100_000)));
    assert!(nudged(&run(256_000)));
    assert!(!nudged(&run(270_000)));
    assert!(!nudged(&run(20_000)));
    assert!(nudged(&run(255_000)));
}

#[test]
fn pi_direct_usage_nudges_again_after_a_drop_with_the_default_threshold() {
    let env = Env::new(HANDOFF_CONFIG);
    let run = |input| {
        env.run(
            &["hook", "post-tool-use", "--harness", "pi"],
            &usage_payload("pi-cycle", input),
        )
    };
    assert!(!nudged(&run(100_000)));
    assert!(nudged(&run(260_000)));
    assert!(!nudged(&run(270_000)));
    assert!(!nudged(&run(30_000)));
    assert!(nudged(&run(260_000)));
}
