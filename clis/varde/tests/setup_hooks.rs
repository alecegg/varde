//! `varde setup hooks install|remove`: one Varde entry per event, foreign
//! entries untouched, edited entries kept until `--force`.

use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;
use std::process::{Command, Output};
use tempfile::TempDir;

struct Env {
    home: TempDir,
    bin: TempDir,
}

impl Env {
    fn new() -> Self {
        Env {
            home: TempDir::new().unwrap(),
            bin: TempDir::new().unwrap(),
        }
    }

    fn path(&self, relative: &str) -> PathBuf {
        self.home.path().join(relative)
    }

    fn varde(&self, args: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(["setup", "hooks"])
            .args(args)
            .env("HOME", self.home.path())
            .env("PATH", self.bin.path())
            .env_remove("XDG_CONFIG_HOME")
            .env_remove("PI_CODING_AGENT_DIR")
            .output()
            .unwrap()
    }

    fn sync(&self, args: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(["setup", "sync"])
            .args(args)
            .env("HOME", self.home.path())
            .env("PATH", self.bin.path())
            .env_remove("XDG_CONFIG_HOME")
            .env_remove("PI_CODING_AGENT_DIR")
            .output()
            .unwrap()
    }

    fn ok(&self, args: &[&str]) -> String {
        let output = self.varde(args);
        assert!(
            output.status.success(),
            "{args:?}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout).unwrap()
    }

    fn json(&self, relative: &str) -> Value {
        serde_json::from_str(&fs::read_to_string(self.path(relative)).unwrap()).unwrap()
    }

    fn fake_opencode(&self, version: &str) {
        use std::os::unix::fs::PermissionsExt;
        let script = self.bin.path().join("opencode");
        fs::write(&script, format!("#!/bin/sh\necho {version}\n")).unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();
    }

    fn seed(&self, relative: &str, value: &Value) {
        let path = self.path(relative);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, serde_json::to_string_pretty(value).unwrap()).unwrap();
    }
}

const CLAUDE: &str = ".claude/settings.json";
const CODEX: &str = ".codex/hooks.json";

fn foreign() -> Value {
    json!({
        "theme": "dark",
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "echo foreign-start"}]}],
            "PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo foreign-post"}]}],
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo foreign-prompt"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "echo foreign-stop"}]}]
        }
    })
}

fn commands(doc: &Value, event: &str) -> Vec<String> {
    doc["hooks"][event]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default()
        .iter()
        .flat_map(|group| group["hooks"].as_array().unwrap())
        .map(|hook| hook["command"].as_str().unwrap().to_owned())
        .collect()
}

fn varde_commands(doc: &Value, event: &str) -> Vec<String> {
    commands(doc, event)
        .into_iter()
        .filter(|command| command.contains(" hook "))
        .collect()
}

#[test]
fn claude_and_codex_get_one_entry_per_event_and_keep_foreign_hooks() {
    let env = Env::new();
    env.seed(CLAUDE, &foreign());
    env.seed(CODEX, &foreign());
    let out = env.ok(&["install", "--harness", "claude", "--harness", "codex"]);
    assert!(out.contains("hooks = true"), "{out}");

    for (file, harness) in [(CLAUDE, "claude"), (CODEX, "codex")] {
        let doc = env.json(file);
        assert_eq!(doc["theme"], "dark");
        assert_eq!(
            varde_commands(&doc, "SessionStart").len(),
            1,
            "{file}: {doc}"
        );
        let post = varde_commands(&doc, "PostToolUse");
        assert_eq!(post.len(), 1, "{file}: {doc}");
        assert!(post[0].ends_with(&format!("hook post-tool-use --harness {harness}")));
        assert!(
            varde_commands(&doc, "SessionStart")[0]
                .ends_with(&format!("hook session-start --harness {harness}"))
        );
        assert!(commands(&doc, "SessionStart").contains(&"echo foreign-start".to_owned()));
        assert!(commands(&doc, "PostToolUse").contains(&"echo foreign-post".to_owned()));
        let prompt = varde_commands(&doc, "UserPromptSubmit");
        assert_eq!(prompt.len(), 1, "{file}: {doc}");
        assert!(prompt[0].ends_with(&format!("hook user-prompt-submit --harness {harness}")));
        assert!(
            commands(&doc, "UserPromptSubmit").contains(&"echo foreign-prompt".to_owned()),
            "{file}: {doc}"
        );
        let prompt_group = doc["hooks"]["UserPromptSubmit"]
            .as_array()
            .unwrap()
            .iter()
            .find(|group| {
                group["hooks"][0]["command"]
                    .as_str()
                    .unwrap()
                    .contains(" hook ")
            })
            .unwrap();
        assert!(prompt_group.get("matcher").is_none(), "{file}: {doc}");
        assert_eq!(commands(&doc, "Stop"), ["echo foreign-stop"]);
        let matcher = doc["hooks"]["PostToolUse"]
            .as_array()
            .unwrap()
            .iter()
            .find(|group| {
                group["hooks"][0]["command"]
                    .as_str()
                    .unwrap()
                    .contains(" hook ")
            })
            .unwrap()["matcher"]
            .clone();
        assert_eq!(matcher, "*");
    }
}

#[test]
fn install_creates_missing_files_and_is_idempotent() {
    let env = Env::new();
    env.ok(&["install"]);
    let files = [
        CLAUDE,
        CODEX,
        ".config/opencode/plugin/varde.ts",
        ".pi/agent/extensions/varde.ts",
    ];
    let first: Vec<String> = files
        .iter()
        .map(|file| fs::read_to_string(env.path(file)).unwrap())
        .collect();
    let again = env.ok(&["install"]);
    assert!(!again.contains("blocked"), "{again}");
    for (file, before) in files.iter().zip(first) {
        assert_eq!(
            fs::read_to_string(env.path(file)).unwrap(),
            before,
            "{file}"
        );
    }
    for event in ["SessionStart", "PostToolUse", "UserPromptSubmit"] {
        assert_eq!(varde_commands(&env.json(CLAUDE), event).len(), 1);
    }
}

#[test]
fn opencode_and_pi_get_one_plugin_and_never_inject_the_toz_note() {
    let env = Env::new();
    let out = env.ok(&["install", "--harness", "opencode", "--harness", "pi"]);
    let opencode = fs::read_to_string(env.path(".config/opencode/plugin/varde.ts")).unwrap();
    let pi = fs::read_to_string(env.path(".pi/agent/extensions/varde.ts")).unwrap();
    for (text, harness) in [(&opencode, "opencode"), (&pi, "pi")] {
        assert!(text.contains(&format!(
            "\"hook\", \"session-start\", \"--harness\", \"{harness}\""
        )));
        assert!(text.contains(&format!(
            "\"hook\", \"post-tool-use\", \"--harness\", \"{harness}\""
        )));
        assert!(!text.contains("{{VARDE_BIN}}") && !text.contains("NOTE"));
        assert!(!text.contains("\"note\""));
    }
    assert!(pi.contains("\"hook\", \"user-prompt-submit\", \"--harness\", \"pi\""));
    assert!(!opencode.contains("user-prompt-submit"));
    assert!(
        out.contains("opencode: user-prompt-submit unsupported"),
        "{out}"
    );
    assert!(
        opencode.contains("@opencode/plugin"),
        "2.x plugin by default"
    );
    let retired = ["varde", "toz"].join("-");
    assert!(
        !env.path(&format!(".config/opencode/plugin/{retired}.ts"))
            .exists()
    );
}

#[test]
fn opencode_before_2_gets_the_1x_plugin() {
    let env = Env::new();
    env.fake_opencode("1.9.2");
    env.ok(&["install", "--harness", "opencode"]);
    let text = fs::read_to_string(env.path(".config/opencode/plugin/varde.ts")).unwrap();
    assert!(text.contains("@opencode-ai/plugin"));
    env.fake_opencode("2.0.1");
    env.ok(&["install", "--harness", "opencode"]);
    let text = fs::read_to_string(env.path(".config/opencode/plugin/varde.ts")).unwrap();
    assert!(
        text.contains("@opencode/plugin"),
        "an unedited plugin upgrades in place"
    );
}

#[test]
fn opencode_and_pi_plugins_follow_selected_features() {
    for (feature, session, toz, post, inbox) in [
        ("learn", false, false, false, false),
        ("toz", true, true, true, false),
        ("change", false, false, true, true),
    ] {
        for harness in ["opencode", "pi"] {
            let env = Env::new();
            env.ok(&["install", "--harness", harness, "--features", feature]);
            let path = if harness == "opencode" {
                ".config/opencode/plugin/varde.ts"
            } else {
                ".pi/agent/extensions/varde.ts"
            };
            let text = fs::read_to_string(env.path(path)).unwrap();
            let has_session = if harness == "opencode" {
                text.contains("ctx.session.hook(\"context\"")
            } else {
                text.contains("pi.on(\"before_agent_start\"")
                    && text.contains("sessionContext(process.cwd(), sessionId)")
            };
            let has_toz = if harness == "opencode" {
                text.contains("ctx.shell.hook(\"create.before\"")
            } else {
                feature == "toz" && text.contains("sessionContext(process.cwd(), sessionId)")
            };
            let has_post = if harness == "opencode" {
                text.contains("ctx.tool.hook(\"execute.after\"")
            } else {
                text.contains("pi.on(\"tool_result\"")
            };
            let has_inbox = text.contains("promptInbox(process.cwd(), sessionId)");
            assert_eq!(has_session, session, "{harness} {feature}");
            assert_eq!(has_toz, toz, "{harness} {feature}");
            assert_eq!(has_post, post, "{harness} {feature}");
            assert_eq!(has_inbox, inbox && harness == "pi", "{harness} {feature}");
        }
    }
}

fn edit_then_force(event: &str, edit: impl Fn(&mut Value)) {
    let env = Env::new();
    env.ok(&["install", "--harness", "claude"]);
    let mut doc = env.json(CLAUDE);
    edit(&mut doc["hooks"][event][0]);
    fs::write(
        env.path(CLAUDE),
        serde_json::to_string_pretty(&doc).unwrap(),
    )
    .unwrap();
    let edited = env.json(CLAUDE)["hooks"][event].clone();

    let out = env.ok(&["install", "--harness", "claude"]);
    assert!(
        out.contains("blocked") && out.contains(event) && out.contains(".claude/settings.json"),
        "{out}"
    );
    assert!(
        out.contains("varde setup hooks install --harness claude --force"),
        "{out}"
    );
    assert_eq!(
        env.json(CLAUDE)["hooks"][event],
        edited,
        "an edited entry is kept as is"
    );
    assert_eq!(varde_commands(&env.json(CLAUDE), event).len(), 1);

    let removed = env.ok(&["remove", "--harness", "claude"]);
    assert!(removed.contains("blocked"), "{removed}");
    assert_eq!(env.json(CLAUDE)["hooks"][event], edited);

    env.ok(&["install", "--harness", "claude", "--force"]);
    let forced = env.json(CLAUDE);
    assert_eq!(varde_commands(&forced, event).len(), 1);
    assert!(!forced.to_string().contains("--edited"), "{forced}");
    assert_eq!(forced["hooks"][event].as_array().unwrap().len(), 1);
}

#[test]
fn an_edited_session_start_entry_is_kept_until_force() {
    edit_then_force("SessionStart", |group| {
        let command = group["hooks"][0]["command"].as_str().unwrap().to_owned();
        group["hooks"][0]["command"] = json!(format!("{command} --edited"));
    });
}

#[test]
fn an_edited_post_tool_use_entry_is_kept_until_force() {
    edit_then_force("PostToolUse", |group| {
        group["hooks"][0]["timeout"] = json!(99);
        group["matcher"] = json!("Bash --edited");
    });
}

#[test]
fn a_group_with_an_extra_key_is_edited() {
    edit_then_force("SessionStart", |group| group["disabled"] = json!(true));
    edit_then_force("PostToolUse", |group| group["disabled"] = json!(true));
}

#[test]
fn a_group_with_a_second_hook_is_kept_and_reported() {
    let env = Env::new();
    env.ok(&["install", "--harness", "claude"]);
    let mut doc = env.json(CLAUDE);
    doc["hooks"]["SessionStart"][0]["hooks"]
        .as_array_mut()
        .unwrap()
        .push(json!({"type": "command", "command": "echo sibling"}));
    fs::write(env.path(CLAUDE), doc.to_string()).unwrap();
    let edited = env.json(CLAUDE)["hooks"]["SessionStart"].clone();
    let out = env.ok(&["install", "--harness", "claude"]);
    assert!(
        out.contains("blocked") && out.contains("SessionStart"),
        "{out}"
    );
    assert_eq!(env.json(CLAUDE)["hooks"]["SessionStart"], edited);
}

#[test]
fn an_env_wrapped_varde_command_is_edited_not_duplicated() {
    let env = Env::new();
    let wrapped = "env FOO=1 /opt/bin/varde hook session-start --harness claude";
    env.seed(
        CLAUDE,
        &json!({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": wrapped, "timeout": 20}]}]}}),
    );
    let before = env.json(CLAUDE)["hooks"]["SessionStart"].clone();
    let out = env.ok(&["install", "--harness", "claude"]);
    assert!(
        out.contains("blocked") && out.contains("SessionStart"),
        "{out}"
    );
    let doc = env.json(CLAUDE);
    assert_eq!(doc["hooks"]["SessionStart"], before);
    assert_eq!(varde_commands(&doc, "SessionStart"), vec![wrapped]);
    assert_eq!(varde_commands(&doc, "PostToolUse").len(), 1);

    env.ok(&["install", "--harness", "claude", "--force"]);
    let forced = env.json(CLAUDE);
    assert_eq!(varde_commands(&forced, "SessionStart").len(), 1);
    assert!(!forced.to_string().contains("env FOO=1"), "{forced}");
}

#[test]
fn a_stalled_opencode_does_not_hang_install_and_remove_skips_it() {
    use std::os::unix::fs::PermissionsExt;
    let env = Env::new();
    let script = env.bin.path().join("opencode");
    fs::write(&script, "#!/bin/sh\nexec /bin/sleep 60\n").unwrap();
    fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();
    let started = std::time::Instant::now();
    env.ok(&["install", "--harness", "opencode"]);
    assert!(started.elapsed() < std::time::Duration::from_secs(10));
    let text = fs::read_to_string(env.path(".config/opencode/plugin/varde.ts")).unwrap();
    assert!(
        text.contains("@opencode/plugin"),
        "falls back to the 2.x plugin"
    );

    let marker = env.bin.path().join("probed");
    fs::write(
        &script,
        format!(
            "#!/bin/sh\n/usr/bin/touch {}\necho 2.0.0\n",
            marker.display()
        ),
    )
    .unwrap();
    env.ok(&["remove", "--harness", "opencode"]);
    assert!(!marker.exists(), "remove must not run opencode");
    assert!(!env.path(".config/opencode/plugin/varde.ts").exists());
}

#[test]
fn an_edit_blocks_only_its_own_event() {
    let env = Env::new();
    env.ok(&["install", "--harness", "codex"]);
    let mut doc = env.json(CODEX);
    doc["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] = json!(1);
    fs::write(env.path(CODEX), doc.to_string()).unwrap();
    // Remove only the PostToolUse entry by hand; install must restore it.
    let mut doc = env.json(CODEX);
    doc["hooks"].as_object_mut().unwrap().remove("PostToolUse");
    fs::write(env.path(CODEX), doc.to_string()).unwrap();

    let out = env.ok(&["install", "--harness", "codex"]);
    assert!(
        out.contains("blocked") && out.contains("SessionStart"),
        "{out}"
    );
    let doc = env.json(CODEX);
    assert_eq!(varde_commands(&doc, "PostToolUse").len(), 1);
    assert_eq!(doc["hooks"]["SessionStart"][0]["hooks"][0]["timeout"], 1);
}

#[test]
fn remove_deletes_only_unified_entries_and_files() {
    let env = Env::new();
    env.seed(CLAUDE, &foreign());
    let before = env.json(CLAUDE);
    env.ok(&["install"]);
    env.ok(&["remove"]);
    assert_eq!(env.json(CLAUDE), before);
    assert!(!env.path(".config/opencode/plugin/varde.ts").exists());
    assert!(!env.path(".pi/agent/extensions/varde.ts").exists());
    let codex = env.json(CODEX);
    assert!(codex.get("hooks").is_none(), "{codex}");
    let again = env.ok(&["remove"]);
    assert!(again.contains("nothing to remove"), "{again}");
}

#[test]
fn an_edited_plugin_file_is_kept_until_force() {
    let env = Env::new();
    env.ok(&["install", "--harness", "pi"]);
    let path = env.path(".pi/agent/extensions/varde.ts");
    let edited = format!("{}// mine\n", fs::read_to_string(&path).unwrap());
    fs::write(&path, &edited).unwrap();

    let out = env.ok(&["install", "--harness", "pi"]);
    assert!(out.contains("blocked") && out.contains("varde.ts"), "{out}");
    assert!(
        out.contains("varde setup hooks install --harness pi --force"),
        "{out}"
    );
    assert_eq!(fs::read_to_string(&path).unwrap(), edited);
    assert!(env.ok(&["remove", "--harness", "pi"]).contains("blocked"));
    assert!(path.exists());

    env.ok(&["install", "--harness", "pi", "--force"]);
    assert!(!fs::read_to_string(&path).unwrap().contains("// mine"));
    env.ok(&["remove", "--harness", "pi"]);
    assert!(!path.exists());
}

#[test]
fn a_foreign_file_at_the_plugin_path_is_not_overwritten() {
    let env = Env::new();
    let path = env.path(".config/opencode/plugin/varde.ts");
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(&path, "export default {}\n").unwrap();
    let out = env.ok(&["install", "--harness", "opencode"]);
    assert!(out.contains("blocked"), "{out}");
    assert_eq!(fs::read_to_string(&path).unwrap(), "export default {}\n");
}

#[test]
fn a_moved_varde_path_is_updated_not_blocked() {
    let env = Env::new();
    env.seed(
        CLAUDE,
        &json!({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "/old/place/varde hook session-start --harness claude", "timeout": 20}]}]}}),
    );
    let out = env.ok(&["install", "--harness", "claude"]);
    assert!(!out.contains("blocked"), "{out}");
    let doc = env.json(CLAUDE);
    assert_eq!(varde_commands(&doc, "SessionStart").len(), 1);
    assert!(!doc.to_string().contains("/old/place"));
}

#[test]
fn skip_event_leaves_one_event_alone() {
    let env = Env::new();
    let out = env.ok(&[
        "install",
        "--harness",
        "claude",
        "--skip-event",
        "UserPromptSubmit",
    ]);
    assert!(out.contains("skipped UserPromptSubmit"), "{out}");
    let doc = env.json(CLAUDE);
    assert!(doc["hooks"].get("UserPromptSubmit").is_none(), "{doc}");
    assert_eq!(varde_commands(&doc, "SessionStart").len(), 1);
    assert_eq!(varde_commands(&doc, "PostToolUse").len(), 1);
}

#[test]
fn selected_features_install_only_their_hook_events() {
    let env = Env::new();
    env.seed(CLAUDE, &foreign());
    env.ok(&["install", "--harness", "claude"]);
    let out = env.ok(&["install", "--harness", "claude", "--features", "toz,code"]);
    assert!(out.contains("removed UserPromptSubmit"), "{out}");
    let doc = env.json(CLAUDE);
    assert_eq!(varde_commands(&doc, "SessionStart").len(), 1);
    assert_eq!(varde_commands(&doc, "PostToolUse").len(), 1);
    assert!(varde_commands(&doc, "UserPromptSubmit").is_empty());
    assert!(commands(&doc, "UserPromptSubmit").contains(&"echo foreign-prompt".to_owned()));
}

#[test]
fn install_defaults_to_all_features_and_validates_custom_features() {
    let env = Env::new();
    let out = env.ok(&["install", "--harness", "claude"]);
    assert!(out.contains("installed UserPromptSubmit"), "{out}");

    let invalid = env.varde(&["install", "--harness", "claude", "--features", "nope"]);
    assert!(!invalid.status.success());
}

#[test]
fn feature_event_matrix_keeps_each_selected_event_only() {
    for (features, session, post, prompt) in [
        ("code", true, false, false),
        ("knowledge", false, true, false),
        ("change", false, true, true),
        ("learn", false, false, false),
    ] {
        let env = Env::new();
        env.ok(&["install", "--harness", "claude", "--features", features]);
        if !session && !post && !prompt {
            assert!(!env.path(CLAUDE).exists(), "{features}");
            continue;
        }
        let hooks = env.json(CLAUDE);
        assert_eq!(
            !varde_commands(&hooks, "SessionStart").is_empty(),
            session,
            "{features}"
        );
        assert_eq!(
            !varde_commands(&hooks, "PostToolUse").is_empty(),
            post,
            "{features}"
        );
        assert_eq!(
            !varde_commands(&hooks, "UserPromptSubmit").is_empty(),
            prompt,
            "{features}"
        );
    }
}

#[test]
fn sync_docs_does_not_wire_the_inbox_hook() {
    let env = Env::new();
    let skills = env.path("central/skills");
    let agents = env.path("central/agents");
    let output = env.sync(&[
        "--preset",
        "docs",
        "--harnesses",
        "claude",
        "--skills-dir",
        skills.to_str().unwrap(),
        "--agents-dir",
        agents.to_str().unwrap(),
    ]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    if env.path(CLAUDE).exists() {
        let hooks = env.json(CLAUDE);
        assert!(
            varde_commands(&hooks, "UserPromptSubmit").is_empty(),
            "{hooks}"
        );
    }
    let config = fs::read_to_string(env.path(".config/varde/config.toml")).unwrap();
    let config: toml::Value = toml::from_str(&config).unwrap();
    assert_eq!(
        config["hooks"]["user_prompt_submit"]["providers"]
            .as_array()
            .unwrap()
            .len(),
        0
    );
}

#[test]
fn help_lists_install_and_remove() {
    let env = Env::new();
    let output = Command::new(env!("CARGO_BIN_EXE_varde"))
        .args(["setup", "hooks", "--help"])
        .env("HOME", env.home.path())
        .output()
        .unwrap();
    let help = String::from_utf8_lossy(&output.stdout);
    assert!(output.status.success());
    for word in ["install", "remove"] {
        assert!(
            help.lines().any(|l| l.trim_start().starts_with(word)),
            "{word}: {help}"
        );
    }
    let output = env.varde(&["install", "--help"]);
    let help = String::from_utf8_lossy(&output.stdout);
    assert!(
        help.contains("Usage: varde setup hooks install") && help.contains("--force"),
        "{help}"
    );
}
