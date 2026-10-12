use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use tempfile::TempDir;
use varde::sync::embedded::{Agent, AgentVariant, agents, skills};

const HARNESS_VARIANTS: &[(&str, &str)] = &[
    ("claude", "claude.md"),
    ("codex", "codex.toml"),
    ("opencode", "opencode.md"),
    ("pi", "pi.md"),
];
const MARKDOWN_MARKER: &[u8] = b"\n<!-- varde-managed-agent -->\n";
const TOML_MARKER: &[u8] = b"\n# varde-managed-agent\n";

struct Sandbox {
    _root: TempDir,
    home: PathBuf,
    config: PathBuf,
    pi_agent: PathBuf,
    cwd: PathBuf,
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
        let skills = root.path().join("canonical/skills");
        let agents = root.path().join("canonical/agents");

        for path in [
            home.join(".claude"),
            home.join(".codex"),
            home.join(".config/opencode"),
            home.join(".pi"),
            config.clone(),
            pi_agent.clone(),
            cwd.clone(),
        ] {
            fs::create_dir_all(&path).unwrap();
            if path.starts_with(&home) {
                fs::write(path.join("fixture.txt"), b"temporary harness fixture\n").unwrap();
            }
        }

        Self {
            _root: root,
            home,
            config,
            pi_agent,
            cwd,
            skills,
            agents,
        }
    }

    fn run(&self, args: &[&str]) -> Output {
        let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
        command
            .args(args)
            .current_dir(&self.cwd)
            .env_clear()
            .env("HOME", &self.home)
            .env("VARDE_CONFIG_DIR", &self.config)
            .env("PI_CODING_AGENT_DIR", &self.pi_agent)
            .env("VARDE_AGENTS_OPENCODE_VERSION", "1");
        if let Some(path) = std::env::var_os("PATH") {
            command.env("PATH", path);
        }
        command.output().unwrap()
    }

    fn run_with_targets(&self, options: &[&str]) -> Output {
        let skills = self.skills.to_str().unwrap();
        let agents = self.agents.to_str().unwrap();
        let mut args = vec![
            "setup",
            "sync",
            "--skills-dir",
            skills,
            "--agents-dir",
            agents,
        ];
        args.extend_from_slice(options);
        self.run(&args)
    }

    fn harness_skills(&self, harness: &str) -> PathBuf {
        match harness {
            "claude" => self.home.join(".claude/skills"),
            "codex" => self.home.join(".codex/skills"),
            "opencode" => self.home.join(".config/opencode/skills"),
            "pi" => self.home.join(".agents/skills"),
            _ => panic!("unknown harness {harness}"),
        }
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
}

#[derive(Debug, PartialEq, Eq)]
struct SnapshotEntry {
    relative_path: PathBuf,
    kind: SnapshotKind,
}

#[derive(Debug, PartialEq, Eq)]
enum SnapshotKind {
    Directory,
    File(Vec<u8>),
    Symlink(PathBuf),
}

fn snapshot_tree(root: &Path) -> Vec<SnapshotEntry> {
    fn visit(root: &Path, current: &Path, entries: &mut Vec<SnapshotEntry>) {
        for entry in fs::read_dir(current).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            let file_type = fs::symlink_metadata(&path).unwrap().file_type();
            let kind = if file_type.is_symlink() {
                SnapshotKind::Symlink(fs::read_link(&path).unwrap())
            } else if file_type.is_dir() {
                SnapshotKind::Directory
            } else {
                SnapshotKind::File(fs::read(&path).unwrap())
            };
            entries.push(SnapshotEntry {
                relative_path: path.strip_prefix(root).unwrap().to_path_buf(),
                kind,
            });
            if file_type.is_dir() {
                visit(root, &path, entries);
            }
        }
    }

    let mut entries = Vec::new();
    visit(root, root, &mut entries);
    entries.sort_by(|left, right| left.relative_path.cmp(&right.relative_path));
    entries
}

fn names(directory: &Path) -> Vec<String> {
    let mut names = fs::read_dir(directory)
        .unwrap()
        .map(|entry| entry.unwrap().file_name().into_string().unwrap())
        .collect::<Vec<_>>();
    names.sort();
    names
}

fn assert_real_directory(path: &Path) {
    let file_type = fs::symlink_metadata(path).unwrap().file_type();
    assert!(
        file_type.is_dir(),
        "{} is not a real directory",
        path.display()
    );
    assert!(!file_type.is_symlink(), "{} is a symlink", path.display());
}

fn assert_real_file(path: &Path) {
    let file_type = fs::symlink_metadata(path).unwrap().file_type();
    assert!(file_type.is_file(), "{} is not a real file", path.display());
    assert!(!file_type.is_symlink(), "{} is a symlink", path.display());
}

fn assert_no_symlinks(root: &Path) {
    let file_type = fs::symlink_metadata(root).unwrap().file_type();
    assert!(!file_type.is_symlink(), "{} is a symlink", root.display());
    if file_type.is_dir() {
        for entry in fs::read_dir(root).unwrap() {
            assert_no_symlinks(&entry.unwrap().path());
        }
    }
}

fn assert_symlink_to(path: &Path, target: &Path) {
    let file_type = fs::symlink_metadata(path).unwrap().file_type();
    assert!(
        file_type.is_symlink(),
        "{} is not a symlink",
        path.display()
    );
    assert_eq!(fs::read_link(path).unwrap(), target, "{}", path.display());
}

fn variant<'a>(agent: &'a Agent, file_name: &str) -> &'a AgentVariant {
    agent
        .variants
        .iter()
        .find(|variant| variant.file_name == file_name)
        .unwrap_or_else(|| panic!("{} has no embedded {file_name}", agent.name))
}

fn installed_agent_name(agent: &Agent, variant: &AgentVariant) -> String {
    let extension = variant.file_name.rsplit_once('.').unwrap().1;
    format!("{}.{}", agent.name, extension)
}

fn agent_marker(file_name: &str) -> &'static [u8] {
    if file_name.ends_with(".toml") {
        TOML_MARKER
    } else {
        MARKDOWN_MARKER
    }
}

#[cfg(unix)]
#[test]
fn installed_binary_copies_embedded_content_and_links_detected_harnesses() {
    let sandbox = Sandbox::new();
    assert!(!sandbox.cwd.join(".git").exists());

    let output = sandbox.run_with_targets(&[]);
    assert!(output.status.success(), "{}", stderr(&output));

    let expected_skills = skills()
        .iter()
        .map(|skill| skill.name.to_owned())
        .collect::<Vec<_>>();
    assert_eq!(names(&sandbox.skills), expected_skills);
    for skill in skills() {
        let canonical = sandbox.skills.join(skill.name);
        assert_real_directory(&canonical);
        for file in skill.files {
            let path = canonical.join(file.relative_path);
            assert_real_file(&path);
            assert_eq!(fs::read(&path).unwrap(), file.bytes, "{}", path.display());
        }
        assert_no_symlinks(&canonical);

        for (harness, _) in HARNESS_VARIANTS {
            let entry = sandbox.harness_skills(harness).join(skill.name);
            assert_symlink_to(&entry, &canonical);
        }
    }

    assert_eq!(
        names(&sandbox.agents),
        HARNESS_VARIANTS
            .iter()
            .map(|(harness, _)| (*harness).to_owned())
            .collect::<Vec<_>>()
    );
    for (harness, file_name) in HARNESS_VARIANTS {
        let canonical_dir = sandbox.agents.join(harness);
        assert_real_directory(&canonical_dir);
        let mut expected = agents()
            .iter()
            .map(|agent| installed_agent_name(agent, variant(agent, file_name)))
            .collect::<Vec<_>>();
        expected.sort();
        assert_eq!(names(&canonical_dir), expected, "{harness} agent count");

        for agent in agents() {
            let variant = variant(agent, file_name);
            let name = installed_agent_name(agent, variant);
            let canonical = canonical_dir.join(&name);
            assert_real_file(&canonical);
            let contents = fs::read(&canonical).unwrap();
            let embedded = std::str::from_utf8(variant.bytes).unwrap().trim();
            let installed = std::str::from_utf8(&contents).unwrap();
            assert!(installed.contains(embedded), "{}", canonical.display());
            assert!(
                contents.ends_with(agent_marker(file_name)),
                "{}",
                canonical.display()
            );
            assert_symlink_to(&sandbox.harness_agents(harness).join(name), &canonical);
        }
    }
    assert_no_symlinks(&sandbox.agents);
}

#[test]
fn missing_targets_leave_the_temp_home_and_config_unchanged_and_recommend_the_layout() {
    let sandbox = Sandbox::new();
    let home_before = snapshot_tree(&sandbox.home);
    let config_before = snapshot_tree(&sandbox.config);

    let output = sandbox.run(&["setup", "sync"]);

    assert!(!output.status.success(), "sync unexpectedly succeeded");
    let message = stderr(&output);
    assert!(message.contains("canonical central copy"), "{message}");
    assert!(
        message.contains("symlink it into each detected harness"),
        "{message}"
    );
    assert_eq!(snapshot_tree(&sandbox.home), home_before);
    assert_eq!(snapshot_tree(&sandbox.config), config_before);
}

#[cfg(unix)]
#[test]
fn saved_copy_mode_refreshes_all_harness_entries_and_can_switch_back_to_symlinks() {
    let sandbox = Sandbox::new();
    let first = sandbox.run_with_targets(&["--link-mode", "copy"]);
    assert!(first.status.success(), "{}", stderr(&first));

    let stale_skill = sandbox
        .harness_skills("claude")
        .join("varde-change/SKILL.md");
    fs::write(&stale_skill, b"stale harness copy\n").unwrap();
    let stale_file = stale_skill.parent().unwrap().join("stale.txt");
    fs::write(&stale_file, b"remove on refresh\n").unwrap();

    let stale_agent = sandbox.harness_agents("claude").join("varde-planner.md");
    let mut stale_agent_contents = fs::read(&stale_agent).unwrap();
    stale_agent_contents.extend_from_slice(b"stale harness copy\n");
    fs::write(&stale_agent, stale_agent_contents).unwrap();

    let second = sandbox.run(&["setup", "sync"]);
    assert!(second.status.success(), "{}", stderr(&second));
    assert_eq!(
        fs::read(&stale_skill).unwrap(),
        fs::read(sandbox.skills.join("varde-change/SKILL.md")).unwrap()
    );
    assert!(!stale_file.exists());
    assert_eq!(
        fs::read(&stale_agent).unwrap(),
        fs::read(sandbox.agents.join("claude/varde-planner.md")).unwrap()
    );

    for (harness, file_name) in HARNESS_VARIANTS {
        for skill in skills() {
            let canonical = sandbox.skills.join(skill.name);
            let entry = sandbox.harness_skills(harness).join(skill.name);
            assert_real_directory(&entry);
            assert_eq!(
                fs::read(entry.join(".varde-managed-skill")).unwrap(),
                b"varde-managed-skill\n"
            );
            for file in skill.files {
                assert_eq!(
                    fs::read(entry.join(file.relative_path)).unwrap(),
                    fs::read(canonical.join(file.relative_path)).unwrap()
                );
            }
        }
        for agent in agents() {
            let variant = variant(agent, file_name);
            let name = installed_agent_name(agent, variant);
            let canonical = sandbox.agents.join(harness).join(&name);
            let entry = sandbox.harness_agents(harness).join(name);
            assert_real_file(&entry);
            let contents = fs::read(&entry).unwrap();
            assert!(
                contents.ends_with(agent_marker(file_name)),
                "{}",
                entry.display()
            );
            assert_eq!(contents, fs::read(canonical).unwrap());
        }
    }

    let third = sandbox.run(&["setup", "sync", "--link-mode", "symlink"]);
    assert!(third.status.success(), "{}", stderr(&third));
    for (harness, file_name) in HARNESS_VARIANTS {
        for skill in skills() {
            assert_symlink_to(
                &sandbox.harness_skills(harness).join(skill.name),
                &sandbox.skills.join(skill.name),
            );
        }
        for agent in agents() {
            let variant = variant(agent, file_name);
            let name = installed_agent_name(agent, variant);
            assert_symlink_to(
                &sandbox.harness_agents(harness).join(&name),
                &sandbox.agents.join(harness).join(name),
            );
        }
    }
}

#[cfg(unix)]
#[test]
fn sync_preserves_user_changed_models_for_claude_and_codex_agents() {
    let sandbox = Sandbox::new();
    let first = sandbox.run_with_targets(&[]);
    assert!(first.status.success(), "{}", stderr(&first));

    let claude = sandbox.harness_agents("claude").join("varde-planner.md");
    let codex = sandbox.harness_agents("codex").join("varde-planner.toml");
    let claude_contents = fs::read_to_string(&claude).unwrap();
    let codex_contents = fs::read_to_string(&codex).unwrap();
    let claude_choice = "user/claude-model-choice";
    let codex_choice = "user/codex-model-choice";
    fs::write(
        &claude,
        replace_model_line(&claude_contents, "model: ", claude_choice),
    )
    .unwrap();
    fs::write(
        &codex,
        replace_model_line(&codex_contents, "model = ", codex_choice),
    )
    .unwrap();

    let second = sandbox.run(&["setup", "sync"]);
    assert!(second.status.success(), "{}", stderr(&second));
    assert!(
        fs::read_to_string(&claude)
            .unwrap()
            .contains(&format!("model: \"{claude_choice}\""))
    );
    assert!(
        fs::read_to_string(&codex)
            .unwrap()
            .contains(&format!("model = \"{codex_choice}\""))
    );
}

fn replace_model_line(contents: &str, prefix: &str, model: &str) -> String {
    let line = contents
        .lines()
        .find(|line| line.starts_with(prefix))
        .unwrap_or_else(|| panic!("no model line with prefix {prefix:?}"));
    contents.replacen(line, &format!("{prefix}\"{model}\""), 1)
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}
