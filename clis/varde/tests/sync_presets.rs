use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use tempfile::TempDir;
use varde::sync::config::{preset_names, preset_skills};
use varde::sync::embedded::skills;

struct Sandbox {
    root: TempDir,
    home: PathBuf,
    cwd: PathBuf,
}

impl Sandbox {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let home = root.path().join("home");
        let cwd = root.path().join("work");
        fs::create_dir_all(&home).unwrap();
        fs::create_dir_all(&cwd).unwrap();
        Self { root, home, cwd }
    }

    fn skills_dir(&self) -> PathBuf {
        self.root.path().join("central/skills")
    }

    fn agents_dir(&self) -> PathBuf {
        self.root.path().join("central/agents")
    }

    fn config_path(&self) -> PathBuf {
        self.home.join(".config/varde/config.toml")
    }

    fn run(&self, options: &[&str]) -> Output {
        let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
        command
            .args([
                "setup",
                "sync",
                "--skills-dir",
                self.skills_dir().to_str().unwrap(),
                "--agents-dir",
                self.agents_dir().to_str().unwrap(),
            ])
            .args(options)
            .current_dir(&self.cwd)
            .env_clear()
            .env("HOME", &self.home)
            .env("VARDE_AGENTS_OPENCODE_VERSION", "1");
        if let Some(path) = std::env::var_os("PATH") {
            command.env("PATH", path);
        }
        command.output().unwrap()
    }
}

fn stdout(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn installed(skills_dir: &Path, name: &str) -> bool {
    skills_dir.join(name).is_dir()
}

#[test]
fn every_preset_names_shipped_skills() {
    let names = preset_names().unwrap();
    for expected in [
        "learn",
        "scan",
        "workflow",
        "full",
        "toz",
        "docs",
        "knowledge",
    ] {
        assert!(names.contains(&expected.to_string()), "missing {expected}");
    }
    let mut sorted = names.clone();
    sorted.sort();
    assert_eq!(names, sorted, "preset names are sorted");

    let shipped = skills().iter().map(|skill| skill.name).collect::<Vec<_>>();
    for name in &names {
        let preset = preset_skills(name).unwrap();
        // `full` names no skills: an empty selection installs every skill.
        if name == "full" {
            assert!(preset.is_empty(), "the full preset names no skills");
            continue;
        }
        assert!(!preset.is_empty(), "preset {name} is empty");
        for skill in &preset {
            assert!(
                shipped.contains(&skill.as_str()),
                "preset {name} names unknown skill {skill}"
            );
            assert_ne!(
                skill, "varde-manage",
                "preset {name} names the implicit skill"
            );
        }
    }
}

#[test]
fn the_full_preset_is_the_all_selection() {
    assert!(preset_skills("full").unwrap().is_empty());
}

#[test]
fn unknown_preset_is_a_usage_error_listing_valid_names() {
    let sandbox = Sandbox::new();

    let output = sandbox.run(&["--preset", "unknown"]);

    assert_eq!(output.status.code(), Some(2), "{}", stderr(&output));
    let message = stderr(&output);
    assert!(message.contains("unknown preset"), "{message}");
    for name in preset_names().unwrap() {
        assert!(message.contains(&name), "{message}");
    }
    assert!(!sandbox.skills_dir().exists());
}

#[test]
fn a_preset_installs_its_skills_and_the_implicit_skill() {
    let sandbox = Sandbox::new();

    let output = sandbox.run(&["--harnesses", "claude", "--preset", "learn"]);

    assert!(output.status.success(), "{}", stderr(&output));
    for name in ["varde-learn", "varde-manage"] {
        assert!(installed(&sandbox.skills_dir(), name), "missing {name}");
        assert!(
            sandbox.home.join(".claude/skills").join(name).exists(),
            "missing harness link for {name}"
        );
    }
    assert!(!installed(&sandbox.skills_dir(), "varde-change"));
}

#[test]
fn selected_features_filter_opencode_and_pi_plugin_files() {
    for (selection, session, shell, post, inbox) in [
        (&["--preset", "docs"][..], false, false, false, false),
        (&["--preset", "toz"][..], true, true, true, false),
        (&["--skills", "varde-change"][..], false, false, true, true),
    ] {
        let sandbox = Sandbox::new();
        let mut options = vec!["--harnesses", "opencode,pi"];
        options.extend_from_slice(selection);
        let output = sandbox.run(&options);
        assert!(output.status.success(), "{}", stderr(&output));

        let opencode =
            fs::read_to_string(sandbox.home.join(".config/opencode/plugin/varde.ts")).unwrap();
        let pi = fs::read_to_string(sandbox.home.join(".pi/agent/extensions/varde.ts")).unwrap();
        let has_opencode_session = opencode
            .contains("\"experimental.chat.system.transform\": async")
            || opencode.contains("ctx.session.hook(\"context\"");
        let has_opencode_post = opencode.contains("\"tool.execute.after\": async")
            || opencode.contains("ctx.tool.hook(\"execute.after\"");
        let has_opencode_shell = opencode.contains("\"shell.env\": async")
            || opencode.contains("ctx.shell.hook(\"create.before\"");
        assert_eq!(has_opencode_session, session, "{selection:?}");
        assert_eq!(has_opencode_post, post, "{selection:?}");
        assert_eq!(has_opencode_shell, shell, "{selection:?}");
        assert_eq!(
            pi.contains("pi.on(\"before_agent_start\""),
            session || inbox,
            "{selection:?}"
        );
        assert_eq!(pi.contains("pi.on(\"tool_result\""), post, "{selection:?}");
        assert_eq!(
            pi.contains("promptInbox(process.cwd(), sessionId)"),
            inbox,
            "{selection:?}"
        );
    }
}

#[test]
fn a_preset_combines_with_skills() {
    let sandbox = Sandbox::new();

    let output = sandbox.run(&[
        "--harnesses",
        "claude",
        "--preset",
        "scan",
        "--skills",
        "varde-change",
    ]);

    assert!(output.status.success(), "{}", stderr(&output));
    for name in ["varde-change", "varde-code", "varde-scan", "varde-manage"] {
        assert!(installed(&sandbox.skills_dir(), name), "missing {name}");
    }
    assert!(!installed(&sandbox.skills_dir(), "varde-learn"));
}

#[test]
fn the_full_preset_installs_every_skill() {
    let sandbox = Sandbox::new();

    let output = sandbox.run(&["--harnesses", "none", "--preset", "full"]);

    assert!(output.status.success(), "{}", stderr(&output));
    for skill in skills() {
        assert!(
            installed(&sandbox.skills_dir(), skill.name),
            "missing {}",
            skill.name
        );
    }
}

#[test]
fn the_sync_help_lists_the_preset_flag_and_names() {
    let sandbox = Sandbox::new();

    let output = sandbox.run(&["--help"]);

    assert!(output.status.success(), "{}", stderr(&output));
    let help = stdout(&output);
    assert!(help.contains("--preset"), "{help}");
    for name in preset_names().unwrap() {
        assert!(
            help.contains(&name),
            "help does not name preset {name}: {help}"
        );
    }
}

#[test]
fn a_preset_after_a_skills_selection_replaces_the_saved_selection() {
    let sandbox = Sandbox::new();

    let first = sandbox.run(&["--harnesses", "none", "--skills", "varde-learn"]);
    assert!(first.status.success(), "{}", stderr(&first));
    assert!(installed(&sandbox.skills_dir(), "varde-learn"));

    let second = sandbox.run(&["--harnesses", "none", "--preset", "scan"]);
    assert!(second.status.success(), "{}", stderr(&second));
    // The replaced selection installs the scan skills; `varde-learn` stays on
    // disk because sync removes nothing.
    for name in [
        "varde-learn",
        "varde-code",
        "varde-scan",
        "varde-customize",
        "varde-manage",
    ] {
        assert!(installed(&sandbox.skills_dir(), name), "missing {name}");
    }
    let saved: toml::Value =
        toml::from_str(&fs::read_to_string(sandbox.config_path()).unwrap()).unwrap();
    let names = saved["sync"]["skills"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_str().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(names, ["varde-code", "varde-scan", "varde-customize"]);
}
