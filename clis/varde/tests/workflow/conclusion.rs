//! `varde plan conclude` reads `<dir>/review.md` and accepts only an
//! approved verdict whose `head` matches the merged commit.

use super::common;

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

fn git(root: &Path, args: &[&str]) -> Output {
    let output = Command::new("git")
        .args(args)
        .current_dir(root)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "git {args:?} failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    output
}

fn fixture(tag: &str) -> (PathBuf, PathBuf) {
    let root = common::temp_bundle(tag);
    git(&root, &["init", "-q"]);
    git(&root, &["config", "user.name", "Conclusion Test"]);
    git(&root, &["config", "user.email", "conclude@example.invalid"]);
    fs::write(root.join("README.md"), "fixture\n").unwrap();
    let plan_dir = root.join("memory-bank/working/plans/2026-10-09-feature");
    fs::create_dir_all(&plan_dir).unwrap();
    (root, plan_dir)
}

fn commit_all(root: &Path, message: &str) -> String {
    git(root, &["add", "-A"]);
    git(root, &["commit", "-qm", message]);
    let output = git(root, &["rev-parse", "HEAD"]);
    String::from_utf8(output.stdout).unwrap().trim().to_owned()
}

fn write_plan(plan_dir: &Path, status: &str) {
    fs::write(
        plan_dir.join("plan.md"),
        format!(
            "---\ntype: plan\nstatus: {status}\n---\n\n## Acceptance criteria\n\n- [x] verified\n"
        ),
    )
    .unwrap();
}

fn write_review(plan_dir: &Path, verdict: &str, head: &str) {
    fs::write(
        plan_dir.join("review.md"),
        format!(
            "---\ntype: review\nverdict: {verdict}\nreviewer: test\nbase: {head}\nhead: {head}\n---\n\nReviewed.\n"
        ),
    )
    .unwrap();
}

fn conclude(root: &Path, plan_dir: &Path, args: &[&str]) -> Output {
    let mut command = common::isolate_memory(root);
    command.arg("conclude").arg(plan_dir);
    for arg in args {
        command.arg(arg);
    }
    command.arg("--json").output().unwrap()
}

#[test]
fn conclude_review_report_accepts_the_merged_head() {
    let (root, plan_dir) = fixture("conclude-approved");
    let head = commit_all(&root, "reviewed");
    write_plan(&plan_dir, "active");
    write_review(&plan_dir, "approved", &head);

    let output = conclude(&root, &plan_dir, &["--repo", root.to_str().unwrap()]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["plan_id"], "2026-10-09-feature");
    assert_eq!(data["reviewed_head"], head);
    assert!(
        fs::read_to_string(plan_dir.join("plan.md"))
            .unwrap()
            .contains("status: completed"),
        "plan was not marked completed"
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn conclude_review_report_rejects_a_head_mismatch() {
    let (root, plan_dir) = fixture("conclude-mismatch");
    let head = commit_all(&root, "reviewed");
    write_plan(&plan_dir, "active");
    write_review(&plan_dir, "approved", &head);
    let merged = commit_all(&root, "merged later");

    let output = conclude(&root, &plan_dir, &["--repo", root.to_str().unwrap()]);
    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains(&merged) && stderr.contains(&head),
        "expected both shas: {stderr}"
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn conclude_review_report_accepts_an_explicit_merged_rev() {
    let (root, plan_dir) = fixture("conclude-merged-flag");
    let head = commit_all(&root, "reviewed");
    write_plan(&plan_dir, "active");
    write_review(&plan_dir, "approved", &head);
    commit_all(&root, "later");

    let output = conclude(
        &root,
        &plan_dir,
        &["--repo", root.to_str().unwrap(), "--merged", &head],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn conclude_review_report_rejects_an_unknown_head() {
    let (root, plan_dir) = fixture("conclude-unknown");
    commit_all(&root, "reviewed");
    write_plan(&plan_dir, "active");
    let unknown = "a".repeat(40);
    write_review(&plan_dir, "approved", &unknown);

    let output = conclude(&root, &plan_dir, &["--repo", root.to_str().unwrap()]);
    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains(&format!(
            "review commit {unknown} not found in {}",
            root.canonicalize().unwrap().display()
        )),
        "{stderr}"
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn conclude_review_report_names_an_unknown_merged_revision() {
    let (root, plan_dir) = fixture("conclude-unknown-merged");
    let head = commit_all(&root, "reviewed");
    write_plan(&plan_dir, "active");
    write_review(&plan_dir, "approved", &head);
    let unknown = "b".repeat(40);

    let output = conclude(
        &root,
        &plan_dir,
        &["--repo", root.to_str().unwrap(), "--merged", &unknown],
    );
    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("merged commit") && stderr.contains(&unknown),
        "expected the unknown merged revision to be named: {stderr}"
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn conclude_review_report_rejects_a_changes_requested_verdict() {
    let (root, plan_dir) = fixture("conclude-changes-requested");
    let head = commit_all(&root, "reviewed");
    write_plan(&plan_dir, "active");
    write_review(&plan_dir, "changes-requested", &head);

    let output = conclude(&root, &plan_dir, &["--repo", root.to_str().unwrap()]);
    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("changes-requested"),
        "expected the verdict in the error: {stderr}"
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn conclude_review_report_accepts_a_single_change_dir() {
    let (root, plan_dir) = fixture("conclude-single-change");
    let head = commit_all(&root, "reviewed");
    fs::write(
        plan_dir.join("task.md"),
        "---\ntype: task\nstatus: todo\n---\n\nShip one fix.\n",
    )
    .unwrap();
    write_review(&plan_dir, "approved", &head);
    assert!(!plan_dir.join("plan.md").exists());

    let output = conclude(&root, &plan_dir, &["--repo", root.to_str().unwrap()]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["plan_id"], "2026-10-09-feature");
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn conclude_without_a_review_report_fails() {
    let (root, plan_dir) = fixture("conclude-no-review");
    commit_all(&root, "reviewed");
    write_plan(&plan_dir, "active");

    let output = conclude(&root, &plan_dir, &["--repo", root.to_str().unwrap()]);
    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("review.md"), "{stderr}");
    fs::remove_dir_all(root).unwrap();
}
