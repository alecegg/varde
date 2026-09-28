//! Tracing/logging wiring tests (task: tracing-logging-wiring).
//! Human-readable logs on stderr; stdout stays a clean JSON document.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};

fn bin() -> Command {
    Command::new(env!("CARGO_BIN_EXE_varde-code"))
}

const MIXED_DIR: &str = "tests/fixtures/ts/mixed";

fn tempdir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "varde-tracing-logging-{tag}-{}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("temp dir creates");
    dir
}

fn run_build(home: &Path, repo: &Path, verbose: bool) -> Output {
    let mut command = bin();
    command.env_remove("RUST_LOG");
    command.args(["build", "--repo-root", repo.to_str().expect("utf-8 path")]);
    if verbose {
        command.arg("--verbose");
    }
    command.env("HOME", home).output().expect("run build")
}

fn run_changed_build(tag: &str, verbose: bool) -> Output {
    let home = tempdir(&format!("{tag}-home"));
    let repo = tempdir(&format!("{tag}-repo"));
    std::fs::write(repo.join("lib.rs"), "pub fn target() {}\n").expect("fixture writes");
    let initial = run_build(&home, &repo, false);
    assert!(
        initial.status.success(),
        "initial build failed: {:?}",
        initial.stderr
    );
    std::fs::write(repo.join("lib.rs"), "pub fn changed() {}\n").expect("fixture updates");

    let output = run_build(&home, &repo, verbose);
    let _ = std::fs::remove_dir_all(home);
    let _ = std::fs::remove_dir_all(repo);
    output
}

#[test]
fn stdout_stays_valid_json_with_verbose_and_rust_log_trace() {
    let out = bin()
        .args(["extract", MIXED_DIR, "--verbose"])
        .env("RUST_LOG", "trace")
        .output()
        .expect("run extract");
    assert!(out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);
    let value: serde_json::Value =
        serde_json::from_str(stdout.trim()).expect("stdout must remain well-formed JSON");
    assert!(value.is_object());
}

#[test]
fn human_readable_logs_on_stderr_not_stdout() {
    let out = bin()
        .args(["extract", MIXED_DIR, "--verbose"])
        .env("RUST_LOG", "trace")
        .output()
        .expect("run extract");
    assert!(out.status.success());

    let stderr = String::from_utf8_lossy(&out.stderr);
    // Human-readable tracing lines: level tag + message on stderr.
    assert!(
        stderr.contains("INFO") || stderr.contains("WARN"),
        "stderr must carry human-readable log lines, got: {stderr:?}"
    );
    assert!(
        stderr.contains("extract complete") || stderr.contains("skipped"),
        "stderr should mention extraction activity, got: {stderr:?}"
    );

    // The same log text must be absent from stdout.
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        !stdout.contains("INFO") && !stdout.contains("WARN"),
        "log lines must not leak onto stdout"
    );
}

#[test]
fn normal_build_hides_per_file_extraction_events() {
    let out = run_changed_build("normal", false);
    assert!(out.status.success(), "build failed: {:?}", out.stderr);
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(
        !stderr.contains("extracting"),
        "unexpected start event: {stderr}"
    );
    assert!(
        !stderr.contains("extract complete"),
        "unexpected completion event: {stderr}"
    );
}

#[test]
fn verbose_build_shows_per_file_extraction_events() {
    let out = run_changed_build("verbose", true);
    assert!(out.status.success(), "build failed: {:?}", out.stderr);
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(
        stderr.contains("extracting"),
        "missing start event: {stderr}"
    );
    assert!(
        stderr.contains("extract complete"),
        "missing completion event: {stderr}"
    );
}
