use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use tempfile::TempDir;
use varde::sync::embedded::{Agent, AgentVariant, agents};

#[cfg(unix)]
use std::os::unix::fs::{PermissionsExt, symlink};

const AGENT_MARKER_MD: &[u8] = b"\n<!-- varde-managed-agent -->\n";
const AGENT_MARKER_TOML: &[u8] = b"\n# varde-managed-agent\n";
const PI_TOOLS: &[&str] = &["read", "bash", "edit", "write", "grep", "find", "ls"];
const AGENTS_LINE: &str = "Read the repository's AGENTS.md, if present, before working.";

struct Sandbox {
    root: TempDir,
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
        for path in [&home, &config, &pi_agent, &cwd, &bin] {
            fs::create_dir_all(path).unwrap();
        }
        Self {
            root,
            home,
            config,
            pi_agent,
            cwd,
            bin,
            skills,
            agents,
        }
    }

    fn run(&self, options: &[&str], path: Option<&Path>, opencode_version: Option<&str>) -> Output {
        self.run_harnesses("none", options, path, opencode_version)
    }

    fn run_harnesses(
        &self,
        harnesses: &str,
        options: &[&str],
        path: Option<&Path>,
        opencode_version: Option<&str>,
    ) -> Output {
        let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
        command
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
            .env("PATH", path.unwrap_or(&self.bin));
        if let Some(version) = opencode_version {
            command.env("VARDE_AGENTS_OPENCODE_VERSION", version);
        }
        command.output().unwrap()
    }
}

#[cfg(unix)]
#[test]
fn links_selected_harness_agents_to_the_canonical_files() {
    let sandbox = Sandbox::new();
    let output = sandbox.run_harnesses("claude", &[], None, Some("1"));
    assert!(output.status.success(), "{}", stderr(&output));

    let claude_agents = sandbox.home.join(".claude/agents");
    for agent in agents() {
        let destination = claude_agents.join(format!("{}.md", agent.name));
        let canonical = sandbox
            .agents
            .join("claude")
            .join(format!("{}.md", agent.name));
        assert!(
            fs::symlink_metadata(&destination)
                .unwrap()
                .file_type()
                .is_symlink(),
            "{} is not a symlink",
            destination.display()
        );
        assert_eq!(fs::read_link(&destination).unwrap(), canonical);
    }
    assert!(!sandbox.home.join(".codex/agents").exists());
    assert!(!sandbox.home.join(".config/opencode/agents").exists());
    assert!(!sandbox.pi_agent.join("agents").exists());
}

#[test]
fn copy_mode_rewrites_marked_harness_agent_copies_on_every_sync() {
    let sandbox = Sandbox::new();
    let options = ["--link-mode", "copy"];
    let first = sandbox.run_harnesses("claude", &options, None, Some("1"));
    assert!(first.status.success(), "{}", stderr(&first));

    let destination = sandbox.home.join(".claude/agents/varde-planner.md");
    let canonical = sandbox.agents.join("claude/varde-planner.md");
    assert!(
        fs::symlink_metadata(&destination)
            .unwrap()
            .file_type()
            .is_file()
    );
    let initial = fs::read_to_string(&destination).unwrap();
    assert!(initial.ends_with(std::str::from_utf8(AGENT_MARKER_MD).unwrap()));
    assert_eq!(initial, fs::read_to_string(&canonical).unwrap());

    fs::OpenOptions::new()
        .append(true)
        .open(&destination)
        .unwrap()
        .write_all(b"stale copy edit\n")
        .unwrap();
    let second = sandbox.run_harnesses("claude", &options, None, Some("1"));
    assert!(second.status.success(), "{}", stderr(&second));
    assert!(
        !fs::read_to_string(&destination)
            .unwrap()
            .contains("stale copy edit")
    );
    assert_eq!(
        fs::read_to_string(&destination).unwrap(),
        fs::read_to_string(canonical).unwrap()
    );
}

#[test]
fn preserves_unowned_harness_agent_files() {
    let sandbox = Sandbox::new();
    let directory = sandbox.home.join(".claude/agents");
    fs::create_dir_all(&directory).unwrap();
    let destination = directory.join("varde-planner.md");
    fs::write(&destination, "user-owned agent\n").unwrap();

    let output = sandbox.run_harnesses("claude", &[], None, Some("1"));
    assert!(output.status.success(), "{}", stderr(&output));
    assert!(stdout(&output).contains(&format!("Preserved unowned {}", destination.display())));
    assert_eq!(
        fs::read_to_string(destination).unwrap(),
        "user-owned agent\n"
    );
}

#[cfg(unix)]
#[test]
fn preserves_foreign_harness_symlinks_without_following_them() {
    let sandbox = Sandbox::new();
    let directory = sandbox.home.join(".claude/agents");
    fs::create_dir_all(&directory).unwrap();
    let target = sandbox.root.path().join("outside-harness-agent.md");
    fs::write(&target, "outside user data\n<!-- varde-managed-agent -->\n").unwrap();
    let destination = directory.join("varde-planner.md");
    symlink(&target, &destination).unwrap();

    let output = sandbox.run_harnesses("claude", &[], None, Some("1"));
    assert!(output.status.success(), "{}", stderr(&output));
    assert!(stdout(&output).contains(&format!("Preserved unowned {}", destination.display())));
    assert_eq!(fs::read_link(&destination).unwrap(), target);
    assert_eq!(
        fs::read_to_string(sandbox.root.path().join("outside-harness-agent.md")).unwrap(),
        "outside user data\n<!-- varde-managed-agent -->\n"
    );
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

fn managed_marker(file_name: &str) -> &'static [u8] {
    if file_name.ends_with(".toml") {
        AGENT_MARKER_TOML
    } else {
        AGENT_MARKER_MD
    }
}

#[test]
fn installs_every_embedded_agent_as_a_marked_real_file_for_all_harnesses() {
    let sandbox = Sandbox::new();
    let output = sandbox.run(&[], None, Some("1"));

    assert!(output.status.success(), "{}", stderr(&output));
    for (harness, file_name, extension) in [
        ("claude", "claude.md", "md"),
        ("codex", "codex.toml", "toml"),
        ("opencode", "opencode.md", "md"),
        ("pi", "pi.md", "md"),
    ] {
        let directory = sandbox.agents.join(harness);
        let directory_type = fs::symlink_metadata(&directory).unwrap().file_type();
        assert!(
            directory_type.is_dir(),
            "{} is not a real directory",
            directory.display()
        );
        for agent in agents() {
            let source = variant(agent, file_name);
            let destination = directory.join(format!("{}.{}", agent.name, extension));
            let metadata = fs::symlink_metadata(&destination).unwrap();
            assert!(
                metadata.file_type().is_file(),
                "{} is not a regular file",
                destination.display()
            );
            let contents = fs::read(&destination).unwrap();
            assert!(
                contents.starts_with(source.bytes),
                "{} lost its embedded variant",
                destination.display()
            );
            assert!(
                contents.ends_with(managed_marker(file_name)),
                "{} has no ownership marker",
                destination.display()
            );
            #[cfg(unix)]
            assert_eq!(
                metadata.permissions().mode() & 0o777,
                0o644,
                "{} mode",
                destination.display()
            );
        }
    }
}

#[cfg(unix)]
#[test]
fn opencode_adapter_uses_the_override_and_version_command_rules() {
    fn selected_variant(report: Option<&str>, override_version: Option<&str>, expected_v2: bool) {
        let sandbox = Sandbox::new();
        if let Some(report) = report {
            let binary = sandbox.bin.join("opencode");
            fs::write(
                &binary,
                format!("#!/bin/sh\nprintf '%s\\n' '{report}'\nprintf '%s\\n' '2.0.1' >&2\n"),
            )
            .unwrap();
            fs::set_permissions(&binary, fs::Permissions::from_mode(0o755)).unwrap();
        }
        let output = sandbox.run(&[], Some(&sandbox.bin), override_version);
        assert!(output.status.success(), "{}", stderr(&output));

        let installed =
            fs::read_to_string(sandbox.agents.join("opencode/varde-planner.md")).unwrap();
        assert_eq!(
            installed
                .lines()
                .any(|line| line.starts_with("permissions: ")),
            expected_v2,
            "report={report:?}, override={override_version:?}: {}",
            stdout(&output)
        );
    }

    selected_variant(None, None, false);
    selected_variant(Some("1.4.2"), None, false);
    selected_variant(Some("2.0.1"), None, true);
    selected_variant(Some("garbage"), None, false);
    selected_variant(Some("1.4.2"), Some("2.0.0"), true);
    selected_variant(Some("2.0.1"), Some("1.0.0"), false);
    selected_variant(Some("2.0.1"), Some("garbage"), false);
}

fn replace_frontmatter_model(contents: &str, model: &str) -> String {
    let mut lines = contents.lines().map(str::to_owned).collect::<Vec<_>>();
    let end = lines
        .iter()
        .enumerate()
        .skip(1)
        .find_map(|(index, line)| (line == "---").then_some(index))
        .expect("frontmatter must end");
    let model_line = lines[1..end]
        .iter()
        .position(|line| line.starts_with("model:"))
        .map(|index| index + 1)
        .expect("Claude agent must ship a model");
    lines[model_line] = format!("model: \"{model}\"");
    format!("{}\n", lines.join("\n"))
}

#[test]
fn preserves_a_user_model_on_sync_and_reports_it_in_dry_run() {
    let sandbox = Sandbox::new();
    let first = sandbox.run(&[], None, Some("1"));
    assert!(first.status.success(), "{}", stderr(&first));

    let destination = sandbox.agents.join("claude/varde-planner.md");
    let user_content = replace_frontmatter_model(
        &fs::read_to_string(&destination).unwrap(),
        "user/selected-model",
    );
    fs::write(&destination, &user_content).unwrap();

    let dry_run = sandbox.run(&["--dry-run"], None, Some("1"));
    assert!(dry_run.status.success(), "{}", stderr(&dry_run));
    let preview = stdout(&dry_run);
    assert!(
        preview.contains(&format!(
            "would replace agent varde-planner -> {}",
            destination.display()
        )),
        "{preview}"
    );
    assert!(
        preview.contains(&format!(
            "would preserve user model setting model in {}",
            destination.display()
        )),
        "{preview}"
    );
    assert_eq!(fs::read_to_string(&destination).unwrap(), user_content);

    let second = sandbox.run(&[], None, Some("1"));
    assert!(second.status.success(), "{}", stderr(&second));
    assert!(
        stdout(&second).contains(&format!(
            "Preserved user model setting model in {}",
            destination.display()
        )),
        "{}",
        stdout(&second)
    );
    assert!(
        fs::read_to_string(destination)
            .unwrap()
            .contains("model: \"user/selected-model\"")
    );
}

#[test]
fn preserves_unowned_canonical_files_and_symlinks() {
    let sandbox = Sandbox::new();
    let claude = sandbox.agents.join("claude");
    fs::create_dir_all(&claude).unwrap();
    let unowned = claude.join("varde-planner.md");
    fs::write(&unowned, "user-owned agent\n").unwrap();

    #[cfg(unix)]
    let (link, link_target) = {
        let target = sandbox.root.path().join("outside-agent.md");
        fs::write(&target, "<!-- varde-managed-agent -->\n").unwrap();
        let link = claude.join("varde-reviewer.md");
        symlink(&target, &link).unwrap();
        (link, target)
    };

    let output = sandbox.run(&[], None, Some("1"));
    assert!(output.status.success(), "{}", stderr(&output));
    let report = stdout(&output);
    assert!(
        report.contains(&format!("Preserved unowned {}", unowned.display())),
        "{report}"
    );
    assert_eq!(fs::read_to_string(&unowned).unwrap(), "user-owned agent\n");
    #[cfg(unix)]
    {
        assert!(
            report.contains(&format!("Preserved unowned {}", link.display())),
            "{report}"
        );
        assert_eq!(fs::read_link(&link).unwrap(), link_target);
    }
}

fn parse_pi_agent(contents: &str) -> (HashMap<String, String>, String) {
    let contents = contents.strip_prefix("---\n").expect("Pi frontmatter");
    let (frontmatter, body) = contents.split_once("\n---\n").expect("Pi frontmatter end");
    let mut fields = HashMap::new();
    for line in frontmatter.lines() {
        let (key, value) = line.split_once(": ").expect("frontmatter field");
        let value = if value.starts_with('"') {
            serde_json::from_str(value).expect("quoted frontmatter value")
        } else {
            value.to_owned()
        };
        assert!(
            fields.insert(key.to_owned(), value).is_none(),
            "duplicate {key}"
        );
    }
    (fields, body.to_owned())
}

#[test]
fn installed_pi_agents_satisfy_the_generated_agent_contract() {
    let sandbox = Sandbox::new();
    let output = sandbox.run(&[], None, Some("1"));
    assert!(output.status.success(), "{}", stderr(&output));

    let mut all_tools: HashMap<String, Vec<String>> = HashMap::new();
    for agent in agents() {
        let destination = sandbox.agents.join(format!("pi/{}.md", agent.name));
        let contents = fs::read_to_string(&destination).unwrap();
        let (fields, body) = parse_pi_agent(&contents);
        assert!(
            !fields.get("description").is_none_or(String::is_empty),
            "{}",
            agent.name
        );
        let tools = fields["tools"]
            .split(',')
            .map(str::trim)
            .map(str::to_owned)
            .collect::<Vec<_>>();
        let unique_tools = tools.iter().map(String::as_str).collect::<HashSet<_>>();
        assert_eq!(
            tools.len(),
            unique_tools.len(),
            "{} duplicate tools",
            agent.name
        );
        assert!(
            tools.iter().all(|tool| PI_TOOLS.contains(&tool.as_str())),
            "{}: {tools:?}",
            agent.name
        );
        assert!(
            tools.iter().any(|tool| tool == "read") && tools.iter().any(|tool| tool == "bash"),
            "{}: {tools:?}",
            agent.name
        );
        assert!(!fields.contains_key("model"), "{} has a model", agent.name);
        assert_eq!(
            fields.get("prompt_mode").map(String::as_str),
            Some("replace")
        );
        assert_eq!(fields.get("skills").map(String::as_str), Some("true"));
        assert!(
            !fields.contains_key("name"),
            "filename must name {}",
            agent.name
        );
        if ["varde-builder", "varde-planner", "varde-reviewer"].contains(&agent.name) {
            assert_eq!(
                fields.get("allowed_subagents").map(String::as_str),
                Some("varde-explorer")
            );
        } else {
            assert!(!fields.contains_key("allowed_subagents"), "{}", agent.name);
        }
        assert!(
            fields.keys().all(|key| [
                "description",
                "tools",
                "model",
                "prompt_mode",
                "skills",
                "allowed_subagents"
            ]
            .contains(&key.as_str())),
            "{} has fields {:?}",
            agent.name,
            fields.keys().collect::<Vec<_>>()
        );
        assert_eq!(body.matches(AGENTS_LINE).count(), 1, "{}", agent.name);

        let claude = std::str::from_utf8(variant(agent, "claude.md").bytes).unwrap();
        let claude_body = claude
            .split_once("-->\n")
            .expect("Claude generated marker")
            .1
            .trim();
        assert!(
            body.contains(claude_body),
            "{} omits the shared instructions",
            agent.name
        );
        all_tools.insert(agent.name.to_owned(), tools);
    }

    assert_eq!(
        all_tools["varde-explorer"]
            .iter()
            .map(String::as_str)
            .collect::<Vec<_>>(),
        vec!["read", "bash", "grep", "find", "ls"]
    );
    assert!(
        !all_tools["varde-explorer"]
            .iter()
            .any(|tool| ["edit", "write"].contains(&tool.as_str()))
    );
    assert!(
        all_tools["varde-builder"]
            .iter()
            .any(|tool| tool == "write")
    );
    assert!(all_tools["varde-builder"].iter().any(|tool| tool == "edit"));
    assert!(
        !all_tools["varde-reviewer"]
            .iter()
            .any(|tool| tool == "edit")
    );
}

#[test]
fn dry_run_creates_no_canonical_targets() {
    let sandbox = Sandbox::new();
    let output = sandbox.run(&["--dry-run"], None, Some("1"));
    assert!(output.status.success(), "{}", stderr(&output));
    assert!(stdout(&output).contains("would install agent"));
    assert!(!sandbox.agents.exists());
    assert!(!sandbox.skills.exists());
    assert!(!sandbox.config.join("config.toml").exists());
}

#[cfg(unix)]
#[test]
fn failed_staged_write_leaves_the_previous_agent_file_intact() {
    let sandbox = Sandbox::new();
    let first = sandbox.run(&[], None, Some("1"));
    assert!(first.status.success(), "{}", stderr(&first));

    let first_agent = &agents()[0];
    let destination = sandbox
        .agents
        .join("claude")
        .join(format!("{}.md", first_agent.name));
    let previous = fs::read(&destination).unwrap();
    let directory = destination.parent().unwrap();
    let original_mode = fs::metadata(directory).unwrap().permissions().mode();
    fs::set_permissions(
        directory,
        fs::Permissions::from_mode(original_mode & !0o222),
    )
    .unwrap();

    let probe = directory.join("write-probe");
    let denied = fs::write(&probe, b"probe").is_err();
    if !denied {
        fs::remove_file(probe).unwrap();
        fs::set_permissions(directory, fs::Permissions::from_mode(original_mode)).unwrap();
        eprintln!("skipped read-only directory failure check: process can write through mode 0555");
        return;
    }

    let failed = sandbox.run(&[], None, Some("1"));
    fs::set_permissions(directory, fs::Permissions::from_mode(original_mode)).unwrap();
    assert!(!failed.status.success(), "{}", stdout(&failed));
    assert_eq!(fs::read(destination).unwrap(), previous);
}
