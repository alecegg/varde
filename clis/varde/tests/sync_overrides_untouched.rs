use std::fs;
use std::path::PathBuf;
use std::process::{Command, Output};

use tempfile::TempDir;

struct Sandbox {
    _root: TempDir,
    home: PathBuf,
    config: PathBuf,
    pi_agent: PathBuf,
    cwd: PathBuf,
    skills: PathBuf,
    agents: PathBuf,
    user_overrides: PathBuf,
}

impl Sandbox {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let home = root.path().join("home");
        let config = root.path().join("config");
        let pi_agent = root.path().join("pi-agent");
        let cwd = root.path().join("repo");
        let skills = root.path().join("canonical/skills");
        let agents = root.path().join("canonical/agents");
        let user_overrides = config.join("code/overrides.toml");

        for path in [
            home.join(".claude"),
            home.join(".codex"),
            home.join(".config/opencode"),
            home.join(".pi"),
            config.clone(),
            pi_agent.clone(),
            cwd.clone(),
            skills.clone(),
            agents.clone(),
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
            user_overrides,
        }
    }

    fn run_sync(&self) -> Output {
        let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
        command
            .args([
                "setup",
                "sync",
                "--skills-dir",
                self.skills.to_str().unwrap(),
                "--agents-dir",
                self.agents.to_str().unwrap(),
            ])
            .current_dir(&self.cwd)
            .env_clear()
            .env("HOME", &self.home)
            .env("VARDE_CONFIG_DIR", &self.config)
            .env("PI_CODING_AGENT_DIR", &self.pi_agent)
            .env("VARDE_CODE_USER_OVERRIDES_FILE", &self.user_overrides)
            .env("VARDE_AGENTS_OPENCODE_VERSION", "1");
        if let Some(path) = std::env::var_os("PATH") {
            command.env("PATH", path);
        }
        command.output().unwrap()
    }
}

#[test]
fn setup_sync_leaves_repo_and_user_overrides_byte_identical() {
    let sandbox = Sandbox::new();
    let repo_overrides = sandbox.cwd.join(".varde-code/overrides.toml");
    fs::create_dir_all(repo_overrides.parent().unwrap()).unwrap();

    let repo_contents = b"[rules]\n\"repo-rule\" = { severity = \"warning\" }\n".to_vec();
    let user_contents = b"[rules]\n\"repo-rule\" = { severity = \"error\" }\n".to_vec();
    fs::write(&repo_overrides, &repo_contents).unwrap();
    fs::create_dir_all(sandbox.user_overrides.parent().unwrap()).unwrap();
    fs::write(&sandbox.user_overrides, &user_contents).unwrap();

    let output = sandbox.run_sync();
    assert!(
        output.status.success(),
        "sync failed:\nstdout: {}\nstderr: {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    assert_eq!(fs::read(repo_overrides).unwrap(), repo_contents);
    assert_eq!(fs::read(sandbox.user_overrides).unwrap(), user_contents);
}
