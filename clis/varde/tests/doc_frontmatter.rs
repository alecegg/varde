use assert_cmd::Command;
use predicates::str::contains;
use serde_json::Value;
use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn frontmatter(args: &[&str]) -> Command {
    let mut command = Command::cargo_bin("varde").expect("varde binary");
    command.args(["doc", "frontmatter"]).args(args);
    command
}

fn envelope(output: &[u8]) -> Value {
    serde_json::from_slice(output).expect("json envelope")
}

fn write_skill(root: &Path, name: &str, frontmatter: &str) -> String {
    let dir = root.join(name);
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(
        dir.join("SKILL.md"),
        format!("---\n{frontmatter}---\n# Body\n"),
    )
    .unwrap();
    dir.to_str().unwrap().to_string()
}

#[test]
fn clean_skills_succeed_with_results_in_the_envelope() {
    let output = frontmatter(&["skills/varde-change", "--json"])
        .current_dir(repo_root())
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let value = envelope(&output);
    assert_eq!(value["ok"], true);
    let results = value["data"]["results"].as_array().unwrap();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0]["path"], "skills/varde-change/SKILL.md");
    assert_eq!(results[0]["ok"], true);
}

#[test]
fn text_output_marks_ok_skills() {
    frontmatter(&["skills/varde-change"])
        .current_dir(repo_root())
        .assert()
        .success()
        .stdout("OK    skills/varde-change/SKILL.md\n");
}

#[test]
fn failing_skill_exits_1_with_negative_result() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = write_skill(tmp.path(), "bad", "name: wrong\ndescription: plain\n");

    let output = frontmatter(&[&dir, "--json"])
        .assert()
        .code(1)
        .get_output()
        .stdout
        .clone();
    let value = envelope(&output);
    assert_eq!(value["ok"], false);
    assert_eq!(value["outcome"], "negative-result");
    assert_eq!(value["data"]["error"]["code"], "doc_frontmatter_failed");
    let results = value["data"]["error"]["details"]["results"]
        .as_array()
        .unwrap();
    assert_eq!(results[0]["ok"], false);
    assert_eq!(results[0]["errors"].as_array().unwrap().len(), 2);

    frontmatter(&[&dir])
        .assert()
        .code(1)
        .stdout(contains(format!("FAIL  {dir}/SKILL.md")))
        .stdout(contains(
            "      error:   `description` must be one double-quoted physical line",
        ));
}

#[test]
fn missing_path_exits_2_in_both_modes() {
    frontmatter(&["no-such-path"])
        .assert()
        .code(2)
        .stderr(contains("path not found: no-such-path"));
    let output = frontmatter(&["no-such-path", "--json"])
        .assert()
        .code(2)
        .get_output()
        .stderr
        .clone();
    let value = envelope(&output);
    assert_eq!(value["ok"], false);
    assert_eq!(value["outcome"], "tool-error");
    assert_eq!(value["data"]["error"]["code"], "doc_frontmatter_input");
}

#[test]
fn directory_without_skills_exits_2() {
    let dir = tempfile::tempdir().unwrap();
    frontmatter(&[dir.path().to_str().unwrap()])
        .assert()
        .code(2)
        .stderr(contains("no SKILL.md found at or under"));
}

#[test]
fn json_usage_errors_print_a_tool_error_envelope() {
    for args in [&["--json"][..], &["--json", "--bogus", "a"][..]] {
        let output = frontmatter(args)
            .assert()
            .code(2)
            .get_output()
            .stderr
            .clone();
        let value = envelope(&output);
        assert_eq!(value["ok"], false);
        assert_eq!(value["outcome"], "tool-error");
        assert_eq!(value["data"]["error"]["code"], "doc_frontmatter_usage");
    }
}
