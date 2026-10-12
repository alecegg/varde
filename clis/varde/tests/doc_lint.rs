use assert_cmd::Command;
use predicates::str::contains;
use serde_json::Value;
use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn lint(args: &[&str]) -> Command {
    let mut command = Command::cargo_bin("varde").expect("varde binary");
    command.args(["doc", "lint"]).args(args);
    command
}

fn envelope(output: &[u8]) -> Value {
    serde_json::from_slice(output).expect("json envelope")
}

#[test]
fn clean_skill_succeeds_with_findings_in_the_envelope() {
    let output = lint(&["skills/varde-change/SKILL.md", "--json"])
        .current_dir(repo_root())
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let value = envelope(&output);
    assert_eq!(value["ok"], true);
    assert!(value["data"]["findings"].is_array());
}

#[test]
fn six_sentence_unit_exits_1_with_negative_result() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("long.md");
    std::fs::write(&file, "One a. Two b. Three c. Four d. Five e. Six f.\n").unwrap();
    let path = file.to_str().unwrap();

    let output = lint(&[path, "--json"])
        .assert()
        .code(1)
        .get_output()
        .stdout
        .clone();
    let value = envelope(&output);
    assert_eq!(value["ok"], false);
    assert_eq!(value["outcome"], "negative-result");
    let findings = value["data"]["error"]["details"]["findings"]
        .as_array()
        .unwrap();
    assert!(findings.iter().any(|f| f["severity"] == "error"));

    lint(&[path])
        .assert()
        .code(1)
        .stdout(contains(format!("ERROR {path}:1 (unit, 6 sentences)")))
        .stdout(contains("1 error(s), 0 warning(s) across 1 file(s)."));
}

#[test]
fn missing_path_exits_2_in_both_modes() {
    lint(&["no-such-path.md"])
        .assert()
        .code(2)
        .stderr(contains("no such file or directory: no-such-path.md"));
    let output = lint(&["no-such-path.md", "--json"])
        .assert()
        .code(2)
        .get_output()
        .stderr
        .clone();
    let value = envelope(&output);
    assert_eq!(value["ok"], false);
    assert_eq!(value["outcome"], "tool-error");
}

#[test]
fn json_usage_errors_print_a_tool_error_envelope() {
    for args in [&["--json"][..], &["--json", "--bogus", "a.md"][..]] {
        let output = lint(args).assert().code(2).get_output().stderr.clone();
        let value = envelope(&output);
        assert_eq!(value["ok"], false);
        assert_eq!(value["outcome"], "tool-error");
        assert_eq!(value["data"]["error"]["code"], "doc_lint_usage");
    }
}

#[test]
fn directory_without_markdown_exits_2() {
    let dir = tempfile::tempdir().unwrap();
    lint(&[dir.path().to_str().unwrap()])
        .assert()
        .code(2)
        .stderr(contains("no Markdown files found"));
}
