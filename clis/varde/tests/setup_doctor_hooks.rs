//! `varde setup doctor` reports the unified hook installation per harness.

use serde_json::Value;
use std::fs;
use std::path::PathBuf;
use std::process::{Command, Output};
use tempfile::TempDir;

struct Env {
    home: TempDir,
    config: TempDir,
    bin: TempDir,
}

impl Env {
    fn new() -> Self {
        Env {
            home: TempDir::new().unwrap(),
            config: TempDir::new().unwrap(),
            bin: TempDir::new().unwrap(),
        }
    }

    fn path(&self, relative: &str) -> PathBuf {
        self.home.path().join(relative)
    }

    fn varde(&self, args: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(args)
            .env("HOME", self.home.path())
            .env("PATH", self.bin.path())
            .env("TOZ_CONFIG_DIR", self.config.path().join("toz"))
            .env("VARDE_CONFIG_DIR", self.config.path().join("varde"))
            .env_remove("XDG_CONFIG_HOME")
            .env_remove("PI_CODING_AGENT_DIR")
            .current_dir(self.home.path())
            .output()
            .unwrap()
    }

    fn install(&self) {
        let output = self.varde(&["setup", "hooks", "install"]);
        assert!(output.status.success());
    }

    fn hooks(&self) -> Vec<Value> {
        let output = self.varde(&["setup", "doctor", "--json"]);
        let report: Value = serde_json::from_slice(&output.stdout).unwrap();
        report["hooks"].as_array().unwrap().clone()
    }

    fn state(&self, harness: &str, target: &str) -> String {
        let hooks = self.hooks();
        let entry = hooks
            .iter()
            .find(|entry| entry["harness"] == harness && entry["target"] == target)
            .unwrap_or_else(|| panic!("no {harness} {target} in {hooks:?}"));
        entry["state"].as_str().unwrap().to_owned()
    }
}

#[test]
fn installed_hooks_are_current() {
    let e = Env::new();
    e.install();
    for (harness, target) in [
        ("claude", "SessionStart"),
        ("claude", "PostToolUse"),
        ("claude", "UserPromptSubmit"),
        ("codex", "SessionStart"),
        ("codex", "PostToolUse"),
        ("codex", "UserPromptSubmit"),
        ("opencode", "plugin"),
        ("pi", "plugin"),
    ] {
        assert_eq!(e.state(harness, target), "current", "{harness} {target}");
    }
    assert_eq!(
        e.state("opencode", "user-prompt-submit"),
        "unsupported",
        "opencode has no per-user-prompt context hook"
    );
}

#[test]
fn missing_hooks_name_the_fix() {
    let e = Env::new();
    let hooks = e.hooks();
    assert_eq!(hooks.len(), 9);
    for entry in &hooks {
        if entry["state"] == "unsupported" {
            assert!(
                entry["reason"].as_str().unwrap().contains("model call"),
                "{entry}"
            );
            continue;
        }
        assert_eq!(entry["state"], "missing", "{entry}");
        assert!(
            entry["fix"]
                .as_str()
                .unwrap()
                .contains("setup hooks install"),
            "{entry}"
        );
    }
    let text = e.varde(&["setup", "doctor"]);
    let stdout = String::from_utf8(text.stdout).unwrap();
    assert!(
        stdout.contains("hook claude SessionStart: missing"),
        "{stdout}"
    );
    assert!(
        stdout.contains("hook opencode user-prompt-submit: unsupported"),
        "{stdout}"
    );
}

#[test]
fn edited_entries_and_plugins_are_reported() {
    let e = Env::new();
    e.install();
    let settings = e.path(".claude/settings.json");
    let edited = fs::read_to_string(&settings)
        .unwrap()
        .replace("\"timeout\": 30", "\"timeout\": 31");
    fs::write(&settings, edited).unwrap();
    let plugin = e.path(".pi/agent/extensions/varde.ts");
    fs::write(
        &plugin,
        format!("{}\n// mine\n", fs::read_to_string(&plugin).unwrap()),
    )
    .unwrap();

    assert_eq!(e.state("claude", "PostToolUse"), "edited");
    assert_eq!(e.state("claude", "SessionStart"), "current");
    assert_eq!(e.state("pi", "plugin"), "edited");
    assert_eq!(e.state("codex", "PostToolUse"), "current");
}

#[test]
fn hook_state_does_not_change_the_exit_code() {
    let e = Env::new();
    let with_missing = e.varde(&["setup", "doctor"]).status.code();
    e.install();
    assert_eq!(e.varde(&["setup", "doctor"]).status.code(), with_missing);
}
