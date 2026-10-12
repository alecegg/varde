//! `hook session-start`: provider output, notices, and per-harness shape.

use super::common;

use std::fs;
use std::process::{Command, Output};

fn inbox_fixture(name: &str) -> (std::path::PathBuf, std::path::PathBuf) {
    let root = common::temp_bundle(name);
    let config = common::temp_bundle(&format!("{name}-config"));
    fs::create_dir_all(&config).unwrap();
    Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .unwrap();
    let plan = root.join("memory-bank/working/plans/test-plan/plan.md");
    fs::create_dir_all(plan.parent().unwrap()).unwrap();
    fs::write(
        &plan,
        "---\ntype: plan\nstatus: active\nowner: claude:session-123\n---\n",
    )
    .unwrap();
    (root, config)
}

fn inbox_command(
    root: &std::path::Path,
    config: &std::path::Path,
    args: &[&str],
    input: Option<&str>,
) -> Output {
    let mut command = Command::new(common::bin());
    command
        .args(args)
        .current_dir(root)
        .env("VARDE_CONFIG_DIR", config)
        .env_remove("VARDE_WORKING_DIR")
        .env_remove("VARDE_KNOWLEDGE_DIR")
        .env_remove("VARDE_LEARN_STORE");
    if let Some(input) = input {
        use std::io::Write;
        use std::process::Stdio;
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let mut child = command.spawn().unwrap();
        child
            .stdin
            .take()
            .unwrap()
            .write_all(input.as_bytes())
            .unwrap();
        child.wait_with_output().unwrap()
    } else {
        command.output().unwrap()
    }
}

fn send_to_plan(root: &std::path::Path, config: &std::path::Path, text: &str) {
    let sent = inbox_command(
        root,
        config,
        &[
            "msg",
            "send",
            "--from",
            "orch",
            "--to",
            "test-plan",
            "--kind",
            "info",
            text,
        ],
        None,
    );
    assert!(
        sent.status.success(),
        "{}",
        String::from_utf8_lossy(&sent.stderr)
    );
}

#[test]
fn hook_plan_inbox_delivers_to_the_owned_plan() {
    let (root, config) = inbox_fixture("hook-plan-inbox");
    send_to_plan(&root, &config, "plan-only-message");
    let output = inbox_command(
        &root,
        &config,
        &["hook", "user-prompt-submit", "--harness", "claude"],
        Some(r#"{"session_id":"session-123"}"#),
    );
    assert!(output.status.success());
    let text = String::from_utf8_lossy(&output.stdout);
    assert!(
        text.contains("plan-only-message"),
        "{text}; stderr={:?}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn hook_plan_inbox_uses_custom_id_for_nested_owned_plan() {
    let (root, config) = inbox_fixture("hook-plan-inbox-custom-id");
    fs::remove_file(root.join("memory-bank/working/plans/test-plan/plan.md")).unwrap();
    let plan = root.join("memory-bank/working/plans/group/nested/plan.md");
    fs::create_dir_all(plan.parent().unwrap()).unwrap();
    fs::write(
        &plan,
        "---\ntype: plan\nid: canonical-custom-id\nstatus: active\nowner: claude:session-123\n---\n",
    )
    .unwrap();
    let sent = inbox_command(
        &root,
        &config,
        &["msg", "send", "--from", "orch", "--to", "canonical-custom-id", "--kind", "info", "custom-id-message"],
        None,
    );
    assert!(sent.status.success());

    let output = inbox_command(
        &root,
        &config,
        &["hook", "user-prompt-submit", "--harness", "claude"],
        Some(r#"{"session_id":"session-123"}"#),
    );
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stdout).contains("custom-id-message"));
}

#[test]
fn hook_plan_inbox_uses_status_path_id_for_nested_plan() {
    let (root, config) = inbox_fixture("hook-plan-inbox-nested-id");
    fs::remove_file(root.join("memory-bank/working/plans/test-plan/plan.md")).unwrap();
    let plan = root.join("memory-bank/working/plans/group/nested/plan.md");
    fs::create_dir_all(plan.parent().unwrap()).unwrap();
    fs::write(
        &plan,
        "---\ntype: plan\nstatus: active\nowner: claude:session-123\n---\n",
    )
    .unwrap();
    let sent = inbox_command(
        &root,
        &config,
        &["msg", "send", "--from", "orch", "--to", "nested", "--kind", "info", "nested-id-message"],
        None,
    );
    assert!(sent.status.success());

    let output = inbox_command(
        &root,
        &config,
        &["hook", "user-prompt-submit", "--harness", "claude"],
        Some(r#"{"session_id":"session-123"}"#),
    );
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stdout).contains("nested-id-message"));
}

#[test]
fn hook_plan_inbox_unread_shares_the_plan_reader_cursor() {
    let (root, config) = inbox_fixture("hook-plan-inbox-unread");
    send_to_plan(&root, &config, "already-read");
    let read = inbox_command(&root, &config, &["msg", "read", "--as", "test-plan"], None);
    assert!(read.status.success());
    send_to_plan(&root, &config, "only-unread");
    let prompt = ["hook", "user-prompt-submit", "--harness", "claude"];
    let input = r#"{"session_id":"session-123"}"#;
    let first = inbox_command(&root, &config, &prompt, Some(input));
    assert!(first.status.success());
    let text = String::from_utf8_lossy(&first.stdout);
    assert!(text.contains("only-unread"), "{text}");
    assert!(!text.contains("already-read"), "{text}");
    let second = inbox_command(&root, &config, &prompt, Some(input));
    assert!(second.status.success());
    assert!(
        second.stdout.is_empty(),
        "{}",
        String::from_utf8_lossy(&second.stdout)
    );
}

#[test]
fn hook_prompt_submit_returns_when_stdin_is_empty() {
    let (root, config) = inbox_fixture("hook-empty-stdin");
    let output = inbox_command(
        &root,
        &config,
        &["hook", "user-prompt-submit", "--harness", "claude"],
        Some(""),
    );
    assert!(output.status.success());
    assert!(output.stdout.is_empty());
}

/// Run `hook session-start` in a fresh temp repo with `providers` as the
/// optional `[hooks.session_start]` override. `nav_map` runs in-process; with
/// `indexed` the repo's code index is built first, without it `nav_map`
/// reports a missing index.
fn session_start(name: &str, harness: &str, providers: Option<&str>, indexed: bool) -> Output {
    session_start_with(name, harness, providers, "", indexed)
}

/// Like `session_start`, with `extra` raw TOML appended to the config.
fn session_start_with(
    name: &str,
    harness: &str,
    providers: Option<&str>,
    extra: &str,
    indexed: bool,
) -> Output {
    let root = common::temp_bundle(name);
    // HOME and config live outside the repo so the index never goes stale.
    let outside = common::temp_bundle(&format!("{name}-outside"));
    let home = outside.join("home");
    fs::create_dir_all(&home).unwrap();
    let config_dir = outside.join("config");
    fs::create_dir_all(&config_dir).unwrap();
    let mut config = String::new();
    if let Some(list) = providers {
        config.push_str(&format!("[hooks.session_start]\nproviders = {list}\n"));
    }
    let target = outside.join("AGENTS.md");
    fs::write(&target, "<!-- varde:start -->\nbrief\n<!-- varde:end -->\n").unwrap();
    config.push_str(&extra.replace("{TARGET}", &target.display().to_string()));
    if !config.is_empty() {
        fs::write(config_dir.join("config.toml"), config).unwrap();
    }
    if indexed {
        fs::create_dir_all(root.join("src")).unwrap();
        fs::write(root.join("src/lib.rs"), "pub fn hello() {}\n").unwrap();
        for args in [vec!["init", "-q"], vec!["add", "src"]] {
            let status = Command::new("git")
                .arg("-C")
                .arg(&root)
                .args(args)
                .status()
                .unwrap();
            assert!(status.success());
        }
        let build = Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(["map", "build", "--repo-root"])
            .arg(&root)
            .current_dir(&root)
            .env("HOME", &home)
            .env("VARDE_CONFIG_DIR", &config_dir)
            .output()
            .unwrap();
        assert!(build.status.success(), "{build:?}");
    }
    Command::new(common::bin())
        .args(["hook", "session-start", "--harness", harness])
        .current_dir(&root)
        .env("HOME", &home)
        .env("VARDE_CONFIG_DIR", &config_dir)
        .output()
        .unwrap()
}

/// A configured target that already holds the managed block.
const TARGETS: &str = "\n[instructions]\ntargets = [\"{TARGET}\"]\n";

fn context(output: &Output) -> String {
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["hookSpecificOutput"]["hookEventName"], "SessionStart");
    value["hookSpecificOutput"]["additionalContext"]
        .as_str()
        .unwrap()
        .to_string()
}

#[test]
fn default_provider_emits_the_repo_map_and_setup_warning_without_targets() {
    let output = session_start("hook-default", "claude", None, true);
    assert!(output.status.success());
    let text = context(&output);
    assert!(text.contains("## Repository outline"), "{text}");
    assert!(!text.contains("skipped"), "{text}");
    assert!(
        !text.contains("at most ") && !text.contains("references/orchestration.md"),
        "{text}"
    );
    assert!(
        text.contains("Varde will not work as designed until its instruction block is installed"),
        "{text}"
    );
}

#[test]
fn codex_uses_the_same_envelope_without_legacy_provider_output() {
    let output = session_start_with("hook-codex", "codex", None, TARGETS, true);
    assert!(output.status.success());
    let text = context(&output);
    assert!(text.contains("## Repository outline"), "{text}");
    assert!(!text.contains("orchestration"), "{text}");
}

#[test]
fn missing_index_exits_zero_with_notice() {
    let output = session_start_with("hook-no-index", "claude", None, TARGETS, false);
    assert!(output.status.success());
    let text = context(&output);
    assert!(text.contains("`nav_map` skipped: index_missing"), "{text}");
    assert!(!text.contains("instruction block is installed"), "{text}");
}

#[test]
fn failed_provider_and_unknown_provider_are_notices() {
    let output = session_start_with(
        "hook-fail",
        "claude",
        Some(r#"["bogus", "nav_map", "toz_note"]"#),
        TARGETS,
        false,
    );
    assert!(output.status.success());
    let text = context(&output);
    assert!(
        text.contains("`bogus`") && text.contains("`nav_map` skipped"),
        "{text}"
    );
    assert!(!text.contains("instruction block is installed"), "{text}");
}

#[test]
fn legacy_providers_are_silently_skipped() {
    let output = session_start_with(
        "hook-legacy-providers",
        "claude",
        Some(r#"["orchestration", "toz_note"]"#),
        "\n[orchestration]\nmax_agents = 0\n\n[instructions]\ntargets = [\"{TARGET}\"]\n",
        false,
    );
    assert!(output.status.success());
    assert!(context(&output).is_empty());
    assert!(
        output.stderr.is_empty(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn setup_warning_is_absent_when_targets_are_configured() {
    let output = session_start_with("hook-targets", "claude", None, TARGETS, true);
    assert!(output.status.success());
    let text = context(&output);
    assert!(text.contains("## Repository outline"), "{text}");
    assert!(!text.contains("instruction block is installed"), "{text}");
    assert!(!String::from_utf8_lossy(&output.stderr).contains("instruction block is installed"));
}

#[test]
fn opencode_is_plain_text_without_toz_note() {
    let output = session_start_with(
        "hook-opencode",
        "opencode",
        Some(r#"["nav_map", "toz_note"]"#),
        TARGETS,
        true,
    );
    assert!(output.status.success());
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(text.contains("## Repository outline"), "{text}");
    assert!(
        !text.contains("TOZ") && !text.contains("hookSpecificOutput"),
        "{text}"
    );
}

#[test]
fn pi_is_plain_text_without_toz_note() {
    let output = session_start_with(
        "hook-pi",
        "pi",
        Some(r#"["nav_map", "toz_note"]"#),
        TARGETS,
        true,
    );
    assert!(output.status.success());
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(text.contains("## Repository outline"), "{text}");
    assert!(
        !text.contains("TOZ") && !text.contains("hookSpecificOutput"),
        "{text}"
    );
}

#[test]
fn opencode_notices_follow_output_in_plain_text() {
    let output = session_start("hook-oc-notice", "opencode", Some(r#"["bogus"]"#), false);
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(
        text.contains("`bogus`") && !text.contains("hookSpecificOutput"),
        "{text}"
    );
}
