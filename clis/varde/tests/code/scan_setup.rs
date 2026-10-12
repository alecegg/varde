use std::path::Path;
use std::process::{Command, Output};

use serde_json::{Value, json};
use tempfile::TempDir;

fn run_setup(repo: &Path, home: &Path, preset: &str, scope: &str, force_flag: bool) -> Output {
    let input = json!({
        "repoRoot": repo.display().to_string(),
        "preset": preset,
        "scope": scope,
    })
    .to_string();
    let user_overrides = home.join("user-overrides.toml");
    let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
    command
        .args(["scan", "setup", "--json", &input])
        .env("HOME", home)
        .env("VARDE_CODE_USER_OVERRIDES_FILE", user_overrides);
    if force_flag {
        command.arg("--force");
    }
    command.output().expect("scan setup runs")
}

fn run_setup_user_flag(repo: &Path, home: &Path, preset: &str) -> Output {
    let input = json!({ "repoRoot": repo.display().to_string(), "preset": preset }).to_string();
    Command::new(env!("CARGO_BIN_EXE_varde"))
        .args(["scan", "setup", "--json", &input, "--user"])
        .env("HOME", home)
        .env(
            "VARDE_CODE_USER_OVERRIDES_FILE",
            home.join("user-overrides.toml"),
        )
        .output()
        .expect("scan setup runs")
}

fn data(output: &Output) -> Value {
    assert!(
        output.status.success(),
        "stdout: {}\nstderr: {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let envelope: Value = serde_json::from_slice(&output.stdout).expect("JSON envelope");
    envelope["data"].clone()
}

fn repo_with_languages() -> TempDir {
    let repo = tempfile::tempdir().expect("repo tempdir");
    std::fs::write(repo.path().join("main.rs"), "fn main() {}\n").expect("Rust source");
    std::fs::write(repo.path().join("app.ts"), "export const answer = 42;\n")
        .expect("TypeScript source");
    repo
}

#[test]
fn minimal_writes_overrides_and_lists_applicable_effective_rules() {
    let repo = repo_with_languages();
    let home = tempfile::tempdir().expect("home tempdir");

    let output = run_setup(repo.path(), home.path(), "minimal", "repo", false);
    let result = data(&output);

    let overrides_path = repo.path().join(".varde-code/overrides.toml");
    let written_path = overrides_path.to_string_lossy().into_owned();
    assert_eq!(result["written"].as_str(), Some(written_path.as_str()));
    assert_eq!(result["detectedLanguages"], json!(["rust", "typescript"]));
    let overrides = std::fs::read_to_string(overrides_path).expect("overrides written");
    assert_eq!(overrides.matches("[rules.").count(), 9);
    assert_eq!(overrides.matches("severity = \"off\"").count(), 9);
    assert!(!overrides.contains("[rules.dependency-boundary]"));

    let rules = result["effectiveRules"]
        .as_array()
        .expect("effective rules");
    assert!(rules.iter().any(|rule| rule["id"] == "eval-usage"));
    assert!(!rules.iter().any(|rule| rule["id"] == "empty-except-block"));
    let boundary = rules
        .iter()
        .find(|rule| rule["id"] == "dependency-boundary")
        .expect("SQL rule remains applicable");
    assert_eq!(boundary["severity"], "error");
}

#[test]
fn existing_overrides_require_force_and_force_replaces_them() {
    let repo = repo_with_languages();
    let home = tempfile::tempdir().expect("home tempdir");
    let overrides_path = repo.path().join(".varde-code/overrides.toml");
    std::fs::create_dir_all(overrides_path.parent().unwrap()).expect("override directory");
    std::fs::write(&overrides_path, "preserve this file\n").expect("existing overrides");

    let refused = run_setup(repo.path(), home.path(), "minimal", "repo", false);
    assert!(!refused.status.success());
    assert_eq!(
        std::fs::read_to_string(&overrides_path).expect("existing file remains"),
        "preserve this file\n"
    );

    let forced = run_setup(repo.path(), home.path(), "minimal", "repo", true);
    data(&forced);
    let replaced = std::fs::read_to_string(overrides_path).expect("forced write");
    assert_eq!(replaced.matches("[rules.").count(), 9);
    assert!(!replaced.contains("preserve this file"));
}

#[test]
fn failed_forced_replace_preserves_existing_target() {
    let repo = repo_with_languages();
    let home = tempfile::tempdir().expect("home tempdir");
    let overrides_path = repo.path().join(".varde-code/overrides.toml");
    std::fs::create_dir_all(&overrides_path).expect("block replacement with directory");
    let sentinel = overrides_path.join("preserve.txt");
    std::fs::write(&sentinel, "preserve this file\n").expect("existing data");

    let failed = run_setup(repo.path(), home.path(), "minimal", "repo", true);

    assert!(!failed.status.success());
    assert_eq!(
        std::fs::read_to_string(sentinel).expect("existing data remains"),
        "preserve this file\n"
    );
    assert_eq!(
        std::fs::read_dir(overrides_path)
            .expect("target remains")
            .count(),
        1,
        "failed replacement cleans up its temporary file"
    );
}

#[test]
fn balanced_uses_defaults_without_writing_an_overrides_file() {
    let repo = repo_with_languages();
    let home = tempfile::tempdir().expect("home tempdir");
    let overrides_path = repo.path().join(".varde-code/overrides.toml");
    std::fs::create_dir_all(overrides_path.parent().unwrap()).expect("override directory");
    std::fs::write(&overrides_path, "[rules.eval-usage]\nseverity = \"off\"\n")
        .expect("existing override");

    let output = run_setup(repo.path(), home.path(), "balanced", "repo", false);
    let result = data(&output);

    assert!(result["written"].is_null());
    assert!(
        result["message"]
            .as_str()
            .unwrap()
            .contains("existing overrides unchanged")
    );
    assert_eq!(
        std::fs::read_to_string(&overrides_path).expect("existing override remains"),
        "[rules.eval-usage]\nseverity = \"off\"\n"
    );
    assert_eq!(
        result["effectiveRules"]
            .as_array()
            .unwrap()
            .iter()
            .find(|rule| rule["id"] == "eval-usage")
            .unwrap()["severity"],
        "off"
    );
}

#[test]
fn user_scope_writes_the_user_overrides_file() {
    let repo = repo_with_languages();
    let home = tempfile::tempdir().expect("home tempdir");

    let output = run_setup(repo.path(), home.path(), "strict", "user", false);
    let result = data(&output);

    let overrides_path = home.path().join("user-overrides.toml");
    let written_path = overrides_path.to_string_lossy().into_owned();
    assert_eq!(result["written"].as_str(), Some(written_path.as_str()));
    let overrides = std::fs::read_to_string(overrides_path).expect("user overrides written");
    assert_eq!(overrides.matches("[rules.").count(), 9);
    assert_eq!(overrides.matches("severity = \"error\"").count(), 9);
}

#[test]
fn user_flag_writes_to_the_user_overrides_file() {
    let repo = repo_with_languages();
    let home = tempfile::tempdir().expect("home tempdir");

    let output = run_setup_user_flag(repo.path(), home.path(), "strict");
    let result = data(&output);

    let overrides_path = home.path().join("user-overrides.toml");
    let written_path = overrides_path.to_string_lossy().into_owned();
    assert_eq!(result["scope"], "user");
    assert_eq!(result["written"].as_str(), Some(written_path.as_str()));
    let overrides = std::fs::read_to_string(overrides_path).expect("user overrides written");
    assert_eq!(overrides.matches("severity = \"error\"").count(), 9);
}
