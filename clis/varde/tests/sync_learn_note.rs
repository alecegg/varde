use std::fs;
use std::path::Path;
use std::process::{Command, Output};

use tempfile::TempDir;

struct Fixture {
    root: TempDir,
    config: std::path::PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let config = root.path().join("config");
        fs::create_dir_all(&config).unwrap();
        Self { root, config }
    }

    fn install(&self, target: &Path, learn: bool) -> Output {
        let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
        command
            .args(["setup", "instructions", "install", "--target"])
            .arg(target)
            .current_dir(self.root.path())
            .env("VARDE_CONFIG_DIR", &self.config);
        if learn {
            command.arg("--learn");
        }
        command.output().unwrap()
    }

    fn sync(&self, target: &Path, skill: &str) -> Output {
        Command::new(env!("CARGO_BIN_EXE_varde"))
            .args([
                "setup",
                "sync",
                "--skills-dir",
                self.root.path().join("skills").to_str().unwrap(),
                "--agents-dir",
                self.root.path().join("agents").to_str().unwrap(),
                "--harnesses",
                "none",
                "--skills",
                skill,
                "--instructions-target",
            ])
            .arg(target)
            .current_dir(self.root.path())
            .env("VARDE_CONFIG_DIR", &self.config)
            .output()
            .unwrap()
    }
}

#[test]
fn learn_note_is_included_only_when_requested_and_removed_on_reinstall() {
    let fixture = Fixture::new();
    let target = fixture.root.path().join("AGENTS.md");

    let output = fixture.install(&target, true);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let installed = fs::read_to_string(&target).unwrap();
    assert!(installed.contains("<!-- varde-learn:start -->"));
    assert!(installed.contains("varde learn friction add"));
    assert!(installed.contains("<!-- varde-learn:end -->"));

    let output = fixture.install(&target, false);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let reinstalled = fs::read_to_string(&target).unwrap();
    assert!(!reinstalled.contains("varde-learn:"));
    assert!(!reinstalled.contains("varde learn friction add"));
}

#[test]
fn sync_tracks_learn_skill_selection_and_removes_the_note() {
    let fixture = Fixture::new();
    let target = fixture.root.path().join("AGENTS.md");

    for (skill, expected) in [("varde-code", false), ("varde-learn", true), ("all", true)] {
        let output = fixture.sync(&target, skill);
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let text = fs::read_to_string(&target).unwrap();
        assert_eq!(
            text.contains("<!-- varde-learn:start -->"),
            expected,
            "{skill}"
        );
    }

    let output = fixture.sync(&target, "varde-code");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = fs::read_to_string(&target).unwrap();
    assert!(!text.contains("varde-learn:"));
}

#[test]
fn sync_instruction_sections_follow_the_resolved_skill_features() {
    let fixture = Fixture::new();
    let target = fixture.root.path().join("AGENTS.md");

    for (skill, orchestration) in [
        ("varde-toz", false),
        ("varde-learn", false),
        ("varde-scan", false),
        ("varde-change", true),
    ] {
        let output = fixture.sync(&target, skill);
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let text = fs::read_to_string(&target).unwrap();
        assert_eq!(
            text.contains("the session manager"),
            orchestration,
            "{skill}"
        );
    }

    let output = fixture.sync(&target, "varde-toz");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = fs::read_to_string(&target).unwrap();
    assert!(text.contains("## varde-toz (tool-output-zone)"));
    assert!(!text.contains("the session manager"));
}
