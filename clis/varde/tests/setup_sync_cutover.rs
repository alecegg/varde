use std::collections::BTreeMap;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};

use serde_json::{Value, json};
use tempfile::TempDir;

struct Sandbox {
    _root: TempDir,
    root: PathBuf,
    home: PathBuf,
    codex_home: PathBuf,
    pi_agent: PathBuf,
    xdg: PathBuf,
    config: PathBuf,
    cargo_root: PathBuf,
    bin: PathBuf,
    work: PathBuf,
    skills: PathBuf,
    agents: PathBuf,
    toz_override: Option<PathBuf>,
}

impl Sandbox {
    fn new(with_toz_override: bool) -> Self {
        let root = tempfile::tempdir().expect("temporary test root");
        let root_path = root.path().to_path_buf();
        let home = root_path.join("home");
        let codex_home = root_path.join("codex");
        let pi_agent = root_path.join("pi-agent");
        let xdg = root_path.join("xdg");
        let config = root_path.join("varde-config");
        let cargo_root = root_path.join("cargo-install");
        let bin = root_path.join("bin");
        let work = root_path.join("work");
        let skills = root_path.join("canonical/skills");
        let agents = root_path.join("canonical/agents");
        let toz_override = with_toz_override.then(|| root_path.join("toz-override"));

        for directory in [
            &home,
            &codex_home,
            &pi_agent,
            &xdg,
            &config,
            &cargo_root,
            &bin,
            &work,
            &skills,
            &agents,
        ] {
            fs::create_dir_all(directory).expect("create isolated directory");
        }
        if let Some(path) = &toz_override {
            fs::create_dir_all(path).expect("create isolated Toz override");
        }
        for directory in [
            home.join(".claude"),
            home.join(".codex"),
            home.join(".config/opencode/plugin"),
            home.join(".pi"),
        ] {
            fs::create_dir_all(directory).expect("create fake harness root");
        }

        let sandbox = Self {
            _root: root,
            root: root_path,
            home,
            codex_home,
            pi_agent,
            xdg,
            config,
            cargo_root,
            bin,
            work,
            skills,
            agents,
            toz_override,
        };
        sandbox.seed_command_stubs();
        sandbox
    }

    fn seed_command_stubs(&self) {
        for (name, version) in [
            ("claude", "2.1.236"),
            ("codex", "0.140.0"),
            ("opencode", "2.0.0"),
            ("pi", "0.84.0"),
        ] {
            self.write_executable(
                &self.bin.join(name),
                &format!("#!/bin/sh\nprintf '%s\\n' '{version}'\n"),
            );
        }

        let manager_log = self.root.join("watch-manager.log");
        let manager = format!(
            "#!/bin/sh\ncase \" $* \" in\n  *' print '*|*' is-active '*) printf '%s\\n' 'Could not find service' >&2; exit 3 ;;\n  *' bootout '*|*' disable '*) printf '%s\\n' \"$*\" >> '{}' ; printf '%s\\n' 'Could not find service' >&2; exit 3 ;;\n  *' bootstrap '*|*' kickstart '*|*' enable '*) printf '%s\\n' \"$*\" >> '{}' ; printf '%s\\n' 'forced test failure' >&2; exit 1 ;;\n  *' daemon-reload '*) exit 0 ;;\n  *) printf '%s\\n' \"$*\" >> '{}' ; exit 0 ;;\nesac\n",
            manager_log.display(),
            manager_log.display(),
            manager_log.display(),
        );
        self.write_executable(&self.bin.join("launchctl"), &manager);
        self.write_executable(&self.bin.join("systemctl"), &manager);
    }

    fn write_executable(&self, path: &Path, contents: &str) {
        fs::write(path, contents).expect("write executable stub");
        let mut permissions = fs::metadata(path).expect("stub metadata").permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(path, permissions).expect("make stub executable");
    }

    fn run(&self, args: &[String]) -> Output {
        let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
        command
            .args(args)
            .current_dir(&self.work)
            .env_clear()
            .env("HOME", &self.home)
            .env("CODEX_HOME", &self.codex_home)
            .env("PI_CODING_AGENT_DIR", &self.pi_agent)
            .env("XDG_CONFIG_HOME", &self.xdg)
            .env("VARDE_CONFIG_DIR", &self.config)
            .env("CARGO_INSTALL_ROOT", &self.cargo_root)
            .env("VARDE_AGENTS_OPENCODE_VERSION", "1");
        let mut paths = vec![self.bin.clone()];
        if let Some(path) = std::env::var_os("PATH") {
            paths.extend(std::env::split_paths(&path));
        }
        command.env(
            "PATH",
            std::env::join_paths(paths).expect("join isolated PATH"),
        );
        if let Some(path) = &self.toz_override {
            command.env("TOZ_CONFIG_DIR", path);
        } else {
            command.env_remove("TOZ_CONFIG_DIR");
        }
        command.stdin(Stdio::null());
        command.output().expect("run isolated varde command")
    }

    fn run_sync(&self, options: &[&str]) -> Output {
        let mut args = vec![
            "setup".to_owned(),
            "sync".to_owned(),
            "--skills-dir".to_owned(),
            self.skills.display().to_string(),
            "--agents-dir".to_owned(),
            self.agents.display().to_string(),
        ];
        args.extend(options.iter().map(|option| (*option).to_owned()));
        self.run(&args)
    }

    fn run_sync_without_opencode_version(&self, options: &[&str]) -> Output {
        let mut args = vec![
            "setup".to_owned(),
            "sync".to_owned(),
            "--skills-dir".to_owned(),
            self.skills.display().to_string(),
            "--agents-dir".to_owned(),
            self.agents.display().to_string(),
        ];
        args.extend(options.iter().map(|option| (*option).to_owned()));

        let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
        command
            .args(args)
            .current_dir(&self.work)
            .env_clear()
            .env("HOME", &self.home)
            .env("CODEX_HOME", &self.codex_home)
            .env("PI_CODING_AGENT_DIR", &self.pi_agent)
            .env("XDG_CONFIG_HOME", &self.xdg)
            .env("VARDE_CONFIG_DIR", &self.config)
            .env("CARGO_INSTALL_ROOT", &self.cargo_root)
            .env("TMPDIR", std::env::temp_dir())
            .env(
                "VARDE_TEST_OPENCODE_PROBE_LOG",
                self.root.join("opencode-probe.log"),
            )
            .env_remove("VARDE_AGENTS_OPENCODE_VERSION");
        let mut paths = vec![self.bin.clone()];
        if let Some(path) = std::env::var_os("PATH") {
            paths.extend(std::env::split_paths(&path));
        }
        command.env(
            "PATH",
            std::env::join_paths(paths).expect("join isolated PATH"),
        );
        command.stdin(Stdio::null());
        command.output().expect("run isolated varde command")
    }

    fn configure_uninstalled_opencode_stub(&self) {
        for directory in [
            self.home.join(".claude"),
            self.home.join(".codex"),
            self.home.join(".config/opencode"),
            self.home.join(".pi"),
        ] {
            if directory.exists() {
                fs::remove_dir_all(directory).expect("remove fake harness config");
            }
        }
        self.write_executable(
            &self.bin.join("opencode"),
            "#!/bin/sh\nprintf '%s\\n' \"$HOME\" >> \"$VARDE_TEST_OPENCODE_PROBE_LOG\"\nmkdir -p \"$HOME/.config/opencode\"\nprintf '%s\\n' '2.0.0'\n",
        );
    }

    fn assert_probe_home_is_isolated(&self) {
        let path = fs::read_to_string(self.root.join("opencode-probe.log"))
            .expect("opencode version probe should run");
        assert_ne!(Path::new(path.trim()), self.home);
    }

    fn seed_legacy_stores(&self) {
        let code = self.home.join(".config/varde-code");
        fs::create_dir_all(&code).expect("legacy code store");
        fs::write(code.join("settings.json"), b"{\"old\":true}\n").unwrap();

        let toz = self.xdg.join("tool-output-zone");
        fs::create_dir_all(&toz).expect("legacy Toz store");
        fs::write(toz.join("events.jsonl"), b"legacy event\n").unwrap();
        if let Some(override_path) = &self.toz_override {
            fs::write(override_path.join("keep.jsonl"), b"override stays\n").unwrap();
        }
    }

    fn seed_legacy_harnesses(&self) {
        let claude_settings_path = self.home.join(".claude/settings.json");
        fs::write(
            &claude_settings_path,
            claude_settings(varde_code::hooks::LEGACY_SESSION_START_COMMAND),
        )
        .expect("legacy Claude hooks");

        let codex_dir = self.home.join(".codex");
        fs::write(
            codex_dir.join("config.toml"),
            format!(
                "[unrelated]\nkeep = \"yes\"\n\n[hooks.session_start]\ncommand = {:?}\n__source = \"varde-code\"\n",
                varde_code::hooks::LEGACY_SESSION_START_COMMAND
            ),
        )
        .unwrap();
        fs::write(codex_dir.join("hooks.json"), codex_hooks()).unwrap();

        let legacy_opencode = varde_code::hooks::LEGACY_OPENCODE_PLUGIN_V1_4;
        fs::write(
            self.home
                .join(".config/opencode/plugin/varde-code-nav-map.js"),
            legacy_opencode,
        )
        .unwrap();

        fs::create_dir_all(self.pi_agent.join("extensions")).unwrap();
        let legacy_pi = varde_code::hooks::LEGACY_PI_EXTENSION_V1_4;
        fs::write(self.pi_agent.join("extensions/pi-extension.js"), legacy_pi).unwrap();

        let opencode = self.xdg.join("opencode/plugin");
        fs::create_dir_all(&opencode).unwrap();
        fs::write(
            opencode.join("varde-session.ts"),
            legacy_session_plugin("opencode"),
        )
        .unwrap();
        fs::write(opencode.join("foreign.ts"), "// keep OpenCode plugin\n").unwrap();
        fs::write(
            self.pi_agent.join("extensions/varde-session.ts"),
            legacy_session_plugin("pi"),
        )
        .unwrap();
        fs::write(
            self.pi_agent.join("extensions/foreign.ts"),
            "// keep Pi extension\n",
        )
        .unwrap();

        self.seed_legacy_toz_plugins();
    }

    fn seed_legacy_toz_plugins(&self) {
        let claude = self.home.join(".claude/skills/toz");
        let claude_plugin = r#"{"name":"toz"}"#;
        let claude_hooks = r#"{"hooks":{"PostToolUse":[{"hooks":[{"type":"command","command":"varde-toz capture --hook"}]}]}}"#;
        fs::create_dir_all(claude.join(".claude-plugin")).unwrap();
        fs::create_dir_all(claude.join("hooks")).unwrap();
        fs::write(claude.join(".claude-plugin/plugin.json"), claude_plugin).unwrap();
        fs::write(claude.join("hooks/hooks.json"), claude_hooks).unwrap();
        write_manifest(
            &claude,
            &[
                (".claude-plugin/plugin.json", claude_plugin),
                ("hooks/hooks.json", claude_hooks),
            ],
        );

        let opencode = self.xdg.join("opencode");
        let old = "// legacy command: varde-toz capture --hook --harness opencode\n";
        fs::create_dir_all(opencode.join("plugin")).unwrap();
        fs::write(opencode.join("plugin/toz.ts"), old).unwrap();
        write_manifest(&opencode, &[("plugin/toz.ts", old)]);

        let pi = self.pi_agent.clone();
        let old = "// legacy command: toz capture --hook --harness pi\n";
        fs::create_dir_all(pi.join("extensions")).unwrap();
        fs::write(pi.join("extensions/toz.ts"), old).unwrap();
        write_manifest(&pi, &[("extensions/toz.ts", old)]);
    }

    fn seed_legacy_bins(&self) {
        let bin = self.cargo_root.join("bin");
        fs::create_dir_all(&bin).unwrap();
        for (name, identity) in [
            ("varde-code", "varde-code 1.6.0"),
            ("varde-workflow", "varde-workflow 1.6.0"),
            ("varde-toz", "varde-toz 1.6.0"),
            ("toz", "varde-toz 1.6.0"),
            ("varde-learn", "varde-learn 1.6.0"),
        ] {
            self.write_executable(
                &bin.join(name),
                &format!("#!/bin/sh\nprintf '%s\\n' '{identity}'\n"),
            );
        }
    }

    fn seed_registered_watcher(&self) -> PathBuf {
        let repo = self.work.join("watched-repo");
        fs::create_dir_all(repo.join(".git")).unwrap();
        let repo = fs::canonicalize(repo).unwrap();
        let hash = watch_set_id(&repo);
        let watch_dir = self.home.join(".config/varde-code/watch-locks");
        fs::create_dir_all(&watch_dir).unwrap();
        let owner = json!({"pid": 4_000_000_000u64, "generation": "test-generation"});
        fs::write(
            watch_dir.join(format!("{hash}.lock")),
            serde_json::to_vec(&owner).unwrap(),
        )
        .unwrap();
        fs::write(
            watch_dir.join(format!("{hash}.meta")),
            serde_json::to_vec(&json!({
                "repos": [repo.display().to_string()],
                "owner": owner,
                "ready_repos": [],
                "stopped": false,
            }))
            .unwrap(),
        )
        .unwrap();
        #[cfg(target_os = "macos")]
        let service = self
            .home
            .join("Library/LaunchAgents")
            .join(format!("varde-code-{hash}.plist"));
        #[cfg(target_os = "linux")]
        let service = self
            .home
            .join(".config/systemd/user")
            .join(format!("varde-code-{hash}.service"));
        fs::create_dir_all(service.parent().unwrap()).unwrap();
        fs::write(&service, "fake watcher unit; never loaded by the host\n").unwrap();
        repo
    }
}

fn claude_settings(code_command: &str) -> String {
    let code = serde_json::to_string(code_command).unwrap();
    let session =
        serde_json::to_string("varde-workflow hook session-start --harness claude").unwrap();
    format!(
        r#"{{"before":{{"keep":"yes"}},"hooks":{{"SessionStart":[{{"matcher":"","hooks":[{{"type":"command","command":{code},"__source":"varde-code"}}]}},{{"matcher":"","hooks":[{{"type":"command","command":{session}}}]}},{{"matcher":"","hooks":[{{"type":"command","command":"echo foreign-session"}}]}}]}},"after":7}}"#
    )
}

fn codex_hooks() -> &'static str {
    r#"{"before":{"keep":"yes"},"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"varde-workflow hook session-start --harness codex"}]},{"hooks":[{"type":"command","command":"echo foreign-session"}]}],"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"toz capture --hook --harness codex","timeout":30},{"type":"command","command":"echo foreign-post"}]}]},"after":7}"#
}

fn write_manifest(root: &Path, files: &[(&str, &str)]) {
    let hashes = files
        .iter()
        .map(|(relative, text)| {
            (
                (*relative).to_owned(),
                toz_core::content_hash(text.as_bytes()),
            )
        })
        .collect::<BTreeMap<_, _>>();
    fs::write(
        root.join(".varde-toz-install.json"),
        serde_json::to_vec_pretty(&json!({"version": 1, "files": hashes})).unwrap(),
    )
    .unwrap();
}

fn watch_set_id(repo: &Path) -> String {
    const OFFSET: u64 = 0xcbf29ce484222325;
    const PRIME: u64 = 0x100000001b3;
    let mut hash = OFFSET;
    for byte in repo.to_string_lossy().as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(PRIME);
    }
    format!("{hash:016x}")
}

fn snapshot(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    fn visit(root: &Path, path: &Path, files: &mut BTreeMap<PathBuf, Vec<u8>>) {
        let metadata = fs::symlink_metadata(path).unwrap();
        let relative = path.strip_prefix(root).unwrap().to_path_buf();
        if metadata.is_dir() {
            files.insert(relative, b"<directory>".to_vec());
            for entry in fs::read_dir(path).unwrap() {
                visit(root, &entry.unwrap().path(), files);
            }
        } else if metadata.file_type().is_symlink() {
            files.insert(
                relative,
                fs::read_link(path)
                    .unwrap()
                    .into_os_string()
                    .into_encoded_bytes(),
            );
        } else {
            files.insert(relative, fs::read(path).unwrap());
        }
    }

    let mut files = BTreeMap::new();
    if root.exists() {
        visit(root, root, &mut files);
    }
    files
}

fn report(output: &Output) -> Value {
    let stdout = String::from_utf8_lossy(&output.stdout);
    let envelope: Value = serde_json::from_slice(&output.stdout)
        .unwrap_or_else(|error| panic!("stdout is not a JSON envelope ({error}): {stdout}"));
    assert_eq!(envelope["schema_version"], 1, "{stdout}");
    assert_eq!(envelope["ok"], true, "{stdout}");
    envelope["data"].clone()
}

fn assert_success(output: &Output) {
    assert!(
        output.status.success(),
        "stdout: {}\nstderr: {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn missing_targets_fail_before_any_migration_and_never_prompt() {
    let sandbox = Sandbox::new(false);
    let before = snapshot(&sandbox.root);

    let output = sandbox.run(&["setup".into(), "sync".into()]);

    assert_eq!(output.status.code(), Some(2));
    assert_eq!(snapshot(&sandbox.root), before);
}

#[test]
fn harnesses_none_does_not_create_unconfigured_opencode_home() {
    let sandbox = Sandbox::new(false);
    sandbox.configure_uninstalled_opencode_stub();

    let output = sandbox.run_sync_without_opencode_version(&["--harnesses", "none"]);

    assert_success(&output);
    assert!(
        !sandbox.home.join(".config/opencode").exists(),
        "sync created an OpenCode home while no OpenCode harness was selected"
    );
    sandbox.assert_probe_home_is_isolated();
}

#[test]
fn default_sync_does_not_create_unconfigured_opencode_home() {
    let sandbox = Sandbox::new(false);
    sandbox.configure_uninstalled_opencode_stub();

    let output = sandbox.run_sync_without_opencode_version(&[]);

    assert_success(&output);
    assert!(
        !sandbox.home.join(".config/opencode").exists(),
        "default sync created an OpenCode home without OpenCode configuration"
    );
    sandbox.assert_probe_home_is_isolated();
}

#[test]
fn help_describes_the_repeatable_instruction_target_flag() {
    let sandbox = Sandbox::new(false);

    let output = sandbox.run(&["setup".into(), "sync".into(), "--help".into()]);

    assert_success(&output);
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("--instructions-target <FILE>"), "{stdout}");
    assert!(stdout.contains("repeatable"), "{stdout}");
}

#[test]
fn dry_run_previews_the_real_pin_and_watch_actions_without_mutating_anything() {
    let sandbox = Sandbox::new(false);
    sandbox.seed_legacy_stores();
    sandbox.seed_legacy_harnesses();
    sandbox.seed_legacy_bins();
    let repo = sandbox.seed_registered_watcher();
    let target = sandbox.work.join("AGENTS.md");
    let options = [
        "--harnesses",
        "claude,codex,opencode,pi",
        "--instructions-target",
        target.to_str().unwrap(),
        "--dry-run",
        "--json",
    ];
    let before = snapshot(&sandbox.root);

    let output = sandbox.run_sync(&options);

    assert_success(&output);
    let data = report(&output);
    assert_eq!(snapshot(&sandbox.root), before);
    let would = data["would"].as_array().expect("would actions");
    assert!(!would.is_empty());
    assert!(
        would
            .iter()
            .all(|entry| entry["reason"].as_str().unwrap().contains("prediction"))
    );
    assert!(would.iter().any(|entry| {
        entry["path"] == repo.to_str().unwrap()
            && entry["reason"]
                .as_str()
                .unwrap()
                .contains("stop and later re-register")
    }));
    let legacy_toz = sandbox.xdg.join("tool-output-zone");
    assert!(would.iter().any(|entry| {
        entry["command"].as_str().is_some_and(|command| {
            command.contains("--toz") && command.contains(legacy_toz.to_str().unwrap())
        })
    }));
}

/// The plugin the legacy `varde-workflow hook install` wrote, as the legacy installer filled it.
fn legacy_session_plugin(harness: &str) -> String {
    let asset = if harness == "pi" {
        include_str!("../src/migrate/legacy/pi-varde-session.ts").to_owned()
    } else {
        let all = include_str!("../src/migrate/legacy/opencode-varde-session.ts");
        let (header, rest) = all.split_once("//@@v1\n").unwrap();
        let (_, v2) = rest.split_once("//@@v2\n").unwrap();
        format!("{header}{v2}")
    };
    asset.replace("\"{{VARDE_WORKFLOW_BIN}}\"", "\"/old/bin/varde-workflow\"")
}

fn count(text: &str, needle: &str) -> usize {
    text.matches(needle).count()
}

#[test]
fn sync_moves_stores_rewrites_all_harnesses_installs_instructions_and_is_idempotent() {
    let sandbox = Sandbox::new(false);
    sandbox.seed_legacy_stores();
    sandbox.seed_legacy_harnesses();
    sandbox.seed_legacy_bins();
    let first_target = sandbox.home.join("AGENTS.md");
    let second_target = sandbox.work.join("AGENTS.md");
    let options = [
        "--harnesses",
        "claude,codex,opencode,pi",
        "--instructions-target",
        first_target.to_str().unwrap(),
        "--instructions-target",
        second_target.to_str().unwrap(),
        "--json",
    ];

    let first = sandbox.run_sync(&options);

    assert_success(&first);
    let first_report = report(&first);
    assert!(
        first_report["unrewritable"].as_array().unwrap().is_empty(),
        "{first_report}"
    );
    for target in [&first_target, &second_target] {
        let instructions = fs::read_to_string(target).expect("instruction target installed");
        assert!(instructions.contains("<!-- varde:start -->"));
        assert!(instructions.contains("<!-- varde:end -->"));
    }

    let code_source = sandbox.home.join(".config/varde-code");
    let code_target = sandbox.config.join("code");
    assert!(!code_source.exists());
    assert_eq!(
        fs::read(code_target.join("settings.json")).unwrap(),
        b"{\"old\":true}\n"
    );
    assert!(code_target.join(".varde-migration-complete").exists());
    let toz_source = sandbox.xdg.join("tool-output-zone");
    let toz_target = sandbox.config.join("toz");
    assert!(!toz_source.exists());
    assert_eq!(
        fs::read(toz_target.join("events.jsonl")).unwrap(),
        b"legacy event\n"
    );
    assert!(toz_target.join(".varde-migration-complete").exists());
    let paths = sandbox.run(&["setup".into(), "paths".into(), "--json".into()]);
    assert_success(&paths);
    let paths: Value = serde_json::from_slice(&paths.stdout).unwrap();
    assert_eq!(
        fs::canonicalize(paths["data"]["toz"].as_str().unwrap()).unwrap(),
        fs::canonicalize(&toz_target).unwrap()
    );

    let claude_path = sandbox.home.join(".claude/settings.json");
    let claude = fs::read_to_string(&claude_path).unwrap();
    assert!(claude.find("\"before\"") < claude.find("\"hooks\""));
    assert!(claude.find("\"hooks\"") < claude.find("\"after\""));
    assert!(claude.contains("echo foreign-session"));
    assert!(!claude.contains("varde-code nav_map"));
    assert!(!claude.contains("varde-workflow hook session-start"));
    assert_eq!(count(&claude, "hook session-start --harness claude"), 1);
    assert_eq!(count(&claude, "hook post-tool-use --harness claude"), 1);
    assert_eq!(
        count(&claude, "hook user-prompt-submit --harness claude"),
        1
    );
    assert!(!sandbox.home.join(".claude/skills/toz").exists());
    assert!(!sandbox.home.join(".claude/skills/varde-toz-hooks").exists());

    let codex = fs::read_to_string(sandbox.home.join(".codex/hooks.json")).unwrap();
    assert!(codex.find("\"before\"") < codex.find("\"hooks\""));
    assert!(codex.find("\"hooks\"") < codex.find("\"after\""));
    assert!(codex.contains("echo foreign-session"));
    assert!(codex.contains("echo foreign-post"));
    assert!(!codex.contains("varde-workflow hook session-start"));
    assert!(!codex.contains("toz capture --hook"));
    assert_eq!(count(&codex, "hook session-start --harness codex"), 1);
    assert_eq!(count(&codex, "hook post-tool-use --harness codex"), 1);
    assert_eq!(count(&codex, "hook user-prompt-submit --harness codex"), 1);

    let codex_config = fs::read_to_string(sandbox.home.join(".codex/config.toml")).unwrap();
    assert!(codex_config.contains("[unrelated]\nkeep = \"yes\""));
    assert!(!codex_config.contains("varde-code nav_map"));
    let opencode_plugins = sandbox.xdg.join("opencode/plugin");
    for retired in ["toz.ts", "varde-toz.ts", "varde-session.ts"] {
        assert!(!opencode_plugins.join(retired).exists(), "{retired}");
    }
    assert!(opencode_plugins.join("varde.ts").is_file());
    assert!(
        fs::read_to_string(opencode_plugins.join("foreign.ts"))
            .unwrap()
            .contains("keep OpenCode")
    );
    assert!(
        !sandbox
            .home
            .join(".config/opencode/plugin/varde-code-nav-map.js")
            .exists()
    );
    let pi_extensions = sandbox.pi_agent.join("extensions");
    for retired in [
        "toz.ts",
        "varde-toz.ts",
        "varde-session.ts",
        "pi-extension.js",
    ] {
        assert!(!pi_extensions.join(retired).exists(), "{retired}");
    }
    assert!(pi_extensions.join("varde.ts").is_file());
    assert!(
        fs::read_to_string(pi_extensions.join("foreign.ts"))
            .unwrap()
            .contains("keep Pi")
    );
    for binary in [
        "varde-code",
        "varde-workflow",
        "varde-toz",
        "toz",
        "varde-learn",
    ] {
        assert!(
            !sandbox.cargo_root.join("bin").join(binary).exists(),
            "{binary} remains"
        );
    }

    let after_first = snapshot(&sandbox.root);
    let second = sandbox.run_sync(&options);
    assert_success(&second);
    assert_eq!(snapshot(&sandbox.root), after_first);
}

#[test]
fn harnesses_none_leaves_every_harness_file_untouched() {
    let sandbox = Sandbox::new(false);
    sandbox.seed_legacy_harnesses();
    sandbox.seed_legacy_bins();
    fs::write(
        sandbox.xdg.join("opencode/plugin/varde-session.ts"),
        "const legacyCommand = \"varde-workflow hook session-start --harness opencode\";\n",
    )
    .unwrap();
    fs::write(
        sandbox.xdg.join("opencode/plugin/toz.ts"),
        "const legacyCommand = \"varde-toz capture --hook --harness opencode\";\n",
    )
    .unwrap();
    let paths = [
        sandbox.home.join(".claude/settings.json"),
        sandbox.home.join(".codex/config.toml"),
        sandbox.home.join(".codex/hooks.json"),
        sandbox
            .home
            .join(".config/opencode/plugin/varde-code-nav-map.js"),
        sandbox.xdg.join("opencode/plugin/varde-session.ts"),
        sandbox.pi_agent.join("extensions/pi-extension.js"),
        sandbox.pi_agent.join("extensions/varde-session.ts"),
    ];
    let before = paths
        .iter()
        .map(|path| (path.clone(), fs::read(path).unwrap()))
        .collect::<Vec<_>>();

    let output = sandbox.run_sync(&["--harnesses", "none", "--json"]);

    assert_success(&output);
    let data = report(&output);
    for (path, contents) in before {
        assert_eq!(fs::read(path).unwrap(), contents);
    }
    for binary in ["varde-code", "varde-workflow", "varde-toz"] {
        assert!(sandbox.cargo_root.join("bin").join(binary).exists());
        assert!(data["skipped"].as_array().unwrap().iter().any(|entry| {
            entry["command"]
                .as_str()
                .is_some_and(|command| command.contains(binary))
        }));
    }
    assert!(!sandbox.cargo_root.join("bin/varde-learn").exists());
}

#[test]
fn explicit_toz_override_stays_while_default_store_moves() {
    let sandbox = Sandbox::new(true);
    sandbox.seed_legacy_stores();

    let output = sandbox.run_sync(&["--harnesses", "none", "--json"]);

    assert_success(&output);
    assert!(!sandbox.xdg.join("tool-output-zone").exists());
    assert!(sandbox.config.join("toz/events.jsonl").exists());
    let override_path = sandbox.toz_override.as_ref().unwrap();
    assert_eq!(
        fs::read(override_path.join("keep.jsonl")).unwrap(),
        b"override stays\n"
    );
}

#[test]
fn distinct_toz_store_does_not_keep_binary_and_moves_on_later_sync() {
    let sandbox = Sandbox::new(false);
    sandbox.seed_legacy_stores();
    let unselected = sandbox.xdg.join("varde-toz");
    fs::create_dir_all(&unselected).unwrap();
    fs::write(unselected.join("later.jsonl"), b"later store\n").unwrap();
    sandbox.seed_legacy_bins();

    let first = sandbox.run_sync(&["--harnesses", "none", "--json"]);

    assert_success(&first);
    let first_report = report(&first);
    assert!(unselected.exists());
    assert!(
        !sandbox.cargo_root.join("bin/varde-toz").exists(),
        "a skipped store path alone must not protect the legacy binary"
    );
    assert!(
        first_report["skipped"]
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| {
                entry["path"] == unselected.display().to_string()
                    && entry["reason"]
                        .as_str()
                        .is_some_and(|reason| reason.contains("left in place"))
            }),
        "{first_report}"
    );

    let second = sandbox.run_sync(&["--harnesses", "none", "--json"]);

    assert_success(&second);
    assert!(!unselected.exists());
    assert_eq!(
        fs::read(sandbox.config.join("toz/later.jsonl")).unwrap(),
        b"later store\n"
    );
}

#[test]
fn sync_merges_reappearing_legacy_code_without_overwriting_target_caches() {
    let sandbox = Sandbox::new(false);
    let legacy = sandbox.home.join(".config/varde-code");
    let current = sandbox.config.join("code");
    fs::create_dir_all(legacy.join("repos/example")).unwrap();
    fs::create_dir_all(current.join("repos/example")).unwrap();
    fs::write(current.join(".varde-migration-complete"), b"").unwrap();
    fs::write(current.join("settings.json"), b"{\"current\":true}\n").unwrap();
    fs::write(legacy.join("settings.json"), b"{\"legacy\":true}\n").unwrap();
    fs::write(legacy.join("new-data.json"), b"merge me\n").unwrap();
    fs::write(current.join("repos/example/index.db"), b"target cache").unwrap();
    fs::write(legacy.join("repos/example/index.db"), b"legacy cache").unwrap();

    let output = sandbox.run_sync(&["--harnesses", "none", "--json"]);

    assert_success(&output);
    let data = report(&output);
    assert_eq!(
        fs::read(current.join("settings.json")).unwrap(),
        b"{\"current\":true}\n"
    );
    assert!(legacy.join("settings.json").exists());
    assert_eq!(
        fs::read(current.join("new-data.json")).unwrap(),
        b"merge me\n"
    );
    assert!(!legacy.join("new-data.json").exists());
    assert_eq!(
        fs::read(current.join("repos/example/index.db")).unwrap(),
        b"target cache"
    );
    assert!(!legacy.join("repos/example/index.db").exists());
    assert!(current.join(".varde-migration-complete").exists());
    let conflict = fs::canonicalize(legacy.join("settings.json")).unwrap();
    assert!(
        data["unrewritable"]
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| { entry["path"] == conflict.display().to_string() }),
        "{data}"
    );
}

#[test]
fn unrewritable_harness_and_failed_watch_are_reported_without_failing_sync() {
    let sandbox = Sandbox::new(false);
    sandbox.seed_legacy_stores();
    sandbox.seed_legacy_harnesses();
    sandbox.seed_legacy_bins();
    let settings = sandbox.home.join(".claude/settings.json");
    fs::write(
        &settings,
        claude_settings(&format!(
            "{} --local-change",
            varde_code::hooks::LEGACY_SESSION_START_COMMAND
        )),
    )
    .unwrap();
    let toz_legacy = sandbox.home.join(".claude/skills/toz");
    let _ = fs::remove_file(toz_legacy.join(".varde-toz-install.json"));
    let customized = r#"{"name":"user customized legacy toz plugin"}"#;
    fs::write(toz_legacy.join(".claude-plugin/plugin.json"), customized).unwrap();
    let repo = sandbox.seed_registered_watcher();
    let options = ["--harnesses", "claude", "--json"];

    let output = sandbox.run_sync(&options);

    assert_success(&output);
    let data = report(&output);
    let unrewritable = data["unrewritable"].as_array().unwrap();
    let watcher = unrewritable
        .iter()
        .find(|entry| {
            entry["path"] == repo.to_str().unwrap()
                && entry["reason"]
                    .as_str()
                    .unwrap()
                    .contains("repo remains unregistered")
        })
        .expect("failed watcher is reported against its repository");
    assert_eq!(
        watcher["command"],
        format!("varde setup watch --ensure --repo {}", repo.display())
    );
    assert!(unrewritable.iter().any(|entry| {
        entry["path"] == settings.to_str().unwrap()
            && entry["reason"]
                .as_str()
                .unwrap()
                .contains("rerun `varde setup sync`")
    }));
    assert!(unrewritable.iter().any(|entry| {
        entry["reason"]
            .as_str()
            .unwrap()
            .contains("per-feature Toz install")
    }));
    assert!(sandbox.cargo_root.join("bin/varde-code").exists());
    assert!(sandbox.cargo_root.join("bin/varde-toz").exists());
    let manager_log = fs::read_to_string(sandbox.root.join("watch-manager.log")).unwrap();
    #[cfg(target_os = "macos")]
    {
        assert!(manager_log.contains("bootstrap"));
        assert!(manager_log.contains("kickstart"));
    }
    #[cfg(target_os = "linux")]
    assert!(manager_log.contains("enable"));
}
