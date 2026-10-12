//! CLI coverage for the app-level session-notes migration command.

use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use tempfile::TempDir;

struct Fixture {
    _temp: TempDir,
    root: PathBuf,
    agent_memory: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("repo");
        let agent_memory = temp.path().join("agent-memory");
        fs::create_dir_all(&root).unwrap();
        Self {
            _temp: temp,
            root,
            agent_memory,
        }
    }

    fn working(&self, project: &str) -> PathBuf {
        self.agent_memory
            .join("projects")
            .join(project)
            .join("working")
    }

    fn add_legacy_note(&self, project: &str, session: &str) -> PathBuf {
        let note = self
            .working(project)
            .join("handoffs")
            .join(session)
            .join("handoff.md");
        fs::create_dir_all(note.parent().unwrap()).unwrap();
        fs::write(&note, format!("# {session}\n")).unwrap();
        note
    }

    fn varde(&self, args: &[&str], current_working: &Path) -> Output {
        Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(args)
            .current_dir(&self.root)
            .env("VARDE_WORKING_DIR", current_working)
            .env("VARDE_CONFIG_DIR", self.root.join("config"))
            .output()
            .unwrap()
    }
}

#[test]
fn command_help_lists_migration_options() {
    let fixture = Fixture::new();
    let output = fixture.varde(
        &["setup", "migrate-session-notes", "--help"],
        &fixture.working("current"),
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(output.status.success(), "{stdout}");
    for option in ["--dry-run", "--json", "--all-projects", "--include-live"] {
        assert!(stdout.contains(option), "missing {option}:\n{stdout}");
    }
}

#[test]
fn dry_run_uses_current_store_and_all_projects_migrates_each_store() {
    let fixture = Fixture::new();
    let current = fixture.working("current");
    let current_note = fixture.add_legacy_note("current", "one");
    let other_note = fixture.add_legacy_note("other", "two");

    let dry_run = fixture.varde(
        &[
            "setup",
            "migrate-session-notes",
            "--dry-run",
            "--json",
            "--include-live",
        ],
        &current,
    );
    assert!(
        dry_run.status.success(),
        "stdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&dry_run.stdout),
        String::from_utf8_lossy(&dry_run.stderr)
    );
    let report: Value = serde_json::from_slice(&dry_run.stdout).unwrap();
    assert_eq!(report["moved"].as_array().unwrap().len(), 1, "{report}");
    assert!(current_note.exists(), "dry-run moved the current note");
    assert!(other_note.exists(), "default scope touched another project");

    let applied = fixture.varde(
        &[
            "setup",
            "migrate-session-notes",
            "--all-projects",
            "--json",
            "--include-live",
        ],
        &current,
    );
    assert!(
        applied.status.success(),
        "stdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&applied.stdout),
        String::from_utf8_lossy(&applied.stderr)
    );
    let report: Value = serde_json::from_slice(&applied.stdout).unwrap();
    assert_eq!(report["moved"].as_array().unwrap().len(), 2, "{report}");
    assert!(
        fixture
            .working("current")
            .join("session-notes/one/notes.md")
            .exists()
    );
    assert!(
        fixture
            .working("other")
            .join("session-notes/two/notes.md")
            .exists()
    );
    assert!(!current_note.exists());
    assert!(!other_note.exists());
}
