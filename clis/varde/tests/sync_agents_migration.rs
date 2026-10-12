use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

#[cfg(unix)]
use std::os::unix::fs::symlink;

use tempfile::TempDir;
use varde::sync::embedded::{Agent, AgentVariant, agents};

const MARKDOWN_MARKER: &str = "\n<!-- varde-managed-agent -->\n";
const TOML_MARKER: &str = "\n# varde-managed-agent\n";

struct Sandbox {
    _root: TempDir,
    home: PathBuf,
    config: PathBuf,
    pi_agent: PathBuf,
    cwd: PathBuf,
    bin: PathBuf,
    skills: PathBuf,
    agents: PathBuf,
}

impl Sandbox {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let home = root.path().join("home");
        let config = root.path().join("config");
        let pi_agent = root.path().join("pi-agent");
        let cwd = root.path().join("work");
        let bin = root.path().join("bin");
        let skills = root.path().join("canonical/skills");
        let agents = root.path().join("canonical/agents");
        for directory in [&home, &config, &pi_agent, &cwd, &bin] {
            fs::create_dir_all(directory).unwrap();
        }
        Self {
            _root: root,
            home,
            config,
            pi_agent,
            cwd,
            bin,
            skills,
            agents,
        }
    }

    fn run(&self, harnesses: &str, options: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_varde"))
            .args([
                "setup",
                "sync",
                "--skills-dir",
                self.skills.to_str().unwrap(),
                "--agents-dir",
                self.agents.to_str().unwrap(),
                "--harnesses",
                harnesses,
            ])
            .args(options)
            .current_dir(&self.cwd)
            .env_clear()
            .env("HOME", &self.home)
            .env("VARDE_CONFIG_DIR", &self.config)
            .env("PI_CODING_AGENT_DIR", &self.pi_agent)
            .env("VARDE_AGENTS_OPENCODE_VERSION", "1.4.0")
            .env("PATH", &self.bin)
            .output()
            .unwrap()
    }

    fn harness_agents(&self, harness: &str) -> PathBuf {
        match harness {
            "claude" => self.home.join(".claude/agents"),
            "codex" => self.home.join(".codex/agents"),
            "opencode" => self.home.join(".config/opencode/agents"),
            "pi" => self.pi_agent.join("agents"),
            _ => panic!("unknown harness {harness}"),
        }
    }

    fn canonical_agent(&self, harness: &str, name: &str, extension: &str) -> PathBuf {
        self.agents
            .join(harness)
            .join(format!("{name}.{extension}"))
    }
}

fn stdout(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn variant<'a>(agent: &'a Agent, file_name: &str) -> &'a AgentVariant {
    agent
        .variants
        .iter()
        .find(|variant| variant.file_name == file_name)
        .unwrap_or_else(|| panic!("{} has no embedded {file_name}", agent.name))
}

fn agent(name: &str) -> &'static Agent {
    agents()
        .iter()
        .find(|agent| agent.name == name)
        .unwrap_or_else(|| panic!("unknown embedded agent {name}"))
}

fn managed_variant(agent: &Agent, file_name: &str, model: Option<&str>) -> String {
    let source = std::str::from_utf8(variant(agent, file_name).bytes).unwrap();
    let prefix = if file_name.ends_with(".toml") {
        "model = "
    } else {
        "model: "
    };
    let mut contents = source
        .lines()
        .map(|line| match model {
            Some(model) if line.starts_with(prefix) => format!("{prefix}{model}"),
            _ => line.to_owned(),
        })
        .collect::<Vec<_>>()
        .join("\n");
    contents.push('\n');
    contents.push_str(if file_name.ends_with(".toml") {
        TOML_MARKER
    } else {
        MARKDOWN_MARKER
    });
    contents
}

fn replace_field(contents: &str, prefix: &str, value: &str) -> String {
    let mut changed = false;
    let replaced = contents
        .lines()
        .map(|line| {
            if !changed && line.starts_with(prefix) {
                changed = true;
                format!("{prefix}{value}")
            } else {
                line.to_owned()
            }
        })
        .collect::<Vec<_>>()
        .join("\n");
    assert!(changed, "missing field {prefix}");
    format!("{replaced}\n")
}

fn assert_model(path: &Path, expected: &str) {
    let contents = fs::read_to_string(path).unwrap();
    assert!(
        contents.lines().any(|line| line == expected),
        "{} does not contain {expected:?}",
        path.display()
    );
}

#[cfg(unix)]
#[test]
fn migrates_a_managed_harness_file_before_linking_it() {
    let sandbox = Sandbox::new();
    let harness_dir = sandbox.harness_agents("claude");
    fs::create_dir_all(&harness_dir).unwrap();
    let destination = harness_dir.join("varde-planner.md");
    fs::write(
        &destination,
        managed_variant(
            agent("varde-planner"),
            "claude.md",
            Some("\"user/model-from-claude\""),
        ),
    )
    .unwrap();

    let output = sandbox.run("claude", &[]);
    assert!(output.status.success(), "{}", stderr(&output));

    let canonical = sandbox.canonical_agent("claude", "varde-planner", "md");
    assert_model(&canonical, "model: \"user/model-from-claude\"");
    assert_eq!(fs::read_link(&destination).unwrap(), canonical);
    assert!(stdout(&output).contains("Preserved user model setting model"));
}

#[test]
fn migrates_model_settings_from_renamed_agents_and_executor_build() {
    let sandbox = Sandbox::new();
    let harness_dir = sandbox.harness_agents("claude");
    fs::create_dir_all(&harness_dir).unwrap();

    for (old_name, agent_name, model) in [
        ("explore", "varde-explorer", "\"user/model-from-explore\""),
        ("plan", "varde-planner", "\"user/model-from-plan\""),
        ("review", "varde-reviewer", "\"user/model-from-review\""),
        ("executor", "varde-builder", "\"user/model-from-executor\""),
    ] {
        fs::write(
            harness_dir.join(format!("{old_name}.md")),
            managed_variant(agent(agent_name), "claude.md", Some(model)),
        )
        .unwrap();
    }
    fs::write(
        harness_dir.join("build.md"),
        managed_variant(
            agent("varde-builder"),
            "claude.md",
            Some("\"user/model-from-build\""),
        ),
    )
    .unwrap();

    let output = sandbox.run("claude", &["--link-mode", "copy"]);
    assert!(output.status.success(), "{}", stderr(&output));
    assert_model(
        &sandbox.canonical_agent("claude", "varde-explorer", "md"),
        "model: \"user/model-from-explore\"",
    );
    assert_model(
        &sandbox.canonical_agent("claude", "varde-planner", "md"),
        "model: \"user/model-from-plan\"",
    );
    assert_model(
        &sandbox.canonical_agent("claude", "varde-reviewer", "md"),
        "model: \"user/model-from-review\"",
    );
    assert_model(
        &sandbox.canonical_agent("claude", "varde-builder", "md"),
        "model: \"user/model-from-executor\"",
    );
}

#[test]
fn build_alias_is_a_model_source_and_is_removed_after_sync() {
    for (harness, extension, variant_name, model_prefix) in [
        ("claude", "md", "claude.md", "model: "),
        ("codex", "toml", "codex.toml", "model = "),
        ("opencode", "md", "opencode.md", "model: "),
    ] {
        let sandbox = Sandbox::new();
        let harness_dir = sandbox.harness_agents(harness);
        fs::create_dir_all(&harness_dir).unwrap();
        let build = harness_dir.join(format!("build.{extension}"));
        let mut contents = managed_variant(
            agent("varde-builder"),
            variant_name,
            Some("\"user/model-from-build\""),
        );
        if harness == "codex" {
            contents = replace_field(
                &contents,
                "model_reasoning_effort = ",
                "\"user/effort-from-build\"",
            );
        }
        fs::write(&build, contents).unwrap();

        let output = sandbox.run(harness, &["--link-mode", "copy"]);
        assert!(output.status.success(), "{}", stderr(&output));
        let canonical = sandbox.canonical_agent(harness, "varde-builder", extension);
        assert_model(
            &canonical,
            &format!("{model_prefix}\"user/model-from-build\""),
        );
        if harness == "codex" {
            assert_model(
                &canonical,
                "model_reasoning_effort = \"user/effort-from-build\"",
            );
        }
        assert!(!build.exists(), "kept {}", build.display());
    }

    for (harness, extension, variant_name) in [
        ("claude", "md", "claude.md"),
        ("codex", "toml", "codex.toml"),
        ("opencode", "md", "opencode.md"),
    ] {
        let sandbox = Sandbox::new();
        let harness_dir = sandbox.harness_agents(harness);
        fs::create_dir_all(&harness_dir).unwrap();
        let build = harness_dir.join(format!("build.{extension}"));
        let executor = harness_dir.join(format!("varde-builder.{extension}"));
        fs::write(
            &build,
            managed_variant(
                agent("varde-builder"),
                variant_name,
                Some("\"user/model-from-build\""),
            ),
        )
        .unwrap();
        fs::write(&executor, "unowned executor\n").unwrap();

        let output = sandbox.run(harness, &["--link-mode", "copy"]);
        assert!(output.status.success(), "{}", stderr(&output));
        assert!(build.exists(), "removed blocked {}", build.display());
        assert_eq!(fs::read_to_string(&executor).unwrap(), "unowned executor\n");
    }
}

#[cfg(unix)]
#[test]
fn retired_canonical_links_and_dangling_aliases_are_removed_in_both_link_modes() {
    for link_mode in ["symlink", "copy"] {
        for (harness, extension, variant_name) in [
            ("claude", "md", "claude.md"),
            ("codex", "toml", "codex.toml"),
            ("opencode", "md", "opencode.md"),
            ("pi", "md", "pi.md"),
        ] {
            let sandbox = Sandbox::new();
            let harness_dir = sandbox.harness_agents(harness);
            fs::create_dir_all(&harness_dir).unwrap();
            let canonical_directory = sandbox.agents.join(harness);
            fs::create_dir_all(&canonical_directory).unwrap();

            let old_canonical = canonical_directory.join(format!("varde-executor.{extension}"));
            fs::write(
                &old_canonical,
                managed_variant(
                    agent("varde-builder"),
                    variant_name,
                    Some("\"user/model-from-canonical-executor\""),
                ),
            )
            .unwrap();
            symlink(
                &old_canonical,
                harness_dir.join(format!("varde-executor.{extension}")),
            )
            .unwrap();
            let foreign_target = sandbox._root.path().join("foreign-agent");
            fs::write(&foreign_target, "foreign\n").unwrap();
            symlink(
                canonical_directory.join(format!("executor.{extension}")),
                harness_dir.join(format!("executor.{extension}")),
            )
            .unwrap();
            symlink(
                &foreign_target,
                harness_dir.join(format!("build.{extension}")),
            )
            .unwrap();
            let foreign_link = harness_dir.join(format!("foreign.{extension}"));
            symlink(&foreign_target, &foreign_link).unwrap();
            let foreign_file = harness_dir.join(format!("user.{extension}"));
            fs::write(&foreign_file, "user-owned\n").unwrap();

            if harness == "opencode" {
                let legacy = sandbox.home.join(".config/opencode/agent");
                fs::create_dir_all(&legacy).unwrap();
                symlink(&old_canonical, legacy.join("varde-executor.md")).unwrap();
                symlink(
                    canonical_directory.join("build.md"),
                    legacy.join("build.md"),
                )
                .unwrap();
            }

            let output = sandbox.run(harness, &["--link-mode", link_mode]);
            assert!(output.status.success(), "{}", stderr(&output));
            if harness != "pi" {
                assert_model(
                    &sandbox.canonical_agent(harness, "varde-builder", extension),
                    &format!(
                        "{}\"user/model-from-canonical-executor\"",
                        if harness == "codex" {
                            "model = "
                        } else {
                            "model: "
                        }
                    ),
                );
            }
            assert!(!old_canonical.exists(), "kept {}", old_canonical.display());
            for retired in ["varde-executor", "executor"] {
                assert!(
                    fs::symlink_metadata(harness_dir.join(format!("{retired}.{extension}")))
                        .is_err(),
                    "kept retired link {retired} for {harness}"
                );
            }
            assert!(harness_dir.join(format!("build.{extension}")).exists());
            assert!(foreign_link.exists());
            assert_eq!(fs::read_to_string(foreign_file).unwrap(), "user-owned\n");
            if harness == "opencode" {
                let legacy = sandbox.home.join(".config/opencode/agent");
                assert!(fs::symlink_metadata(legacy.join("varde-executor.md")).is_err());
                assert!(fs::symlink_metadata(legacy.join("build.md")).is_err());
            }
        }
    }
}

#[test]
fn cleanup_dry_run_reports_only_managed_stale_files() {
    let sandbox = Sandbox::new();
    let harness_dir = sandbox.harness_agents("claude");
    fs::create_dir_all(&harness_dir).unwrap();
    for (name, agent_name) in [
        ("explore.md", "varde-explorer"),
        ("executor.md", "varde-builder"),
        ("build.md", "varde-builder"),
    ] {
        fs::write(
            harness_dir.join(name),
            managed_variant(agent(agent_name), "claude.md", None),
        )
        .unwrap();
    }
    fs::write(harness_dir.join("plan.md"), "unowned plan\n").unwrap();
    fs::write(harness_dir.join("review.md"), "unowned review\n").unwrap();

    let dry_run = sandbox.run("claude", &["--link-mode", "copy", "--dry-run"]);
    assert!(dry_run.status.success(), "{}", stderr(&dry_run));
    let preview = stdout(&dry_run);
    for stale in ["explore.md", "executor.md", "build.md"] {
        assert!(
            preview.contains(&format!(
                "would remove {}",
                harness_dir.join(stale).display()
            )),
            "{preview}"
        );
        assert!(harness_dir.join(stale).exists(), "dry run removed {stale}");
    }
    assert_eq!(
        fs::read_to_string(harness_dir.join("plan.md")).unwrap(),
        "unowned plan\n"
    );
    assert_eq!(
        fs::read_to_string(harness_dir.join("review.md")).unwrap(),
        "unowned review\n"
    );

    let output = sandbox.run("claude", &["--link-mode", "copy"]);
    assert!(output.status.success(), "{}", stderr(&output));
    for stale in ["explore.md", "executor.md", "build.md"] {
        assert!(!harness_dir.join(stale).exists(), "kept {stale}");
    }
    assert_eq!(
        fs::read_to_string(harness_dir.join("plan.md")).unwrap(),
        "unowned plan\n"
    );
    assert_eq!(
        fs::read_to_string(harness_dir.join("review.md")).unwrap(),
        "unowned review\n"
    );
}

#[cfg(unix)]
#[test]
fn reports_install_link_preserve_and_remove_in_that_order() {
    let sandbox = Sandbox::new();
    let harness_dir = sandbox.harness_agents("claude");
    fs::create_dir_all(&harness_dir).unwrap();
    fs::write(
        harness_dir.join("varde-planner.md"),
        managed_variant(
            agent("varde-planner"),
            "claude.md",
            Some("\"user/model-for-report-order\""),
        ),
    )
    .unwrap();
    fs::write(
        harness_dir.join("varde-reviewer.md"),
        "user-owned reviewer\n",
    )
    .unwrap();
    fs::write(
        harness_dir.join("explore.md"),
        managed_variant(agent("varde-explorer"), "claude.md", None),
    )
    .unwrap();

    let output = sandbox.run("claude", &[]);
    assert!(output.status.success(), "{}", stderr(&output));
    let report = stdout(&output);
    let install = report
        .find(&format!(
            "Installed agent varde-planner -> {}",
            sandbox
                .canonical_agent("claude", "varde-planner", "md")
                .display()
        ))
        .unwrap();
    let link = report
        .find(&format!(
            "Linked harness agent {} -> {}",
            harness_dir.join("varde-planner.md").display(),
            sandbox
                .canonical_agent("claude", "varde-planner", "md")
                .display()
        ))
        .unwrap();
    let preserve_model = report.find("Preserved user model setting model").unwrap();
    let preserve_unowned = report
        .find(&format!(
            "Preserved unowned {}",
            harness_dir.join("varde-reviewer.md").display()
        ))
        .unwrap();
    let remove = report
        .find(&format!(
            "Removed {}",
            harness_dir.join("explore.md").display()
        ))
        .unwrap();

    assert!(install < link, "{report}");
    assert!(link < preserve_model, "{report}");
    assert!(preserve_model < preserve_unowned, "{report}");
    assert!(preserve_unowned < remove, "{report}");
}

#[test]
fn opencode_legacy_files_migrate_then_owned_files_are_removed() {
    let sandbox = Sandbox::new();
    let legacy = sandbox.home.join(".config/opencode/agent");
    fs::create_dir_all(&legacy).unwrap();
    fs::write(
        legacy.join("varde-planner.md"),
        managed_variant(
            agent("varde-planner"),
            "opencode.md",
            Some("\"user/model-from-legacy-name\""),
        ),
    )
    .unwrap();
    fs::write(
        legacy.join("plan.md"),
        managed_variant(
            agent("varde-planner"),
            "opencode.md",
            Some("\"user/model-from-renamed-legacy\""),
        ),
    )
    .unwrap();

    let output = sandbox.run("opencode", &["--link-mode", "copy"]);
    assert!(output.status.success(), "{}", stderr(&output));
    assert_model(
        &sandbox.canonical_agent("opencode", "varde-planner", "md"),
        "model: \"user/model-from-legacy-name\"",
    );
    assert!(!legacy.join("varde-planner.md").exists());
    assert!(!legacy.join("plan.md").exists());
    let destination = sandbox.harness_agents("opencode").join("varde-planner.md");
    assert!(
        fs::symlink_metadata(&destination)
            .unwrap()
            .file_type()
            .is_file()
    );
    assert_eq!(
        fs::read_to_string(destination).unwrap(),
        fs::read_to_string(sandbox.canonical_agent("opencode", "varde-planner", "md")).unwrap()
    );
}

#[cfg(unix)]
#[test]
fn opencode_legacy_symlink_directory_is_neither_read_nor_cleaned() {
    use std::os::unix::fs::symlink;

    let sandbox = Sandbox::new();
    let legacy_target = sandbox._root.path().join("legacy-external");
    fs::create_dir_all(&legacy_target).unwrap();
    let plan = legacy_target.join("plan.md");
    fs::write(
        &plan,
        managed_variant(
            agent("varde-planner"),
            "opencode.md",
            Some("\"user/model-must-not-be-read\""),
        ),
    )
    .unwrap();
    let legacy = sandbox.home.join(".config/opencode/agent");
    fs::create_dir_all(legacy.parent().unwrap()).unwrap();
    symlink(&legacy_target, &legacy).unwrap();

    let output = sandbox.run("opencode", &[]);
    assert!(output.status.success(), "{}", stderr(&output));
    let canonical = sandbox.canonical_agent("opencode", "varde-planner", "md");
    let shipped =
        std::str::from_utf8(variant(agent("varde-planner"), "opencode.md").bytes).unwrap();
    assert_model(
        &canonical,
        shipped
            .lines()
            .find(|line| line.starts_with("model: "))
            .unwrap(),
    );
    assert_eq!(
        fs::read_to_string(&plan).unwrap(),
        managed_variant(
            agent("varde-planner"),
            "opencode.md",
            Some("\"user/model-must-not-be-read\"")
        )
    );
    assert_eq!(fs::read_link(&legacy).unwrap(), legacy_target);
}

#[cfg(unix)]
#[test]
fn pi_agent_directory_override_receives_links() {
    let sandbox = Sandbox::new();
    let pi_agents = sandbox.harness_agents("pi");
    fs::create_dir_all(&pi_agents).unwrap();
    let source = std::str::from_utf8(variant(agent("varde-planner"), "pi.md").bytes).unwrap();
    let mut lines = source.lines().map(str::to_owned).collect::<Vec<_>>();
    let tools = lines
        .iter()
        .position(|line| line.starts_with("tools:"))
        .unwrap();
    lines.insert(tools, "model: \"user/model-from-pi\"".to_owned());
    let mut installed = lines.join("\n");
    installed.push('\n');
    installed.push_str(MARKDOWN_MARKER);
    fs::write(pi_agents.join("varde-planner.md"), installed).unwrap();

    let output = sandbox.run("pi", &[]);
    assert!(output.status.success(), "{}", stderr(&output));

    let destination = pi_agents.join("varde-planner.md");
    let canonical = sandbox.canonical_agent("pi", "varde-planner", "md");
    assert_eq!(fs::read_link(&destination).unwrap(), canonical);
    assert!(
        fs::symlink_metadata(&destination)
            .unwrap()
            .file_type()
            .is_symlink()
    );
    assert_model(
        &sandbox.canonical_agent("pi", "varde-planner", "md"),
        "model: \"user/model-from-pi\"",
    );
    assert!(!sandbox.home.join(".pi/agent/agents").exists());
}
