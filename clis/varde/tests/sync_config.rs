use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use tempfile::TempDir;
use varde::sync::harness::{HarnessId, detect};

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

    fn run(&self, args: &[&str], xdg: Option<&Path>, pi_dir: Option<&Path>) -> Output {
        let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
        command
            .args(args)
            .current_dir(&self.cwd)
            .env_clear()
            .env("HOME", &self.home)
            .env("VARDE_AGENTS_OPENCODE_VERSION", "1");
        if let Some(path) = std::env::var_os("PATH") {
            command.env("PATH", path);
        }
        if let Some(path) = xdg {
            command.env("XDG_CONFIG_HOME", path);
        }
        if let Some(path) = pi_dir {
            command.env("PI_CODING_AGENT_DIR", path);
        }
        command.output().unwrap()
    }

    fn config_path(&self) -> PathBuf {
        self.home.join(".config/varde/config.toml")
    }
}

fn stdout(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn tree(root: &Path) -> Vec<PathBuf> {
    fn visit(root: &Path, current: &Path, paths: &mut Vec<PathBuf>) {
        for entry in fs::read_dir(current).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            paths.push(path.strip_prefix(root).unwrap().to_path_buf());
            if entry.file_type().unwrap().is_dir() {
                visit(root, &path, paths);
            }
        }
    }

    let mut paths = Vec::new();
    visit(root, root, &mut paths);
    paths.sort();
    paths
}

fn target_args<'a>(skills: &'a str, agents: &'a str) -> [&'a str; 6] {
    [
        "setup",
        "sync",
        "--skills-dir",
        skills,
        "--agents-dir",
        agents,
    ]
}

#[test]
fn missing_targets_report_both_flags_and_leave_the_home_unchanged() {
    let sandbox = Sandbox::new();
    let before = tree(sandbox.root.path());

    let output = sandbox.run(&["setup", "sync"], None, None);

    assert_eq!(output.status.code(), Some(2), "{}", stderr(&output));
    let message = stderr(&output);
    assert!(message.contains("--skills-dir"), "{message}");
    assert!(message.contains("--agents-dir"), "{message}");
    assert!(message.contains("canonical central copy"), "{message}");
    assert_eq!(tree(sandbox.root.path()), before);
}

#[test]
fn one_saved_target_names_the_missing_flag_without_changing_config() {
    let sandbox = Sandbox::new();
    let config_path = sandbox.config_path();
    fs::create_dir_all(config_path.parent().unwrap()).unwrap();
    let original = "[sync]\nskills_dir = \"/saved/skills\"\n";
    fs::write(&config_path, original).unwrap();

    let output = sandbox.run(&["setup", "sync"], None, None);

    assert_eq!(output.status.code(), Some(2), "{}", stderr(&output));
    assert!(stderr(&output).contains("--agents-dir"));
    assert_eq!(fs::read_to_string(config_path).unwrap(), original);
}

#[test]
fn flags_are_saved_as_absolute_targets_and_reused_on_the_next_run() {
    let sandbox = Sandbox::new();
    let output = sandbox.run(
        &target_args("canonical/skills", "~/canonical-agents"),
        None,
        None,
    );

    assert!(output.status.success(), "{}", stderr(&output));
    let skills = fs::canonicalize(&sandbox.cwd)
        .unwrap()
        .join("canonical/skills");
    let agents = sandbox.home.join("canonical-agents");
    let saved = fs::read_to_string(sandbox.config_path()).unwrap();
    assert!(saved.contains(&format!("skills_dir = \"{}\"", skills.display())));
    assert!(saved.contains(&format!("agents_dir = \"{}\"", agents.display())));
    assert!(saved.contains("link_mode = \"symlink\""));

    let again = sandbox.run(&["setup", "sync"], None, None);
    assert!(again.status.success(), "{}", stderr(&again));
    assert!(stdout(&again).contains(&format!("skills target: {}", skills.display())));
    assert!(stdout(&again).contains(&format!("agents target: {}", agents.display())));
    assert_eq!(
        fs::read_to_string(skills.join("varde-change/.varde-managed-skill"))
            .unwrap()
            .trim(),
        "varde-managed-skill"
    );
    assert!(
        fs::read_to_string(agents.join("claude/varde-planner.md"))
            .unwrap()
            .contains("<!-- varde-managed-agent -->")
    );
}

#[test]
fn xdg_config_home_selects_the_saved_config_location() {
    let sandbox = Sandbox::new();
    let xdg = sandbox.root.path().join("xdg");
    let output = sandbox.run(&target_args("skills", "agents"), Some(&xdg), None);

    assert!(output.status.success(), "{}", stderr(&output));
    assert!(xdg.join("varde/config.toml").is_file());
    assert!(!sandbox.config_path().exists());
}

#[test]
fn saving_sync_settings_preserves_default_and_unrelated_config_tables() {
    let sandbox = Sandbox::new();
    let config_path = sandbox.config_path();
    fs::create_dir_all(config_path.parent().unwrap()).unwrap();
    fs::write(
        &config_path,
        "[default]\nworking = \"/work\"\n\n[hooks.session_start]\nproviders = [\"claude\"]\n\n[unrelated]\nkeep = \"yes\"\n\n[sync]\nskills_dir = \"/old/skills\"\nagents_dir = \"/old/agents\"\n",
    )
    .unwrap();

    let mut args = target_args("new-skills", "new-agents").to_vec();
    args.extend(["--link-mode", "copy"]);
    let output = sandbox.run(&args, None, None);

    assert!(output.status.success(), "{}", stderr(&output));
    let saved: toml::Value = toml::from_str(&fs::read_to_string(config_path).unwrap()).unwrap();
    assert_eq!(saved["default"]["working"].as_str(), Some("/work"));
    assert_eq!(
        saved["hooks"]["session_start"]["providers"][0].as_str(),
        Some("claude")
    );
    assert_eq!(saved["unrelated"]["keep"].as_str(), Some("yes"));
    assert_eq!(saved["sync"]["link_mode"].as_str(), Some("copy"));
}

#[test]
fn skill_selection_is_saved_and_all_clears_the_saved_selection() {
    let sandbox = Sandbox::new();
    let mut args = target_args("skills", "agents").to_vec();
    args.extend(["--skills", "varde-code"]);
    let output = sandbox.run(&args, None, None);

    assert!(output.status.success(), "{}", stderr(&output));
    let saved: toml::Value =
        toml::from_str(&fs::read_to_string(sandbox.config_path()).unwrap()).unwrap();
    assert_eq!(
        saved["sync"]["skills"].as_array().unwrap()[0].as_str(),
        Some("varde-code")
    );

    let mut clear_args = target_args("skills", "agents").to_vec();
    clear_args.extend(["--skills", "all"]);
    let cleared = sandbox.run(&clear_args, None, None);

    assert!(cleared.status.success(), "{}", stderr(&cleared));
    assert!(sandbox.cwd.join("skills/varde-change").is_dir());
    let saved: toml::Value =
        toml::from_str(&fs::read_to_string(sandbox.config_path()).unwrap()).unwrap();
    assert!(saved["sync"].get("skills").is_none());
}

#[test]
fn preset_selection_is_saved_as_expanded_skill_names() {
    let sandbox = Sandbox::new();
    let mut args = target_args("skills", "agents").to_vec();
    args.extend(["--preset", "learn"]);
    let output = sandbox.run(&args, None, None);

    assert!(output.status.success(), "{}", stderr(&output));
    let saved: toml::Value =
        toml::from_str(&fs::read_to_string(sandbox.config_path()).unwrap()).unwrap();
    let skills = saved["sync"]["skills"].as_array().unwrap();
    assert_eq!(skills.len(), 1);
    assert_eq!(skills[0].as_str(), Some("varde-learn"));
}

#[test]
fn the_full_preset_saves_no_selection_and_installs_every_skill() {
    let sandbox = Sandbox::new();
    let mut args = target_args("skills", "agents").to_vec();
    args.extend(["--preset", "full"]);
    let output = sandbox.run(&args, None, None);

    assert!(output.status.success(), "{}", stderr(&output));
    assert!(sandbox.cwd.join("skills/varde-change").is_dir());
    assert!(sandbox.cwd.join("skills/varde-customize").is_dir());
    let saved: toml::Value =
        toml::from_str(&fs::read_to_string(sandbox.config_path()).unwrap()).unwrap();
    assert!(saved["sync"].get("skills").is_none());
}

#[test]
fn link_mode_harness_selection_and_dry_run_are_supported() {
    let sandbox = Sandbox::new();
    let mut args = target_args("skills", "agents").to_vec();
    args.extend([
        "--link-mode",
        "copy",
        "--harnesses",
        "claude,codex",
        "--dry-run",
    ]);
    let output = sandbox.run(&args, None, None);

    assert!(output.status.success(), "{}", stderr(&output));
    let message = stdout(&output);
    assert!(message.contains("would use skills target:"), "{message}");
    assert!(message.contains("link mode: copy"), "{message}");
    assert!(message.contains("harnesses: claude, codex"), "{message}");
    assert!(!sandbox.config_path().exists());

    let mut none_args = target_args("skills", "agents").to_vec();
    none_args.extend(["--harnesses", "none", "--dry-run"]);
    let none = sandbox.run(&none_args, None, None);
    assert!(none.status.success(), "{}", stderr(&none));
    assert!(stdout(&none).contains("harnesses: none"));
}

#[test]
fn invalid_link_mode_and_harness_id_are_usage_errors() {
    let sandbox = Sandbox::new();
    let mut bad_mode = target_args("skills", "agents").to_vec();
    bad_mode.extend(["--link-mode", "hardlink"]);
    let output = sandbox.run(&bad_mode, None, None);
    assert_eq!(output.status.code(), Some(2));

    let mut bad_harness = target_args("skills", "agents").to_vec();
    bad_harness.extend(["--harnesses", "unknown"]);
    let output = sandbox.run(&bad_harness, None, None);
    assert_eq!(output.status.code(), Some(2));
    assert!(stderr(&output).contains("unknown"));
}

#[test]
fn an_existing_file_cannot_be_used_as_a_target() {
    let sandbox = Sandbox::new();
    let file = sandbox.cwd.join("not-a-directory");
    fs::write(&file, "file").unwrap();
    let output = sandbox.run(&target_args(file.to_str().unwrap(), "agents"), None, None);

    assert_eq!(output.status.code(), Some(2), "{}", stderr(&output));
    assert!(stderr(&output).contains("directory"));
    assert!(!sandbox.config_path().exists());
}

#[test]
fn detected_harnesses_include_their_layouts_and_pi_uses_its_override() {
    let sandbox = Sandbox::new();
    let home = sandbox.root.path().join("harness-home");
    fs::create_dir_all(home.join(".claude")).unwrap();
    fs::create_dir_all(home.join(".codex")).unwrap();
    fs::create_dir_all(home.join(".config/opencode")).unwrap();
    let pi_agent = sandbox.root.path().join("custom-pi-agent");

    let found = detect(&home, Some(&pi_agent));

    assert_eq!(
        found.iter().map(|harness| harness.id).collect::<Vec<_>>(),
        [
            HarnessId::Claude,
            HarnessId::Codex,
            HarnessId::OpenCode,
            HarnessId::Pi,
        ]
    );
    assert_eq!(
        found[0].skills_dir.as_deref(),
        Some(home.join(".claude/skills").as_path())
    );
    assert_eq!(found[2].agents_dir, home.join(".config/opencode/agents"));
    assert_eq!(found[3].skills_dir, None);
    assert_eq!(found[3].agents_dir, pi_agent.join("agents"));
}

#[test]
fn pi_directory_is_detected_from_home_and_uses_the_default_agent_root() {
    let sandbox = Sandbox::new();
    let home = sandbox.root.path().join("pi-home");
    fs::create_dir_all(home.join(".pi")).unwrap();

    let found = detect(&home, None);

    assert_eq!(found.len(), 1);
    assert_eq!(found[0].id, HarnessId::Pi);
    assert_eq!(found[0].agents_dir, home.join(".pi/agent/agents"));
}

#[test]
fn pi_environment_override_is_used_by_the_spawned_command() {
    let sandbox = Sandbox::new();
    fs::create_dir_all(sandbox.home.join(".claude")).unwrap();
    fs::create_dir_all(sandbox.home.join(".codex")).unwrap();
    fs::create_dir_all(sandbox.home.join(".config/opencode")).unwrap();
    let pi_agent = sandbox.root.path().join("custom-pi-agent");
    let mut args = target_args("skills", "agents").to_vec();
    args.push("--dry-run");

    let output = sandbox.run(&args, None, Some(&pi_agent));

    assert!(output.status.success(), "{}", stderr(&output));
    assert!(stdout(&output).contains("harnesses: claude, codex, opencode, pi"));
}

#[test]
fn sync_seeds_commented_hook_tables_and_later_writers_keep_them() {
    let sandbox = Sandbox::new();
    let output = sandbox.run(&target_args("skills", "agents"), None, None);
    assert!(output.status.success(), "{}", stderr(&output));

    let seeded = fs::read_to_string(sandbox.config_path()).unwrap();
    assert!(seeded.contains("[hooks.session_start]"), "{seeded}");
    assert!(seeded.contains("[hooks.post_tool_use]"), "{seeded}");
    assert!(seeded.contains("nav_map        - "), "{seeded}");
    assert!(seeded.contains("capture          - "), "{seeded}");
    assert!(seeded.contains("session_notes    - "), "{seeded}");
    assert!(
        seeded.contains("context_handoff  - deprecated alias"),
        "{seeded}"
    );
    assert!(
        seeded.contains("Defaults: providers = [\"capture\", \"session_notes\"]"),
        "{seeded}"
    );
    assert!(seeded.contains("notes_at_tokens = 250000"), "{seeded}");
    assert!(
        seeded.contains("handoff_at_tokens = 250000 # deprecated alias"),
        "{seeded}"
    );

    let set = sandbox.run(
        &[
            "setup",
            "paths",
            "set",
            "--default",
            "--learn",
            "learn-store",
        ],
        None,
        None,
    );
    assert!(set.status.success(), "{}", stderr(&set));
    let after = fs::read_to_string(sandbox.config_path()).unwrap();
    assert!(after.contains("learn-store"), "{after}");
    assert!(after.contains("[hooks.session_start]"), "{after}");
    assert!(
        after.contains("Defaults: providers = [\"nav_map\", \"toz_note\"]"),
        "{after}"
    );
    assert!(after.contains("[hooks.post_tool_use]"), "{after}");
}

#[test]
fn sync_reports_deprecated_session_notes_config_aliases() {
    let sandbox = Sandbox::new();
    fs::create_dir_all(sandbox.config_path().parent().unwrap()).unwrap();
    fs::write(
        sandbox.config_path(),
        "[hooks.post_tool_use]\nproviders = [\"context_handoff\"]\n[session]\nhandoff_at_tokens = 100\n",
    )
    .unwrap();

    let output = sandbox.run(&target_args("skills", "agents"), None, None);

    assert!(output.status.success(), "{}", stderr(&output));
    let message = stderr(&output);
    assert!(
        message.contains("context_handoff -> session_notes"),
        "{message}"
    );
    assert!(
        message.contains("[session].handoff_at_tokens -> [session].notes_at_tokens"),
        "{message}"
    );
    assert!(message.contains("new key wins"), "{message}");
    let config = fs::read_to_string(sandbox.config_path()).unwrap();
    assert!(
        config.contains("providers = [\"context_handoff\"]"),
        "{config}"
    );
    assert!(config.contains("handoff_at_tokens = 100"), "{config}");
}

#[test]
fn sync_never_rewrites_existing_hook_values() {
    let sandbox = Sandbox::new();
    fs::create_dir_all(sandbox.config_path().parent().unwrap()).unwrap();
    let original = "[hooks.session_start]\nproviders = [\"orchestration\"] # mine\n\n[hooks.user_prompt_submit]\nproviders = []\n";
    fs::write(sandbox.config_path(), original).unwrap();

    let output = sandbox.run(&target_args("skills", "agents"), None, None);
    assert!(output.status.success(), "{}", stderr(&output));

    let text = fs::read_to_string(sandbox.config_path()).unwrap();
    assert!(
        text.contains("providers = [\"orchestration\"] # mine"),
        "{text}"
    );
    assert!(text.contains("[hooks.post_tool_use]"), "{text}");
    let config: toml::Value = toml::from_str(&text).unwrap();
    assert_eq!(
        config["hooks"]["session_start"]["providers"][0].as_str(),
        Some("orchestration")
    );
    assert!(
        config["hooks"]["user_prompt_submit"]["providers"]
            .as_array()
            .unwrap()
            .is_empty()
    );
}

#[test]
fn toz_sync_backfills_only_missing_provider_lists_on_existing_hook_tables() {
    let sandbox = Sandbox::new();
    let config_path = sandbox.config_path();
    fs::create_dir_all(config_path.parent().unwrap()).unwrap();
    fs::write(
        &config_path,
        "[hooks.session_start]\ntimeout = 7\n\n[hooks.post_tool_use]\n\ntimeout = 9\n\n[hooks.user_prompt_submit]\ntimeout = 11\n\n[other]\nkeep = true\n",
    )
    .unwrap();

    let output = sandbox.run(
        &[
            "setup",
            "sync",
            "--skills-dir",
            "skills",
            "--agents-dir",
            "agents",
            "--preset",
            "toz",
        ],
        None,
        None,
    );
    assert!(output.status.success(), "{}", stderr(&output));
    let config: toml::Value = toml::from_str(&fs::read_to_string(config_path).unwrap()).unwrap();
    assert_eq!(
        config["hooks"]["session_start"]["providers"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        config["hooks"]["session_start"]["providers"][0].as_str(),
        Some("toz_note")
    );
    assert_eq!(
        config["hooks"]["session_start"]["timeout"].as_integer(),
        Some(7)
    );
    assert_eq!(
        config["hooks"]["post_tool_use"]["providers"][0].as_str(),
        Some("capture")
    );
    assert_eq!(
        config["hooks"]["post_tool_use"]["timeout"].as_integer(),
        Some(9)
    );
    assert!(
        config["hooks"]["user_prompt_submit"]["providers"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert_eq!(
        config["hooks"]["user_prompt_submit"]["timeout"].as_integer(),
        Some(11)
    );
    assert_eq!(config["other"]["keep"].as_bool(), Some(true));
}
