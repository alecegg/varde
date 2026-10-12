use assert_cmd::Command;
use std::os::unix::fs::PermissionsExt;
use tempfile::tempdir;

#[test]
fn mutation_fails_and_source_skill_is_untouched_then_restored_skill_passes() {
    let root = tempdir().unwrap();
    let skill = root.path().join("skill");
    std::fs::create_dir_all(skill.join("evals")).unwrap();
    std::fs::write(
        skill.join("SKILL.md"),
        "---\nname: skill\ndescription: Fixture skill.\n---\nDo not write answer.txt\nUnrelated guidance.\n",
    )
    .unwrap();
    std::fs::write(
        skill.join("evals/evals.json"),
        r#"{"skill_name":"fixture","evals":[{"id":"no_write","prompt":"follow the skill","assert":[{"kind":"file_absent","path":"answer.txt"}]}]}"#,
    )
    .unwrap();
    std::fs::write(
        skill.join("evals/mutations.json"),
        r#"{"mutations":[{"id":"allow_write","file":"SKILL.md","remove":"Do not write answer.txt","evals":["no_write"]},{"id":"unrelated","file":"SKILL.md","remove":"Unrelated guidance.","negative":true,"evals":["no_write"]}]}"#,
    )
    .unwrap();

    let bin = root.path().join("bin");
    std::fs::create_dir_all(&bin).unwrap();
    let claude = bin.join("claude");
    std::fs::write(
        &claude,
        r##"#!/bin/sh
if [ -f "$PWD/.skill-under-evaluation/SKILL.md" ] && ! grep -q 'Do not write answer.txt' "$PWD/.skill-under-evaluation/SKILL.md"; then
  printf bad > answer.txt
fi
printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"result":"ok","duration_ms":1}'
"##,
    )
    .unwrap();
    let mut permissions = std::fs::metadata(&claude).unwrap().permissions();
    permissions.set_mode(0o755);
    std::fs::set_permissions(&claude, permissions).unwrap();

    let existing_path = std::env::var_os("PATH").unwrap_or_default();
    let path =
        std::env::join_paths(std::iter::once(bin).chain(std::env::split_paths(&existing_path)))
            .unwrap();
    Command::cargo_bin("varde")
        .unwrap()
        .args([
            "learn",
            "eval",
            "calibrate",
            skill.to_str().unwrap(),
            "--harness",
            "claude",
            "--json",
        ])
        .env("PATH", path)
        .assert()
        .success();

    assert_eq!(
        std::fs::read_to_string(skill.join("SKILL.md")).unwrap(),
        "---\nname: skill\ndescription: Fixture skill.\n---\nDo not write answer.txt\nUnrelated guidance.\n"
    );
}

#[test]
fn calibrate_help_is_exposed_under_eval() {
    Command::cargo_bin("varde")
        .unwrap()
        .args(["learn", "eval", "--help"])
        .assert()
        .success()
        .stdout(predicates::str::contains("calibrate"));
}
