use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::env;
use std::ffi::OsString;
use std::fs;
use std::ops::{Deref, DerefMut};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use tempfile::TempDir;
use varde::migrate::harness;
use varde::migrate::{MigrateEnv, Report};

fn test_guard() -> std::sync::MutexGuard<'static, ()> {
    crate::process_env_guard()
}

struct ProcessEnv(Vec<(&'static str, Option<OsString>)>);

impl ProcessEnv {
    fn set(values: Vec<(&'static str, Option<OsString>)>) -> Self {
        let previous = values
            .iter()
            .map(|(name, _)| (*name, env::var_os(name)))
            .collect();
        for (name, value) in values {
            unsafe {
                match value {
                    Some(value) => env::set_var(name, value),
                    None => env::remove_var(name),
                }
            }
        }
        Self(previous)
    }
}

impl Drop for ProcessEnv {
    fn drop(&mut self) {
        for (name, value) in self.0.drain(..) {
            unsafe {
                match value {
                    Some(value) => env::set_var(name, value),
                    None => env::remove_var(name),
                }
            }
        }
    }
}

struct TestEnv {
    // Restore process variables before the TempDir removes their target paths.
    _process_env: ProcessEnv,
    env: MigrateEnv,
    _root: TempDir,
}

impl Deref for TestEnv {
    type Target = MigrateEnv;

    fn deref(&self) -> &Self::Target {
        &self.env
    }
}

impl DerefMut for TestEnv {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.env
    }
}

fn fixture_env() -> TestEnv {
    let root = tempfile::tempdir().expect("temporary test root");
    let home = root.path().join("home");
    let xdg_config_home = root.path().join("xdg-config");
    let config_dir = root.path().join("varde-config");
    let cargo_install_root = root.path().join("cargo");
    let pi_agent = root.path().join("pi-agent");
    for dir in [
        &home,
        &xdg_config_home,
        &config_dir,
        &cargo_install_root,
        &pi_agent,
    ] {
        fs::create_dir_all(dir).expect("create isolated test root");
    }
    let process_env = ProcessEnv::set(vec![
        ("HOME", Some(home.as_os_str().to_owned())),
        (
            "CODEX_HOME",
            Some(home.join(".codex").as_os_str().to_owned()),
        ),
        ("PI_CODING_AGENT_DIR", Some(pi_agent.as_os_str().to_owned())),
        (
            "XDG_CONFIG_HOME",
            Some(xdg_config_home.as_os_str().to_owned()),
        ),
        ("VARDE_CONFIG_DIR", Some(config_dir.as_os_str().to_owned())),
        (
            "CARGO_INSTALL_ROOT",
            Some(cargo_install_root.as_os_str().to_owned()),
        ),
        ("VARDE_TOZ_CONFIG_DIR", None),
        ("TOZ_CONFIG_DIR", None),
    ]);
    let mut env = MigrateEnv {
        home,
        config_dir,
        xdg_config_home: Some(xdg_config_home),
        path: env::var_os("PATH").unwrap_or_default(),
        cargo_install_root,
        exe: PathBuf::from(env!("CARGO_BIN_EXE_varde")),
        toz_config_override: None,
        dry_run: false,
    };

    let fake_bin = env.config_dir.join("fake-harness-bin");
    fs::create_dir_all(&fake_bin).expect("fake harness bin directory");
    for (name, version) in [
        ("claude", "2.1.236"),
        ("codex", "0.140.0"),
        ("opencode", "2.0.0"),
        ("pi", "0.84.0"),
    ] {
        let path = fake_bin.join(name);
        fs::write(&path, format!("#!/bin/sh\nprintf '%s\\n' '{version}'\n"))
            .expect("write fake version command");
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755))
            .expect("make fake version command executable");
    }
    let mut paths = vec![fake_bin];
    paths.extend(env::split_paths(&env.path));
    env.path = env::join_paths(paths).expect("join test PATH");
    TestEnv {
        _process_env: process_env,
        env,
        _root: root,
    }
}

fn pi_agent_dir(env: &MigrateEnv) -> PathBuf {
    env::var_os("PI_CODING_AGENT_DIR")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| env.home.join(".pi/agent"))
}

fn cli_output(env: &MigrateEnv, args: &[&str]) -> Output {
    let mut command = Command::new(&env.exe);
    command
        .args(args)
        .env("HOME", &env.home)
        .env("CODEX_HOME", env.home.join(".codex"))
        .env("PI_CODING_AGENT_DIR", pi_agent_dir(env))
        .env("VARDE_CONFIG_DIR", &env.config_dir)
        .env("CARGO_INSTALL_ROOT", &env.cargo_install_root)
        .env("PATH", &env.path)
        .stdin(Stdio::null());
    match &env.xdg_config_home {
        Some(path) => {
            command.env("XDG_CONFIG_HOME", path);
        }
        None => {
            command.env_remove("XDG_CONFIG_HOME");
        }
    }
    command.env_remove("VARDE_TOZ_CONFIG_DIR");
    command.env_remove("TOZ_CONFIG_DIR");
    if let Some(path) = &env.toz_config_override {
        command.env("VARDE_TOZ_CONFIG_DIR", path);
    }
    command.output().expect("run isolated varde command")
}

fn write_old_toz_manifest(dir: &Path, files: &[(&str, &str)]) {
    let hashes = files
        .iter()
        .map(|(relative, contents)| {
            (
                (*relative).to_owned(),
                toz_core::content_hash(contents.as_bytes()),
            )
        })
        .collect::<BTreeMap<_, _>>();
    let manifest = json!({"version": 1, "files": hashes});
    fs::write(
        dir.join(".varde-toz-install.json"),
        serde_json::to_vec_pretty(&manifest).expect("serialize old Toz manifest"),
    )
    .expect("write old Toz manifest");
}

fn seed_legacy_toz_files(env: &MigrateEnv) {
    let claude = env.home.join(".claude/skills/toz");
    let claude_plugin = r#"{"name":"toz"}"#;
    let claude_hooks = r#"{"hooks":{"PostToolUse":[{"hooks":[{"type":"command","command":"varde-toz capture --hook"}]}]}}"#;
    fs::create_dir_all(claude.join(".claude-plugin")).expect("old Claude plugin dir");
    fs::create_dir_all(claude.join("hooks")).expect("old Claude hooks dir");
    fs::write(claude.join(".claude-plugin/plugin.json"), claude_plugin).expect("old Claude plugin");
    fs::write(claude.join("hooks/hooks.json"), claude_hooks).expect("old Claude hooks");
    write_old_toz_manifest(
        &claude,
        &[
            (".claude-plugin/plugin.json", claude_plugin),
            ("hooks/hooks.json", claude_hooks),
        ],
    );

    let opencode = env
        .xdg_config_home
        .as_ref()
        .expect("temporary XDG config root")
        .join("opencode");
    let opencode_old = "// legacy command: varde-toz capture --hook --harness opencode\n";
    fs::create_dir_all(opencode.join("plugin")).expect("old OpenCode plugin dir");
    fs::write(opencode.join("plugin/toz.ts"), opencode_old).expect("old OpenCode adapter");
    write_old_toz_manifest(&opencode, &[("plugin/toz.ts", opencode_old)]);

    let pi = pi_agent_dir(env);
    let pi_old = "// legacy command: toz capture --hook --harness pi\n";
    fs::create_dir_all(pi.join("extensions")).expect("old Pi extension dir");
    fs::write(pi.join("extensions/toz.ts"), pi_old).expect("old Pi adapter");
    write_old_toz_manifest(&pi, &[("extensions/toz.ts", pi_old)]);
}

fn seed_claude_hooks(command: &str) -> String {
    let code_command = serde_json::to_string(command).expect("serialize legacy code command");
    let workflow_command =
        serde_json::to_string("varde-workflow hook session-start --harness claude")
            .expect("serialize legacy workflow command");
    format!(
        r#"{{"before":{{"keep":"byte-identical"}},"hooks":{{"SessionStart":[{{"matcher":"","hooks":[{{"type":"command","command":{code_command},"__source":"varde-code"}}]}},{{"matcher":"","hooks":[{{"type":"command","command":{workflow_command}}}]}},{{"matcher":"","hooks":[{{"type":"command","command":"echo foreign-session"}}]}}]}},"after":7}}"#
    )
}

fn seed_codex_hooks() -> &'static str {
    r#"{"before":{"keep":"byte-identical"},"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"varde-workflow hook session-start --harness codex"}]},{"hooks":[{"type":"command","command":"echo foreign-session"}]}],"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"toz capture --hook --harness codex","timeout":30},{"type":"command","command":"echo foreign-post"}]}]},"after":7}"#
}

fn seed_legacy_code_hooks(env: &MigrateEnv) {
    let claude = env.home.join(".claude/settings.json");
    fs::create_dir_all(claude.parent().unwrap()).expect("Claude settings dir");
    fs::write(
        &claude,
        seed_claude_hooks(varde_code::hooks::LEGACY_SESSION_START_COMMAND),
    )
    .expect("legacy Claude settings");

    let codex = env.home.join(".codex");
    fs::create_dir_all(&codex).expect("Codex dir");
    fs::write(
        codex.join("config.toml"),
        format!(
            "[unrelated]\nkeep = \"byte-identical\"\n\n[hooks.session_start]\ncommand = {:?}\n__source = \"varde-code\"\n",
            varde_code::hooks::LEGACY_SESSION_START_COMMAND
        ),
    )
    .expect("legacy Codex config");
    fs::write(codex.join("hooks.json"), seed_codex_hooks()).expect("legacy Codex hooks");

    let opencode = env.home.join(".config/opencode/plugin");
    fs::create_dir_all(&opencode).expect("code OpenCode plugin dir");
    let legacy_opencode = varde_code::hooks::LEGACY_OPENCODE_PLUGIN_V1_4;
    fs::write(opencode.join("varde-code-nav-map.js"), legacy_opencode)
        .expect("legacy OpenCode code plugin");

    let pi_extensions = pi_agent_dir(env).join("extensions");
    fs::create_dir_all(&pi_extensions).expect("Pi extension dir");
    let legacy_pi = varde_code::hooks::LEGACY_PI_EXTENSION_V1_4;
    fs::write(pi_extensions.join("pi-extension.js"), legacy_pi).expect("legacy Pi code extension");

    let xdg_opencode = env
        .xdg_config_home
        .as_ref()
        .expect("temporary XDG config root")
        .join("opencode/plugin");
    fs::create_dir_all(&xdg_opencode).expect("session OpenCode plugin dir");
    fs::write(
        xdg_opencode.join("foreign.ts"),
        "// foreign OpenCode plugin\n",
    )
    .expect("foreign OpenCode plugin");
    fs::write(
        xdg_opencode.join("varde-session.ts"),
        legacy_session_plugin("opencode", "/old/bin/varde-workflow"),
    )
    .expect("legacy OpenCode session plugin");
    fs::write(
        pi_extensions.join("varde-session.ts"),
        legacy_session_plugin("pi", "/old/bin/varde-workflow"),
    )
    .expect("legacy Pi session extension");
    fs::write(
        pi_extensions.join("foreign.ts"),
        "// foreign Pi extension\n",
    )
    .expect("foreign Pi extension");
}

fn legacy_session_plugin(harness: &str, bin: &str) -> String {
    let asset = if harness == "pi" {
        include_str!("../src/migrate/legacy/pi-varde-session.ts").to_owned()
    } else {
        let all = include_str!("../src/migrate/legacy/opencode-varde-session.ts");
        let (header, rest) = all.split_once("//@@v1\n").unwrap();
        let (_, v2) = rest.split_once("//@@v2\n").unwrap();
        format!("{header}{v2}")
    };
    asset.replace(
        "\"{{VARDE_WORKFLOW_BIN}}\"",
        &serde_json::to_string(bin).unwrap(),
    )
}

fn commands_in(value: &Value, out: &mut Vec<String>) {
    match value {
        Value::Object(object) => {
            if let Some(Value::String(command)) = object.get("command") {
                out.push(command.clone());
            }
            for child in object.values() {
                commands_in(child, out);
            }
        }
        Value::Array(array) => {
            for child in array {
                commands_in(child, out);
            }
        }
        _ => {}
    }
}

fn count_containing(commands: &[String], needle: &str) -> usize {
    commands
        .iter()
        .filter(|command| command.contains(needle))
        .count()
}

fn assert_varde_command(command: &str) {
    let executable = command
        .split_whitespace()
        .next()
        .expect("hook command has an executable");
    assert_eq!(
        Path::new(executable)
            .file_name()
            .and_then(|name| name.to_str()),
        Some("varde"),
        "hook command must run through varde: {command}"
    );
}

fn snapshot(roots: &[PathBuf]) -> BTreeMap<PathBuf, Vec<u8>> {
    fn visit(path: &Path, files: &mut BTreeMap<PathBuf, Vec<u8>>) {
        let metadata = fs::symlink_metadata(path).expect("inspect snapshot path");
        if metadata.is_dir() {
            files.insert(path.to_path_buf(), b"<directory>".to_vec());
            let mut children = fs::read_dir(path)
                .expect("read snapshot directory")
                .map(|entry| entry.expect("read snapshot entry").path())
                .collect::<Vec<_>>();
            children.sort();
            for child in children {
                visit(&child, files);
            }
        } else if metadata.file_type().is_symlink() {
            files.insert(
                path.to_path_buf(),
                fs::read_link(path)
                    .expect("read snapshot symlink")
                    .into_os_string()
                    .into_encoded_bytes(),
            );
        } else {
            files.insert(
                path.to_path_buf(),
                fs::read(path).expect("read snapshot file"),
            );
        }
    }

    let mut files = BTreeMap::new();
    for root in roots {
        if root.exists() {
            visit(root, &mut files);
        }
    }
    files
}

fn all_test_roots(env: &MigrateEnv) -> Vec<PathBuf> {
    let mut roots = vec![
        env.home.clone(),
        env.config_dir.clone(),
        env.xdg_config_home.clone().expect("temporary XDG root"),
        env.home.join(".codex"),
        pi_agent_dir(env),
    ];
    roots.sort();
    roots.dedup();
    roots
}

#[test]
fn rewrites_legacy_entries_for_each_harness_and_is_idempotent() {
    let _guard = test_guard();
    let env = fixture_env();
    seed_legacy_toz_files(&env);
    seed_legacy_code_hooks(&env);

    let mut report = Report::default();
    for harness in ["claude", "codex", "opencode", "pi"] {
        harness::rewrite_harness(&env, harness, &mut report);
    }
    assert!(report.unrewritable.is_empty(), "{:#?}", report.unrewritable);

    assert!(!env.home.join(".claude/skills/toz").exists());
    assert!(!env.home.join(".claude/skills/varde-toz-hooks").exists());

    let claude_settings_path = env.home.join(".claude/settings.json");
    let claude_settings = fs::read_to_string(&claude_settings_path).expect("Claude settings");
    assert!(claude_settings.contains(r#""keep":"byte-identical""#));
    assert!(claude_settings.find("\"before\"") < claude_settings.find("\"hooks\""));
    assert!(claude_settings.find("\"hooks\"") < claude_settings.find("\"after\""));
    assert!(!claude_settings.contains("varde-code nav_map"));
    assert!(!claude_settings.contains("varde-workflow hook session-start"));
    let claude_doc: Value = serde_json::from_str(&claude_settings).expect("valid Claude settings");
    let mut claude_commands = Vec::new();
    commands_in(&claude_doc["hooks"]["SessionStart"], &mut claude_commands);
    assert_eq!(
        count_containing(&claude_commands, "hook session-start"),
        1,
        "{claude_commands:?}"
    );
    let claude_session = claude_commands
        .iter()
        .find(|command| command.contains("hook session-start --harness claude"))
        .expect("Claude session hook");
    assert_varde_command(claude_session);
    let mut claude_post = Vec::new();
    commands_in(&claude_doc["hooks"]["PostToolUse"], &mut claude_post);
    assert_eq!(claude_post.len(), 1, "{claude_post:?}");
    assert!(claude_post[0].contains("hook post-tool-use --harness claude"));
    let mut claude_prompt = Vec::new();
    commands_in(&claude_doc["hooks"]["UserPromptSubmit"], &mut claude_prompt);
    assert_eq!(
        count_containing(&claude_prompt, "hook user-prompt-submit --harness claude"),
        1,
        "{claude_prompt:?}"
    );
    assert!(
        claude_commands
            .iter()
            .any(|command| command == "echo foreign-session")
    );

    let codex_hooks_path = env.home.join(".codex/hooks.json");
    let codex_hooks = fs::read_to_string(&codex_hooks_path).expect("Codex hooks");
    assert!(codex_hooks.contains(r#""keep":"byte-identical""#));
    assert!(codex_hooks.find("\"before\"") < codex_hooks.find("\"hooks\""));
    assert!(codex_hooks.find("\"hooks\"") < codex_hooks.find("\"after\""));
    assert!(!codex_hooks.contains("toz capture --hook"));
    assert!(!codex_hooks.contains("varde-workflow hook session-start"));
    let codex_doc: Value = serde_json::from_str(&codex_hooks).expect("valid Codex hooks");
    let mut codex_commands = Vec::new();
    commands_in(&codex_doc["hooks"], &mut codex_commands);
    assert_eq!(
        count_containing(&codex_commands, "hook session-start"),
        1,
        "{codex_commands:?}"
    );
    assert_eq!(
        count_containing(&codex_commands, "hook post-tool-use"),
        1,
        "{codex_commands:?}"
    );
    assert_eq!(
        count_containing(&codex_commands, "hook user-prompt-submit"),
        1,
        "{codex_commands:?}"
    );
    for command in codex_commands
        .iter()
        .filter(|command| command.contains(" hook "))
    {
        assert_varde_command(command);
    }
    assert!(
        codex_commands
            .iter()
            .any(|command| command == "echo foreign-session")
    );
    assert!(
        codex_commands
            .iter()
            .any(|command| command == "echo foreign-post")
    );
    let codex_toml = fs::read_to_string(env.home.join(".codex/config.toml")).expect("Codex config");
    assert!(codex_toml.contains("[unrelated]\nkeep = \"byte-identical\""));
    assert!(!codex_toml.contains("varde-code nav_map"));

    let xdg_opencode = env
        .xdg_config_home
        .as_ref()
        .unwrap()
        .join("opencode/plugin");
    assert!(!xdg_opencode.join("toz.ts").exists());
    for retired in ["varde-toz.ts", "varde-session.ts"] {
        assert!(!xdg_opencode.join(retired).exists(), "{retired}");
    }
    let opencode_plugin =
        fs::read_to_string(xdg_opencode.join("varde.ts")).expect("OpenCode unified plugin");
    assert!(opencode_plugin.contains(&env.exe.display().to_string()));
    assert_eq!(
        fs::read_to_string(xdg_opencode.join("foreign.ts")).unwrap(),
        "// foreign OpenCode plugin\n"
    );
    assert!(
        !env.home
            .join(".config/opencode/plugin/varde-code-nav-map.js")
            .exists()
    );

    let pi_extensions = pi_agent_dir(&env).join("extensions");
    assert!(!pi_extensions.join("toz.ts").exists());
    for retired in ["varde-toz.ts", "varde-session.ts"] {
        assert!(!pi_extensions.join(retired).exists(), "{retired}");
    }
    let pi_plugin =
        fs::read_to_string(pi_extensions.join("varde.ts")).expect("Pi unified extension");
    assert!(pi_plugin.contains(&env.exe.display().to_string()));
    assert!(!pi_extensions.join("pi-extension.js").exists());
    assert_eq!(
        fs::read_to_string(pi_extensions.join("foreign.ts")).unwrap(),
        "// foreign Pi extension\n"
    );

    let before_second_run = snapshot(&all_test_roots(&env));
    let mut second_report = Report::default();
    for harness in ["claude", "codex", "opencode", "pi"] {
        harness::rewrite_harness(&env, harness, &mut second_report);
    }
    assert!(
        second_report.unrewritable.is_empty(),
        "{:#?}",
        second_report.unrewritable
    );
    assert_eq!(snapshot(&all_test_roots(&env)), before_second_run);
}

#[test]
fn locally_modified_legacy_entry_is_kept_with_a_recovery_hint() {
    let _guard = test_guard();
    let env = fixture_env();
    let modified_command = format!(
        "{} --local-change",
        varde_code::hooks::LEGACY_SESSION_START_COMMAND
    );
    let settings = env.home.join(".claude/settings.json");
    fs::create_dir_all(settings.parent().unwrap()).expect("Claude settings dir");
    fs::write(&settings, seed_claude_hooks(&modified_command)).expect("modified legacy hook");

    let mut report = Report::default();
    harness::rewrite_harness(&env, "claude", &mut report);

    let skipped = report
        .unrewritable
        .iter()
        .find(|entry| entry.path.ends_with(".claude/settings.json"))
        .expect("modified legacy hook is reported");
    assert!(skipped.reason.contains("modified"));
    assert!(skipped.reason.contains("rerun `varde setup sync`"));
    assert_eq!(skipped.command, None);
    assert!(
        fs::read_to_string(settings)
            .unwrap()
            .contains("--local-change")
    );
}

#[test]
fn edited_legacy_session_entries_are_kept_reported_and_not_duplicated() {
    let _guard = test_guard();
    let env = fixture_env();
    let claude = env.home.join(".claude/settings.json");
    let codex = env.home.join(".codex/hooks.json");
    fs::create_dir_all(claude.parent().unwrap()).unwrap();
    fs::create_dir_all(codex.parent().unwrap()).unwrap();
    // Wrong timeout (claude) and an extra argument (codex) mean the user edited them.
    let claude_seed = r#"{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"varde-workflow hook session-start --harness claude","timeout":99}]},{"hooks":[{"type":"command","command":"echo foreign-session"}]}]}}"#;
    let codex_seed = r#"{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"varde-workflow hook session-start --harness codex --debug","timeout":20}]}]}}"#;
    fs::write(&claude, claude_seed).unwrap();
    fs::write(&codex, codex_seed).unwrap();

    let mut report = Report::default();
    harness::rewrite_harness(&env, "claude", &mut report);
    harness::rewrite_harness(&env, "codex", &mut report);

    for (path, harness, seed) in [
        (&claude, "claude", claude_seed),
        (&codex, "codex", codex_seed),
    ] {
        let blocked = report
            .unrewritable
            .iter()
            .find(|entry| &entry.path == path && entry.reason.contains("SessionStart"))
            .unwrap_or_else(|| panic!("{harness} edited entry reported: {report:#?}"));
        assert_eq!(
            blocked.command.as_deref(),
            Some(format!("varde setup hooks install --harness {harness} --force").as_str())
        );
        let text = fs::read_to_string(path).unwrap();
        assert!(
            text.contains(
                seed.split("\"command\":\"")
                    .nth(1)
                    .unwrap()
                    .split('"')
                    .next()
                    .unwrap()
            )
        );
        let doc: Value = serde_json::from_str(&text).unwrap();
        let mut session = Vec::new();
        commands_in(&doc["hooks"]["SessionStart"], &mut session);
        assert_eq!(
            count_containing(&session, "hook session-start"),
            1,
            "{session:?}"
        );
        // The other event is not held back.
        let mut post = Vec::new();
        commands_in(&doc["hooks"]["PostToolUse"], &mut post);
        assert_eq!(post.len(), 1, "{post:?}");
    }
    assert!(
        fs::read_to_string(&claude)
            .unwrap()
            .contains("echo foreign-session")
    );
}

fn session_and_post_commands(path: &Path) -> (Vec<String>, Vec<String>) {
    let doc: Value = serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
    let mut session = Vec::new();
    commands_in(&doc["hooks"]["SessionStart"], &mut session);
    let mut post = Vec::new();
    commands_in(&doc["hooks"]["PostToolUse"], &mut post);
    (session, post)
}

#[test]
fn a_retained_edited_code_hook_holds_back_only_the_unified_session_start() {
    let _guard = test_guard();
    let env = fixture_env();
    let modified = format!(
        "{} --local-change",
        varde_code::hooks::LEGACY_SESSION_START_COMMAND
    );
    let settings = env.home.join(".claude/settings.json");
    fs::create_dir_all(settings.parent().unwrap()).unwrap();
    fs::write(&settings, seed_claude_hooks(&modified)).unwrap();
    let codex = env.home.join(".codex");
    fs::create_dir_all(&codex).unwrap();
    fs::write(
        codex.join("config.toml"),
        format!("[hooks.session_start]\ncommand = {modified:?}\n__source = \"varde-code\"\n"),
    )
    .unwrap();

    let mut report = Report::default();
    harness::rewrite_harness(&env, "claude", &mut report);
    harness::rewrite_harness(&env, "codex", &mut report);

    for (path, name) in [(&settings, "claude"), (&codex.join("hooks.json"), "codex")] {
        let (session, post) = session_and_post_commands(path);
        assert_eq!(
            count_containing(&session, "hook session-start"),
            0,
            "{name}: {session:?}"
        );
        assert_eq!(count_containing(&post, "hook post-tool-use"), 1, "{name}");
    }
    for config in [&settings, &codex.join("config.toml")] {
        let entry = report
            .unrewritable
            .iter()
            .find(|entry| &entry.path == config)
            .unwrap_or_else(|| panic!("{} reported: {report:#?}", config.display()));
        assert!(entry.reason.contains("SessionStart"), "{}", entry.reason);
    }
}

#[test]
fn a_legacy_workflow_group_with_an_extra_key_is_kept_and_reported() {
    let _guard = test_guard();
    let env = fixture_env();
    let claude = env.home.join(".claude/settings.json");
    fs::create_dir_all(claude.parent().unwrap()).unwrap();
    let seed = r#"{"hooks":{"SessionStart":[{"disabled":true,"hooks":[{"type":"command","command":"varde-workflow hook session-start --harness claude","timeout":20}]}]}}"#;
    fs::write(&claude, seed).unwrap();

    let mut report = Report::default();
    harness::rewrite_harness(&env, "claude", &mut report);

    let text = fs::read_to_string(&claude).unwrap();
    assert!(text.contains("\"disabled\":true"), "{text}");
    let (session, post) = session_and_post_commands(&claude);
    assert_eq!(
        count_containing(&session, "hook session-start"),
        1,
        "{session:?}"
    );
    assert_eq!(count_containing(&post, "hook post-tool-use"), 1);
    assert!(
        report
            .unrewritable
            .iter()
            .any(|entry| entry.path == claude && entry.reason.contains("SessionStart")),
        "{report:#?}"
    );
}

#[test]
fn an_edited_codex_toz_capture_entry_is_kept_and_reported() {
    let _guard = test_guard();
    let env = fixture_env();
    let hooks = env.home.join(".codex/hooks.json");
    fs::create_dir_all(hooks.parent().unwrap()).unwrap();
    let seed = r#"{"hooks":{"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"toz capture --hook --harness codex","timeout":99}]}]}}"#;
    fs::write(&hooks, seed).unwrap();

    let mut report = Report::default();
    harness::rewrite_harness(&env, "codex", &mut report);

    assert_eq!(fs::read_to_string(&hooks).unwrap(), seed);
    let entry = report
        .unrewritable
        .iter()
        .find(|entry| entry.path == hooks)
        .unwrap_or_else(|| panic!("edited entry reported: {report:#?}"));
    assert!(entry.reason.contains("edited"), "{}", entry.reason);
}

#[test]
fn edited_legacy_session_plugin_is_kept_and_blocks_the_unified_plugin() {
    let _guard = test_guard();
    let env = fixture_env();
    let plugin_dir = env
        .xdg_config_home
        .as_ref()
        .unwrap()
        .join("opencode/plugin");
    fs::create_dir_all(&plugin_dir).unwrap();
    let edited = format!(
        "{}// my change\n",
        legacy_session_plugin("opencode", "/old/bin/varde-workflow")
    );
    fs::write(plugin_dir.join("varde-session.ts"), &edited).unwrap();

    let mut report = Report::default();
    harness::rewrite_harness(&env, "opencode", &mut report);

    let entry = report
        .unrewritable
        .iter()
        .find(|entry| entry.path.ends_with("varde-session.ts"))
        .expect("edited legacy plugin reported");
    assert!(entry.reason.contains("rerun `varde setup sync`"));
    assert_eq!(entry.command, None);
    assert_eq!(
        fs::read_to_string(plugin_dir.join("varde-session.ts")).unwrap(),
        edited
    );
    assert!(!plugin_dir.join("varde.ts").exists());
}

#[test]
fn non_json_settings_are_reported_without_modification() {
    let _guard = test_guard();
    let env = fixture_env();
    let settings = env.home.join(".claude/settings.json");
    fs::create_dir_all(settings.parent().unwrap()).expect("Claude settings dir");
    let original = b"this is not json\n";
    fs::write(&settings, original).expect("write invalid settings");

    let mut report = Report::default();
    harness::rewrite_harness(&env, "claude", &mut report);

    assert!(
        report.unrewritable.iter().any(|entry| {
            entry.path == settings && entry.reason.to_lowercase().contains("json")
        })
    );
    assert_eq!(fs::read(settings).unwrap(), original);
}

#[test]
fn instructions_install_targets_or_reports_the_shared_warning() {
    let _guard = test_guard();
    let env = fixture_env();
    let target = env.home.join("AGENTS.md");
    let mut report = Report::default();
    harness::install_instructions(
        &env,
        std::slice::from_ref(&target),
        &["orchestration".into(), "toz".into()],
        &mut report,
    );
    let installed = fs::read_to_string(&target).expect("instruction target installed");
    assert!(installed.contains("<!-- varde:start -->"));
    assert!(installed.contains("<!-- varde:end -->"));

    let mut empty_env = env.clone();
    empty_env.config_dir = env.config_dir.join("no-instruction-targets");
    fs::create_dir_all(&empty_env.config_dir).expect("empty instruction config");
    let mut no_target_report = Report::default();
    harness::install_instructions(
        &empty_env,
        &[],
        &["orchestration".into(), "toz".into()],
        &mut no_target_report,
    );
    assert!(no_target_report.skipped.iter().any(|entry| {
        entry.reason == "Varde will not work as designed until its instruction block is installed: agents will not delegate as designed or use captured command output. Install it with `varde setup instructions install --target <file>`. Use one canonical `AGENTS.md` symlinked into each harness."
    }));
}

#[test]
fn instructions_install_includes_learn_guidance_when_installed() {
    let _guard = test_guard();
    let env = fixture_env();
    let target = env.home.join("AGENTS.md");
    let mut report = Report::default();

    harness::install_instructions(
        &env,
        std::slice::from_ref(&target),
        &["orchestration".into(), "toz".into(), "learn".into()],
        &mut report,
    );

    let installed = fs::read_to_string(&target).expect("instruction target installed");
    assert!(installed.contains("<!-- varde:start -->"));
    assert!(installed.contains("varde learn friction"));
}

#[test]
fn pins_marker_aware_toz_root_when_no_default_is_saved() {
    let _guard = test_guard();
    let env = fixture_env();
    let xdg = env.xdg_config_home.as_ref().expect("temporary XDG root");
    let legacy_root = xdg.join("tool-output-zone");
    fs::create_dir_all(&legacy_root).expect("pre-marker legacy Toz root");
    fs::create_dir_all(env.config_dir.join("toz")).expect("new Toz root before marker");
    let expected = toz_core::config::config_dir().expect("marker-aware Toz root");
    assert_eq!(expected, legacy_root);

    let mut report = Report::default();
    harness::pin_toz_store(&env, &mut report);

    assert!(report.unrewritable.is_empty(), "{:#?}", report.unrewritable);
    assert!(report.moved.iter().any(|entry| entry.path == expected));
    let paths = cli_output(&env, &["setup", "paths", "--json"]);
    assert!(
        paths.status.success(),
        "{}",
        String::from_utf8_lossy(&paths.stderr)
    );
    let paths: Value = serde_json::from_slice(&paths.stdout).expect("paths output JSON");
    let actual = PathBuf::from(paths["data"]["toz"].as_str().expect("resolved Toz path"));
    assert_eq!(
        fs::canonicalize(actual).unwrap(),
        fs::canonicalize(expected).unwrap()
    );
}

#[test]
fn dry_run_previews_real_actions_without_mutating_the_temp_tree() {
    let _guard = test_guard();
    let mut env = fixture_env();
    let legacy_root = env
        .xdg_config_home
        .as_ref()
        .expect("temporary XDG root")
        .join("tool-output-zone");
    fs::create_dir_all(&legacy_root).expect("pre-marker legacy Toz root");
    fs::create_dir_all(env.config_dir.join("toz")).expect("new Toz root before marker");
    let target = env.home.join("dry-run/AGENTS.md");
    let before = snapshot(&all_test_roots(&env));
    env.dry_run = true;

    let mut report = Report::default();
    for harness in ["claude", "codex", "opencode", "pi"] {
        harness::rewrite_harness(&env, harness, &mut report);
    }
    harness::install_instructions(
        &env,
        std::slice::from_ref(&target),
        &["orchestration".into(), "toz".into()],
        &mut report,
    );
    harness::pin_toz_store(&env, &mut report);

    assert_eq!(snapshot(&all_test_roots(&env)), before);
    assert!(report.unrewritable.is_empty(), "{:#?}", report.unrewritable);
    assert!(!report.would.is_empty());
    assert!(
        report
            .would
            .iter()
            .all(|entry| entry.reason.contains("prediction")),
        "dry-run actions must be labeled predictions: {:#?}",
        report.would
    );
    assert!(report.would.iter().any(|entry| {
        entry.path == toz_core::config::config_dir().unwrap()
            && entry
                .command
                .as_deref()
                .is_some_and(|command| command.contains("--toz"))
    }));
}
