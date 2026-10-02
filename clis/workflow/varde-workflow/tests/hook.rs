//! `hook session-start`: provider output, notices, and per-harness shape.

mod common;

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::{Command, Output};
use std::time::Duration;

fn stub(dir: &Path, name: &str, body: &str) {
    let path = dir.join(name);
    fs::write(&path, format!("#!/bin/sh\n{body}\n")).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
}

/// Run `hook session-start` with `bin_dir` as the only provider search path
/// (plus the system dirs the stub shell scripts need) and `providers` as the
/// optional `[hooks.session_start]` override.
fn session_start(
    name: &str,
    harness: &str,
    providers: Option<&str>,
    stubs: &[(&str, &str)],
) -> Output {
    session_start_with(name, harness, providers, "", stubs)
}

/// Like `session_start`, with `extra` raw TOML appended to the config.
fn session_start_with(
    name: &str,
    harness: &str,
    providers: Option<&str>,
    extra: &str,
    stubs: &[(&str, &str)],
) -> Output {
    let root = common::temp_bundle(name);
    let bin_dir = root.join("bin");
    fs::create_dir_all(&bin_dir).unwrap();
    for (tool, body) in stubs {
        stub(&bin_dir, tool, body);
    }
    let config_dir = root.join("config");
    fs::create_dir_all(&config_dir).unwrap();
    let mut config = String::new();
    if let Some(list) = providers {
        config.push_str(&format!("[hooks.session_start]\nproviders = {list}\n"));
    }
    config.push_str(extra);
    if !config.is_empty() {
        fs::write(config_dir.join("config.toml"), config).unwrap();
    }
    Command::new(common::bin())
        .args(["hook", "session-start", "--harness", harness])
        .current_dir(&root)
        .env("VARDE_CONFIG_DIR", &config_dir)
        .env("PATH", format!("{}:/usr/bin:/bin", bin_dir.display()))
        .output()
        .unwrap()
}

const BOTH: [(&str, &str); 2] = [
    ("varde-code", r#"echo "NAV $*""#),
    ("varde-toz", r#"echo "TOZ $*""#),
];

fn context(output: &Output) -> String {
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["hookSpecificOutput"]["hookEventName"], "SessionStart");
    value["hookSpecificOutput"]["additionalContext"]
        .as_str()
        .unwrap()
        .to_string()
}

#[test]
fn default_provider_emits_nav_map_and_setup_warning_without_targets() {
    let output = session_start("hook-default", "claude", None, &BOTH);
    assert!(output.status.success());
    let text = context(&output);
    assert!(text.starts_with("NAV nav_map --json"), "{text}");
    assert!(
        text.contains("--format text --with-project-knowledge"),
        "{text}"
    );
    assert!(text.contains(r#""repoRoot""#), "{text}");
    assert!(!text.contains("--harness"), "{text}");
    assert!(
        !text.contains("TOZ")
            && !text.contains("at most ")
            && !text.contains("references/orchestration.md"),
        "{text}"
    );
    assert!(
        text.contains("Varde will not work as designed until its instruction block is installed"),
        "{text}"
    );
}

#[test]
fn codex_uses_the_same_envelope_without_legacy_provider_output() {
    let output = session_start_with(
        "hook-codex",
        "codex",
        None,
        "\n[instructions]\ntargets = [\"/tmp/AGENTS.md\"]\n",
        &BOTH,
    );
    assert!(output.status.success());
    let text = context(&output);
    assert!(text.contains("NAV nav_map"), "{text}");
    assert!(
        !text.contains("TOZ") && !text.contains("orchestration"),
        "{text}"
    );
}

#[test]
fn missing_binary_exits_zero_with_notice() {
    let output = session_start_with(
        "hook-missing",
        "claude",
        None,
        "\n[instructions]\ntargets = [\"/tmp/AGENTS.md\"]\n",
        &[("varde-toz", "echo TOZ")],
    );
    assert!(output.status.success());
    let text = context(&output);
    assert!(
        text.contains("`nav_map` skipped: cannot run varde-code: No such file or directory"),
        "{text}"
    );
    assert!(!text.contains("instruction block is installed"), "{text}");
}

#[test]
fn nonzero_exit_and_unknown_provider_are_notices() {
    let output = session_start_with(
        "hook-fail",
        "claude",
        Some(r#"["bogus", "nav_map", "toz_note"]"#),
        "\n[instructions]\ntargets = [\"/tmp/AGENTS.md\"]\n",
        &[("varde-code", "exit 3"), ("varde-toz", "echo TOZ")],
    );
    assert!(output.status.success());
    let text = context(&output);
    assert!(
        text.contains("`bogus`") && text.contains("`nav_map` skipped"),
        "{text}"
    );
    assert!(
        !text.contains("TOZ") && !text.contains("instruction block is installed"),
        "{text}"
    );
}

#[test]
fn legacy_providers_are_silently_skipped() {
    let output = session_start_with(
        "hook-legacy-providers",
        "claude",
        Some(r#"["orchestration", "toz_note"]"#),
        "\n[orchestration]\nmax_agents = 0\n\n[instructions]\ntargets = [\"/tmp/AGENTS.md\"]\n",
        &BOTH,
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
    let output = session_start_with(
        "hook-targets",
        "claude",
        None,
        "\n[instructions]\ntargets = [\"/tmp/AGENTS.md\"]\n",
        &BOTH,
    );
    assert!(output.status.success());
    let text = context(&output);
    assert!(text.contains("NAV nav_map"), "{text}");
    assert!(!text.contains("instruction block is installed"), "{text}");
    assert!(!String::from_utf8_lossy(&output.stderr).contains("instruction block is installed"));
}

#[test]
fn opencode_is_plain_text_without_toz_note() {
    let output = session_start(
        "hook-opencode",
        "opencode",
        Some(r#"["nav_map", "toz_note"]"#),
        &BOTH,
    );
    assert!(output.status.success());
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(text.starts_with("NAV nav_map"), "{text}");
    assert!(
        !text.contains("TOZ") && !text.contains("hookSpecificOutput"),
        "{text}"
    );
}

#[test]
fn pi_is_plain_text_without_toz_note() {
    let output = session_start("hook-pi", "pi", Some(r#"["nav_map", "toz_note"]"#), &BOTH);
    assert!(output.status.success());
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(text.starts_with("NAV nav_map"), "{text}");
    assert!(
        !text.contains("TOZ") && !text.contains("hookSpecificOutput"),
        "{text}"
    );
}

#[test]
fn slow_provider_times_out_and_later_providers_still_run() {
    let output = session_start_with(
        "hook-timeout",
        "claude",
        Some(r#"["nav_map", "nav_map"]"#),
        "\n[instructions]\ntargets = [\"/tmp/AGENTS.md\"]\n",
        &[(
            "varde-code",
            "if [ -e hook-timeout-called ]; then echo NAV; else touch hook-timeout-called; exec sleep 30; fi",
        )],
    );
    assert!(output.status.success());
    let text = context(&output);
    assert!(
        text.starts_with("NAV") && text.contains("timed out"),
        "{text}"
    );
}

#[test]
fn provider_with_lingering_child_cannot_block_past_the_timeout() {
    let started = std::time::Instant::now();
    // No `exec`: the shell stays the parent of `sleep`, which holds the pipes.
    let output = session_start_with(
        "hook-grandchild",
        "claude",
        Some(r#"["nav_map", "nav_map"]"#),
        "\n[instructions]\ntargets = [\"/tmp/AGENTS.md\"]\n",
        &[(
            "varde-code",
            "if [ -e hook-grandchild-called ]; then echo NAV; else touch hook-grandchild-called; sleep 12; fi",
        )],
    );
    assert!(output.status.success());
    assert!(
        started.elapsed() < Duration::from_secs(8),
        "{:?}",
        started.elapsed()
    );
    let text = context(&output);
    assert!(
        text.starts_with("NAV") && text.contains("timed out"),
        "{text}"
    );
}

#[test]
fn opencode_notices_follow_output_in_plain_text() {
    let output = session_start("hook-oc-notice", "opencode", Some(r#"["bogus"]"#), &BOTH);
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(
        text.contains("`bogus`") && !text.contains("hookSpecificOutput"),
        "{text}"
    );
}

// ---- hook install / remove ----

fn hook_cmd(action: &str, harness: &str, home: &Path, extra: &[&str]) -> Output {
    let mut command = Command::new(common::bin());
    command
        .args(["hook", action, "--harness", harness])
        .args(extra)
        .env("HOME", home)
        .env("XDG_CONFIG_HOME", home.join("xdg"))
        .env("PATH", "/usr/bin:/bin");
    command.output().unwrap()
}

fn read_json(path: &Path) -> serde_json::Value {
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn session_start_commands(root: &serde_json::Value) -> Vec<String> {
    let Some(groups) = root["hooks"]["SessionStart"].as_array() else {
        return Vec::new();
    };
    groups
        .iter()
        .flat_map(|g| g["hooks"].as_array().cloned().unwrap_or_default())
        .map(|h| h["command"].as_str().unwrap().to_string())
        .collect()
}

fn json_target(home: &Path, harness: &str) -> std::path::PathBuf {
    match harness {
        "claude" => home.join(".claude/settings.json"),
        _ => home.join(".codex/hooks.json"),
    }
}

const FOREIGN: &str = r#"{
  "model": "x",
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "/opt/other-tool start", "timeout": 5}]},
      {"hooks": [{"type": "command", "command": "/usr/bin/varde-code session"}]}
    ],
    "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "keep-me"}]}]
  }
}"#;

#[test]
fn install_twice_leaves_one_entry_and_remove_keeps_foreign() {
    for harness in ["claude", "codex"] {
        let home = common::temp_bundle(&format!("hook-inst-{harness}"));
        let target = json_target(&home, harness);
        fs::create_dir_all(target.parent().unwrap()).unwrap();
        fs::write(&target, FOREIGN).unwrap();

        for _ in 0..2 {
            let out = hook_cmd("install", harness, &home, &[]);
            assert!(out.status.success(), "{out:?}");
        }
        let json = read_json(&target);
        let ours: Vec<String> = session_start_commands(&json)
            .into_iter()
            .filter(|c| c.contains("hook session-start"))
            .collect();
        assert_eq!(ours.len(), 1, "{json}");
        assert!(
            ours[0].ends_with(&format!(
                "varde-workflow hook session-start --harness {harness}"
            )) && ours[0].starts_with('/'),
            "{}",
            ours[0]
        );
        let entry = json["hooks"]["SessionStart"]
            .as_array()
            .unwrap()
            .iter()
            .flat_map(|g| g["hooks"].as_array().unwrap())
            .find(|h| h["command"] == ours[0].as_str())
            .unwrap()
            .clone();
        assert_eq!(entry["type"], "command");
        assert_eq!(entry["timeout"], 20);
        assert_eq!(json["model"], "x");
        assert_eq!(
            json["hooks"]["PostToolUse"][0]["hooks"][0]["command"],
            "keep-me"
        );

        let out = hook_cmd("remove", harness, &home, &[]);
        assert!(out.status.success(), "{out:?}");
        let json = read_json(&target);
        assert_eq!(
            session_start_commands(&json),
            ["/opt/other-tool start", "/usr/bin/varde-code session"]
        );
        assert_eq!(json["model"], "x");
    }
}

#[test]
fn install_creates_missing_file_and_remove_drops_empty_arrays() {
    let home = common::temp_bundle("hook-inst-create");
    let target = json_target(&home, "codex");
    assert!(hook_cmd("install", "codex", &home, &[]).status.success());
    assert_eq!(session_start_commands(&read_json(&target)).len(), 1);
    assert!(hook_cmd("remove", "codex", &home, &[]).status.success());
    assert!(read_json(&target)["hooks"].get("SessionStart").is_none());
}

#[test]
fn dry_run_writes_nothing() {
    let home = common::temp_bundle("hook-inst-dry");
    for harness in ["claude", "codex", "opencode"] {
        let out = hook_cmd("install", harness, &home, &["--dry-run"]);
        assert!(out.status.success(), "{out:?}");
        assert!(!String::from_utf8_lossy(&out.stdout).is_empty());
    }
    assert!(!home.join(".claude").exists());
    assert!(!home.join(".codex").exists());
    assert!(!home.join("xdg").exists());
}

/// Install the opencode plugin with `bin` as the only non-system PATH entry.
fn install_opencode(home: &Path, bin: &Path) -> String {
    let out = Command::new(common::bin())
        .args(["hook", "install", "--harness", "opencode"])
        .env("HOME", home)
        .env("XDG_CONFIG_HOME", home.join("xdg"))
        .env("PATH", format!("{}:/usr/bin:/bin", bin.display()))
        .output()
        .unwrap();
    assert!(out.status.success(), "{out:?}");
    fs::read_to_string(home.join("xdg/opencode/plugin/varde-session.ts")).unwrap()
}

#[test]
fn opencode_plugin_written_selected_by_version_and_removed() {
    let home = common::temp_bundle("hook-inst-oc");
    let plugin = home.join("xdg/opencode/plugin/varde-session.ts");
    let bin = home.join("bin");
    fs::create_dir_all(&bin).unwrap();
    let is_v1 = |text: &str| text.contains("experimental.chat.system.transform");
    let is_v2 = |text: &str| text.contains("session.hook(\"context\"");

    // No opencode on PATH: unknown version defaults to the 1.x plugin.
    let text = install_opencode(&home, &bin);
    assert!(text.contains("hook\", \"session-start\"") && text.contains("varde-workflow"));
    assert!(is_v1(&text) && !is_v2(&text) && !text.contains("{{"));
    // Child (subagent) sessions get no brief: the v1 hook skips sessions that have a parentID.
    assert!(text.contains("client.session.get") && text.contains("res.data.parentID"));
    assert!(text.contains("input.sessionID") && text.contains("new Map<string, boolean>()"));
    // The lookup is bounded so a slow host cannot stall the request; a timeout injects.
    assert!(text.contains("Promise.race") && text.contains("LOOKUP_TIMEOUT_MS"));

    stub(&bin, "opencode", "echo 2.0.1");
    let text = install_opencode(&home, &bin);
    assert!(is_v2(&text) && !is_v1(&text) && !text.contains("{{"));
    // The v2 hook has the same child guard and bounded lookup.
    assert!(text.contains("ctx.session.get({ sessionID: event.sessionID })"));
    assert!(text.contains("parentID") && text.contains("new Map<string, boolean>()"));
    assert!(text.contains("Promise.race") && text.contains("LOOKUP_TIMEOUT_MS"));

    stub(&bin, "opencode", "echo 1.4.2");
    assert!(is_v1(&install_opencode(&home, &bin)));

    stub(&bin, "opencode", "echo not-a-version");
    assert!(is_v1(&install_opencode(&home, &bin)));

    assert!(hook_cmd("remove", "opencode", &home, &[]).status.success());
    assert!(!plugin.exists());
    assert!(hook_cmd("remove", "opencode", &home, &[]).status.success());
}

#[test]
fn provider_error_json_becomes_a_notice() {
    let error = r#"{"data":{"error":{"code":"index_missing"}},"ok":false}"#;
    let output = session_start_with(
        "hook-err-json",
        "claude",
        Some(r#"["nav_map", "toz_note"]"#),
        "\n[instructions]\ntargets = [\"/tmp/AGENTS.md\"]\n",
        &[
            ("varde-code", &format!("echo '{error}'")),
            ("varde-toz", "echo TOZ"),
        ],
    );
    assert!(output.status.success());
    let text = context(&output);
    assert!(text.contains("`nav_map` skipped: index_missing"), "{text}");
    assert!(!text.contains("\"ok\""), "{text}");
    assert!(!text.contains("TOZ"), "{text}");
}

#[test]
fn json_looking_text_without_ok_false_is_kept() {
    let output = session_start(
        "hook-ok-json",
        "claude",
        Some(r#"["nav_map"]"#),
        &[("varde-code", r#"echo '{"ok":true,"x":1}'"#)],
    );
    assert!(context(&output).contains(r#""ok":true"#));
}

fn pi_cmd(action: &str, home: &Path, agent_dir: Option<&Path>) -> Output {
    let mut command = Command::new(common::bin());
    command
        .args(["hook", action, "--harness", "pi"])
        .env("HOME", home)
        .env("PATH", "/usr/bin:/bin")
        .env_remove("PI_CODING_AGENT_DIR");
    if let Some(dir) = agent_dir {
        command.env("PI_CODING_AGENT_DIR", dir);
    }
    command.output().unwrap()
}

#[test]
fn pi_extension_installs_idempotently_and_removes() {
    let home = common::temp_bundle("hook-inst-pi");
    let agent = home.join("custom-agent");
    for (dir, file) in [
        (
            Some(agent.as_path()),
            agent.join("extensions/varde-session.ts"),
        ),
        (None, home.join(".pi/agent/extensions/varde-session.ts")),
    ] {
        assert!(pi_cmd("install", &home, dir).status.success());
        let first = fs::read_to_string(&file).unwrap();
        assert!(pi_cmd("install", &home, dir).status.success());
        assert_eq!(first, fs::read_to_string(&file).unwrap());
        assert!(!first.contains("{{") && first.contains("varde-workflow"));
        assert!(first.contains("\"--harness\", \"pi\""));
        // Child (subagent) sessions get no brief, evaluated on every call.
        assert!(first.contains("before_agent_start"));
        assert!(first.contains("getSessionFile()") && first.contains("getHeader()?.parentSession"));
        assert!(first.contains("event.systemPrompt"));
        assert!(pi_cmd("remove", &home, dir).status.success());
        assert!(!file.exists());
        assert!(pi_cmd("remove", &home, dir).status.success());
    }
}

#[test]
fn install_removes_legacy_varde_code_nav_map_entries_for_codex_only() {
    const LEGACY: &str = r#"{
      "hooks": {
        "SessionStart": [
          {"hooks": [{"type": "command", "command": "/h/.cargo/bin/varde-code nav_map --json \"{\\\"repoRoot\\\":\\\"$(pwd)\\\"}\" --format text"}]},
          {"hooks": [
            {"type": "command", "command": "'/opt/x/varde-code' nav_map --format text"},
            {"type": "command", "command": "/opt/other-tool nav_map"}
          ]},
          {"hooks": [{"type": "command", "command": "/usr/bin/varde-code session"}]}
        ]
      }
    }"#;
    for harness in ["claude", "codex"] {
        let home = common::temp_bundle(&format!("hook-legacy-{harness}"));
        let target = json_target(&home, harness);
        fs::create_dir_all(target.parent().unwrap()).unwrap();
        fs::write(&target, LEGACY).unwrap();

        let dry = hook_cmd("install", harness, &home, &["--dry-run"]);
        assert!(dry.status.success(), "{dry:?}");
        assert_eq!(fs::read_to_string(&target).unwrap(), LEGACY);
        assert_eq!(
            String::from_utf8_lossy(&dry.stdout).contains("legacy varde-code"),
            harness == "codex",
            "{dry:?}"
        );

        for _ in 0..2 {
            let out = hook_cmd("install", harness, &home, &[]);
            assert!(out.status.success(), "{out:?}");
        }
        let commands = session_start_commands(&read_json(&target));
        if harness == "claude" {
            // varde-code owns its Claude entry; install leaves it alone.
            assert_eq!(commands.len(), 5, "{commands:?}");
            assert!(commands[0].contains("varde-code nav_map"));
            assert!(commands[4].contains("varde-workflow hook session-start"));
            continue;
        }
        assert_eq!(commands.len(), 3, "{commands:?}");
        assert_eq!(commands[0], "/opt/other-tool nav_map");
        assert_eq!(commands[1], "/usr/bin/varde-code session");
        assert!(commands[2].contains("varde-workflow hook session-start"));
    }
}

#[test]
fn remove_without_a_config_file_creates_nothing() {
    let home = common::temp_bundle("hook-remove-missing");
    let out = hook_cmd("remove", "codex", &home, &[]);
    assert!(out.status.success(), "{out:?}");
    assert!(!json_target(&home, "codex").exists());
}

#[test]
fn install_keeps_symlink_and_permissions() {
    use std::os::unix::fs::symlink;
    let home = common::temp_bundle("hook-symlink");
    let dotfiles = home.join("dotfiles");
    fs::create_dir_all(&dotfiles).unwrap();
    let real = dotfiles.join("settings.json");
    fs::write(&real, FOREIGN).unwrap();
    fs::set_permissions(&real, fs::Permissions::from_mode(0o600)).unwrap();
    let link = json_target(&home, "claude");
    fs::create_dir_all(link.parent().unwrap()).unwrap();
    symlink(&real, &link).unwrap();

    let out = hook_cmd("install", "claude", &home, &[]);
    assert!(out.status.success(), "{out:?}");
    assert!(
        fs::symlink_metadata(&link)
            .unwrap()
            .file_type()
            .is_symlink()
    );
    assert_eq!(
        fs::metadata(&real).unwrap().permissions().mode() & 0o777,
        0o600
    );
    let commands = session_start_commands(&read_json(&real));
    assert!(commands.iter().any(|c| c.contains("hook session-start")));
}
