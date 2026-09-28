use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command as ProcessCommand, Output, Stdio};

use assert_cmd::Command;
use predicates::prelude::*;
use serde_json::Value;
use tempfile::TempDir;
use varde_learn_core::{
    HistoricalCaptureRequest, HistoricalItemMode, HistoricalOccurrenceRequest, HistoricalWitness,
    Store,
};

fn list_command(root: &TempDir) -> Command {
    let mut command = Command::cargo_bin("varde-learn").expect("varde-learn binary");
    command
        .current_dir(root.path())
        .env_remove("VARDE_LEARN_STORE")
        .env_remove("VARDE_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env("HOME", root.path().join("home"))
        .args(["friction", "list", "--json"]);
    command
}

fn run_add(root: &TempDir, cwd: &Path, store_dir: &Path, args: &[&str], evidence: &str) -> Output {
    let mut command = ProcessCommand::new(env!("CARGO_BIN_EXE_varde-learn"));
    command
        .current_dir(cwd)
        .env_remove("VARDE_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env("HOME", root.path().join("home"))
        .env("VARDE_LEARN_STORE", store_dir)
        .args(["friction", "add"])
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = command.spawn().expect("spawn friction add");
    child
        .stdin
        .take()
        .expect("stdin pipe")
        .write_all(evidence.as_bytes())
        .expect("write evidence");
    child.wait_with_output().expect("wait for friction add")
}

fn run_list(root: &TempDir, cwd: &Path, store_dir: &Path, args: &[&str]) -> Output {
    ProcessCommand::new(env!("CARGO_BIN_EXE_varde-learn"))
        .current_dir(cwd)
        .env_remove("VARDE_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env("HOME", root.path().join("home"))
        .env("VARDE_LEARN_STORE", store_dir)
        .args(["friction", "list", "--json"])
        .args(args)
        .output()
        .expect("run friction list")
}

fn run_show(
    root: &TempDir,
    cwd: &Path,
    store_dir: &Path,
    identifier: &str,
    args: &[&str],
) -> Output {
    ProcessCommand::new(env!("CARGO_BIN_EXE_varde-learn"))
        .current_dir(cwd)
        .env_remove("VARDE_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env("HOME", root.path().join("home"))
        .env("VARDE_LEARN_STORE", store_dir)
        .args(["friction", "show", identifier, "--json"])
        .args(args)
        .output()
        .expect("run friction show")
}

fn run_set_status(
    root: &TempDir,
    cwd: &Path,
    store_dir: &Path,
    identifier: &str,
    status: &str,
    reason: &str,
) -> Output {
    ProcessCommand::new(env!("CARGO_BIN_EXE_varde-learn"))
        .current_dir(cwd)
        .env_remove("VARDE_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env("HOME", root.path().join("home"))
        .env("VARDE_LEARN_STORE", store_dir)
        .args([
            "friction",
            "set-status",
            identifier,
            status,
            "--reason",
            reason,
            "--json",
        ])
        .output()
        .expect("run friction set-status")
}

fn run_export(root: &TempDir, cwd: &Path, store_dir: &Path, destination: &Path) -> Output {
    ProcessCommand::new(env!("CARGO_BIN_EXE_varde-learn"))
        .current_dir(cwd)
        .env_remove("VARDE_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env("HOME", root.path().join("home"))
        .env("VARDE_LEARN_STORE", store_dir)
        .args([
            "friction",
            "export",
            destination.to_str().unwrap(),
            "--json",
        ])
        .output()
        .expect("run friction export")
}

fn run_import(
    root: &TempDir,
    cwd: &Path,
    store_dir: &Path,
    source_dir: &Path,
    repo: &Path,
    args: &[&str],
) -> Output {
    ProcessCommand::new(env!("CARGO_BIN_EXE_varde-learn"))
        .current_dir(cwd)
        .env_remove("VARDE_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env("HOME", root.path().join("home"))
        .env("VARDE_LEARN_STORE", store_dir)
        .args([
            "friction",
            "import",
            source_dir.to_str().unwrap(),
            "--repo",
            repo.to_str().unwrap(),
        ])
        .args(args)
        .output()
        .expect("run friction import")
}

fn run_adopt_record(root: &TempDir, cwd: &Path, store_dir: &Path, args: &[&str]) -> Output {
    ProcessCommand::new(env!("CARGO_BIN_EXE_varde-learn"))
        .current_dir(cwd)
        .env_remove("VARDE_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env("HOME", root.path().join("home"))
        .env("VARDE_LEARN_STORE", store_dir)
        .args(["adopt", "record", "--json"])
        .args(args)
        .output()
        .expect("run adopt record")
}

fn run_adopt_recurrence(root: &TempDir, cwd: &Path, store_dir: &Path, args: &[&str]) -> Output {
    ProcessCommand::new(env!("CARGO_BIN_EXE_varde-learn"))
        .current_dir(cwd)
        .env_remove("VARDE_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env("HOME", root.path().join("home"))
        .env("VARDE_LEARN_STORE", store_dir)
        .args(["adopt", "recurrence", "--json"])
        .args(args)
        .output()
        .expect("run adopt recurrence")
}

fn spawn_set_status(
    root: &TempDir,
    cwd: &Path,
    store_dir: &Path,
    identifier: &str,
    status: &str,
    reason: &str,
) -> std::process::Child {
    ProcessCommand::new(env!("CARGO_BIN_EXE_varde-learn"))
        .current_dir(cwd)
        .env_remove("VARDE_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env("HOME", root.path().join("home"))
        .env("VARDE_LEARN_STORE", store_dir)
        .args([
            "friction",
            "set-status",
            identifier,
            status,
            "--reason",
            reason,
            "--json",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn friction set-status")
}

fn init_test_repository(path: &Path) -> PathBuf {
    std::fs::create_dir_all(path).expect("create repository directory");
    let status = ProcessCommand::new("git")
        .args(["init", "--quiet"])
        .current_dir(path)
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .status()
        .expect("initialize repository");
    assert!(status.success());
    path.canonicalize().expect("canonical repository path")
}

fn assert_empty_json_list(output: &[u8]) {
    let value: Value = serde_json::from_slice(output).expect("friction list JSON");
    assert_eq!(value["schema_version"], 1);
    assert_eq!(value["ok"], true);
    assert_eq!(value["outcome"], "success");
    assert_eq!(value["data"]["items"], serde_json::json!([]));
    assert_eq!(value["meta"]["truncated"], false);
}

fn write_config(config_dir: &Path, learn_dir: &str) {
    std::fs::create_dir_all(config_dir).expect("create config directory");
    std::fs::write(
        config_dir.join("config.toml"),
        format!("[default]\nlearn = {learn_dir:?}\n"),
    )
    .expect("write global config");
}

#[test]
fn historical_provenance_shows_exports_restores_and_rejects_duplicate_incidents() {
    let root = TempDir::new().expect("temp root");
    let repo = init_test_repository(&root.path().join("repo"));
    let cwd = repo.join("cwd");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    let repo_root = repo.to_string_lossy().into_owned();
    let historical_cwd = repo.join("old-cwd").to_string_lossy().into_owned();
    let source_store_dir = root.path().join("source-store");
    let mut store = Store::open(&source_store_dir).expect("open source store");
    let capture_request = HistoricalCaptureRequest {
        mode: HistoricalItemMode::Create {
            source: "varde-learn".to_owned(),
            title: "Historical failure".to_owned(),
            target: Some("skills/varde-learn/SKILL.md".to_owned()),
            repo_root: Some(repo_root.clone()),
        },
        occurrence: HistoricalOccurrenceRequest {
            at: "2026-09-12T09:45:00Z".to_owned(),
            cwd: historical_cwd.clone(),
            repo_root: Some(repo_root.clone()),
            head_sha: Some("historical-head".to_owned()),
            evidence: "The historical tool call failed.".to_owned(),
            canonical_facts: serde_json::json!({
                "event": {"tool":"exec", "error":"permission denied"},
                "context": {"turn":7}
            }),
            witness: HistoricalWitness {
                harness: "codex".to_owned(),
                thread_id: "thread-9".to_owned(),
                incident_kind: "failed-tool".to_owned(),
                witness_id: Some("event-3".to_owned()),
                source_id: "/old/capture/session.jsonl".to_owned(),
                record_index: 3,
                byte_start: 120,
                byte_end: 240,
                record_digest: format!("sha256:{}", "c".repeat(64)),
            },
        },
    };
    let captured = store
        .record_historical_occurrence(capture_request.clone())
        .expect("capture historical occurrence");
    let key = captured
        .occurrence
        .provenance
        .as_ref()
        .expect("capture provenance")
        .incident_key
        .clone();
    drop(store);

    let shown = run_show(
        &root,
        &cwd,
        &source_store_dir,
        &captured.item.id.to_string(),
        &[],
    );
    assert!(
        shown.status.success(),
        "{}",
        String::from_utf8_lossy(&shown.stderr)
    );
    let shown: Value = serde_json::from_slice(&shown.stdout).expect("show JSON");
    assert_eq!(
        shown["data"]["occurrences"][0]["provenance"]["incident_key"],
        key
    );
    assert_eq!(
        shown["data"]["occurrences"][0]["at"],
        "2026-09-12T09:45:00Z"
    );
    assert_eq!(
        shown["data"]["occurrences"][0]["cwd"],
        repo.join("old-cwd").to_string_lossy().as_ref()
    );

    let export_dir = root.path().join("export");
    let exported = run_export(&root, &cwd, &source_store_dir, &export_dir);
    assert!(
        exported.status.success(),
        "{}",
        String::from_utf8_lossy(&exported.stderr)
    );
    let export_path = export_dir.join("historical-failure.md");
    let export_text = std::fs::read_to_string(&export_path).expect("read Markdown export");
    assert!(export_text.contains("provenance:"));
    assert!(export_text.contains(&key));

    let restored_store_dir = root.path().join("restored-store");
    let restored = run_import(
        &root,
        &cwd,
        &restored_store_dir,
        &export_dir,
        &repo,
        &["--json"],
    );
    assert!(
        restored.status.success(),
        "{}",
        String::from_utf8_lossy(&restored.stderr)
    );
    let restored: Value = serde_json::from_slice(&restored.stdout).expect("import JSON");
    assert_eq!(restored["data"]["summary"]["imported"], 1);
    let restored_show = run_show(
        &root,
        &cwd,
        &restored_store_dir,
        &captured.item.id.to_string(),
        &[],
    );
    assert!(restored_show.status.success());
    let restored_show: Value = serde_json::from_slice(&restored_show.stdout).expect("show JSON");
    assert_eq!(
        restored_show["data"]["occurrences"][0]["provenance"]["incident_key"],
        key
    );
    let restored_occurrence_id = restored_show["data"]["occurrences"][0]["id"]
        .as_i64()
        .expect("restored occurrence ID");
    let mut restored_store = Store::open(&restored_store_dir).expect("open restore store");
    let retry = restored_store
        .record_historical_occurrence(capture_request.clone())
        .expect("unchanged imported context is idempotent");
    assert!(!retry.created);
    assert_eq!(retry.item.id, captured.item.id);
    assert_eq!(retry.occurrence.id, restored_occurrence_id);
    assert_eq!(retry.occurrence.at, "2026-09-12T09:45:00Z");
    assert_eq!(retry.occurrence.cwd, historical_cwd);
    assert_eq!(
        retry.occurrence.repo_root.as_deref(),
        Some(repo_root.as_str())
    );
    assert_eq!(
        retry.occurrence.head_sha.as_deref(),
        Some("historical-head")
    );
    drop(restored_store);

    for (field, original, edited) in [
        ("at", "2026-09-12T09:45:00Z", "2026-09-25T09:45:00Z"),
        ("cwd", historical_cwd.as_str(), "/altered/B"),
        ("repo_root", repo_root.as_str(), "/altered/repo"),
        ("head_sha", "historical-head", "edited-head"),
    ] {
        let mut edited_export = export_text.clone();
        let original_line = format!(
            "    {field}: {}",
            serde_json::to_string(original).expect("encode original value")
        );
        assert_eq!(edited_export.matches(&original_line).count(), 1);
        let edited_line = format!(
            "    {field}: {}",
            serde_json::to_string(edited).expect("encode edited value")
        );
        edited_export = edited_export.replacen(&original_line, &edited_line, 1);
        let edited_import_dir = root.path().join(format!("edited-{field}-export"));
        std::fs::create_dir(&edited_import_dir).expect("create edited import directory");
        std::fs::write(edited_import_dir.join("edited.md"), edited_export)
            .expect("write edited export");
        let edited_store_dir = root.path().join(format!("edited-{field}-store"));
        let edited_import = run_import(
            &root,
            &cwd,
            &edited_store_dir,
            &edited_import_dir,
            &repo,
            &["--json"],
        );
        assert!(
            edited_import.status.success(),
            "{}",
            String::from_utf8_lossy(&edited_import.stderr)
        );
        let edited_import: Value =
            serde_json::from_slice(&edited_import.stdout).expect("import JSON");
        assert_eq!(edited_import["data"]["summary"]["imported"], 1);
        let edited_item_id = edited_import["data"]["results"][0]["id"]
            .as_i64()
            .expect("edited import item ID")
            .to_string();
        let before_conflict = run_show(&root, &cwd, &edited_store_dir, &edited_item_id, &[]);
        assert!(before_conflict.status.success());
        let before_conflict: Value =
            serde_json::from_slice(&before_conflict.stdout).expect("show before retry");
        let occurrence = &before_conflict["data"]["occurrences"][0];
        assert_eq!(occurrence[field], edited);

        let mut edited_store = Store::open(&edited_store_dir).expect("open edited store");
        let error = edited_store
            .record_historical_occurrence(capture_request.clone())
            .expect_err("edited imported context must conflict with source-verified retry");
        assert_eq!(error.code(), "diagnose_incident_conflict");
        drop(edited_store);
        let after_conflict = run_show(&root, &cwd, &edited_store_dir, &edited_item_id, &[]);
        assert!(after_conflict.status.success());
        let after_conflict: Value =
            serde_json::from_slice(&after_conflict.stdout).expect("show after retry");
        assert_eq!(
            after_conflict["data"]["item"],
            before_conflict["data"]["item"]
        );
        assert_eq!(
            after_conflict["data"]["occurrences"],
            before_conflict["data"]["occurrences"]
        );
        let edited_list = run_list(&root, &cwd, &edited_store_dir, &[]);
        let edited_list: Value =
            serde_json::from_slice(&edited_list.stdout).expect("list after retry");
        assert_eq!(edited_list["data"]["items"].as_array().unwrap().len(), 1);
    }

    let duplicate_slug_import = run_import(
        &root,
        &cwd,
        &source_store_dir,
        &export_dir,
        &repo,
        &["--json"],
    );
    assert!(duplicate_slug_import.status.success());
    let duplicate_slug_import: Value =
        serde_json::from_slice(&duplicate_slug_import.stdout).expect("skip report JSON");
    assert_eq!(duplicate_slug_import["data"]["summary"]["skipped"], 1);

    let collision_dir = root.path().join("collision-import");
    std::fs::create_dir(&collision_dir).expect("create collision import");
    std::fs::write(
        collision_dir.join("different-slug.md"),
        export_text.replace(
            "slug: \"historical-failure\"",
            "slug: \"second-item-same-incident\"",
        ),
    )
    .expect("write colliding import");
    let collision = run_import(
        &root,
        &cwd,
        &source_store_dir,
        &collision_dir,
        &repo,
        &["--json"],
    );
    assert!(!collision.status.success());
    let listed = run_list(&root, &cwd, &source_store_dir, &[]);
    let listed: Value = serde_json::from_slice(&listed.stdout).expect("list JSON");
    assert_eq!(listed["data"]["items"].as_array().unwrap().len(), 1);

    let malformed_dir = root.path().join("malformed-import");
    std::fs::create_dir(&malformed_dir).expect("create malformed import");
    std::fs::write(
        malformed_dir.join("malformed.md"),
        export_text.replace(&key, "incident-v1:invalid"),
    )
    .expect("write malformed provenance export");
    let dry_store_dir = root.path().join("dry-run-store");
    let malformed = run_import(
        &root,
        &cwd,
        &dry_store_dir,
        &malformed_dir,
        &repo,
        &["--dry-run", "--json"],
    );
    assert!(malformed.status.success());
    let malformed: Value = serde_json::from_slice(&malformed.stdout).expect("dry-run JSON");
    assert_eq!(malformed["data"]["summary"]["skipped"], 1);
    assert!(!dry_store_dir.join("learn.db").exists());
}

#[test]
fn store_path_precedence_and_config_lookup_are_consistent() {
    let root = TempDir::new().expect("temp root");
    let home = root.path().join("home");
    let cwd = root.path().join("cwd");
    let config_override = root.path().join("config-override");
    let xdg = root.path().join("xdg");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    std::fs::create_dir_all(&home).expect("create home");

    let explicit_dir = root.path().join("explicit-store");
    let configured_dir = root.path().join("configured-store");
    write_config(&config_override, configured_dir.to_str().unwrap());
    list_command(&root)
        .current_dir(&cwd)
        .env("VARDE_CONFIG_DIR", &config_override)
        .env("XDG_CONFIG_HOME", &xdg)
        .env("VARDE_LEARN_STORE", &explicit_dir)
        .assert()
        .success()
        .stdout(predicate::function(|stdout: &str| {
            assert_empty_json_list(stdout.as_bytes());
            true
        }));
    assert!(explicit_dir.join("learn.db").is_file());
    assert!(!configured_dir.exists());

    let relative_dir = PathBuf::from("relative-learn");
    write_config(&config_override, "relative-learn");
    list_command(&root)
        .current_dir(&cwd)
        .env("VARDE_CONFIG_DIR", &config_override)
        .env("XDG_CONFIG_HOME", &xdg)
        .assert()
        .success()
        .stdout(predicate::function(|stdout: &str| {
            assert_empty_json_list(stdout.as_bytes());
            true
        }));
    assert!(cwd.join(relative_dir).join("learn.db").is_file());

    write_config(&xdg.join("varde"), "~/xdg-learn");
    list_command(&root)
        .current_dir(&cwd)
        .env("XDG_CONFIG_HOME", &xdg)
        .assert()
        .success()
        .stdout(predicate::function(|stdout: &str| {
            assert_empty_json_list(stdout.as_bytes());
            true
        }));
    assert!(home.join("xdg-learn/learn.db").is_file());

    std::fs::remove_file(config_override.join("config.toml")).expect("remove global config");
    list_command(&root)
        .current_dir(&cwd)
        .env("VARDE_CONFIG_DIR", &config_override)
        .assert()
        .success()
        .stdout(predicate::function(|stdout: &str| {
            assert_empty_json_list(stdout.as_bytes());
            true
        }));
    assert!(config_override.join("learn/learn.db").is_file());
}

#[test]
fn config_directory_environment_is_kept_literal_like_workflow() {
    let root = TempDir::new().expect("temp root");
    let home = root.path().join("home");
    let cwd = root.path().join("cwd");
    std::fs::create_dir_all(&home).expect("create home");
    std::fs::create_dir_all(&cwd).expect("create cwd");

    let literal_config_dir = cwd.join("~/varde-config");
    let expanded_config_dir = home.join("varde-config");
    write_config(&literal_config_dir, "literal-store");
    write_config(&expanded_config_dir, "expanded-store");

    list_command(&root)
        .current_dir(&cwd)
        .env("HOME", &home)
        .env("VARDE_CONFIG_DIR", "~/varde-config")
        .assert()
        .success()
        .stdout(predicate::function(|stdout: &str| {
            assert_empty_json_list(stdout.as_bytes());
            true
        }));

    assert!(cwd.join("literal-store/learn.db").is_file());
    assert!(!cwd.join("expanded-store/learn.db").exists());
}

#[test]
fn invalid_explicit_path_fails_without_falling_back() {
    let root = TempDir::new().expect("temp root");
    let config_dir = root.path().join("config");
    let invalid_path = root.path().join("not-a-directory");
    std::fs::write(&invalid_path, "file").expect("make invalid store path");
    write_config(&config_dir, "configured-fallback");

    let output = list_command(&root)
        .env("VARDE_CONFIG_DIR", &config_dir)
        .env("VARDE_LEARN_STORE", &invalid_path)
        .assert()
        .code(2)
        .get_output()
        .clone();
    let error: Value = serde_json::from_slice(&output.stderr).expect("error JSON envelope");
    assert_eq!(error["schema_version"], 1);
    assert_eq!(error["ok"], false);
    assert_eq!(error["meta"]["truncated"], false);
    assert!(!config_dir.join("configured-fallback").exists());
}

#[test]
fn git_ceiling_cannot_hide_store_inside_repository() {
    let root = TempDir::new().expect("temp root");
    let repo = root.path().join("repo");
    std::fs::create_dir_all(repo.join("sub")).expect("create nested repository path");
    ProcessCommand::new("git")
        .args(["init", "--quiet"])
        .current_dir(&repo)
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env_remove("GIT_CEILING_DIRECTORIES")
        .status()
        .expect("run git init")
        .success()
        .then_some(())
        .expect("initialize repository");

    let cwd = repo.join("sub");
    let store_dir = cwd.join("store");
    let output = ProcessCommand::new(env!("CARGO_BIN_EXE_varde-learn"))
        .current_dir(&cwd)
        .env_remove("VARDE_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env("HOME", root.path().join("home"))
        .env("VARDE_LEARN_STORE", &store_dir)
        .env("GIT_CEILING_DIRECTORIES", &repo)
        .args(["friction", "list", "--json"])
        .output()
        .expect("run friction list");

    assert_eq!(output.status.code(), Some(2));
    let error: Value = serde_json::from_slice(&output.stderr).expect("error JSON envelope");
    assert_eq!(error["data"]["error"]["code"], "store_inside_git");
    assert!(!store_dir.exists());
}

#[test]
fn store_inside_git_is_refused_through_symlink_before_creation() {
    let root = TempDir::new().expect("temp root");
    let repo = root.path().join("repo");
    std::fs::create_dir(&repo).expect("create repository");
    ProcessCommand::new("git")
        .args(["init", "--quiet"])
        .current_dir(&repo)
        .status()
        .expect("run git init")
        .success()
        .then_some(())
        .expect("initialize repository");

    let alias = root.path().join("repo-alias");
    #[cfg(unix)]
    std::os::unix::fs::symlink(&repo, &alias).expect("symlink repository");

    for store_dir in [repo.join("new/nested/store"), alias.join("linked/store")] {
        let output = list_command(&root)
            .env("VARDE_LEARN_STORE", &store_dir)
            .assert()
            .code(2)
            .get_output()
            .clone();
        let error: Value = serde_json::from_slice(&output.stderr).expect("error JSON envelope");
        assert_eq!(error["data"]["error"]["code"], "store_inside_git");
        assert!(
            error["data"]["error"]["message"]
                .as_str()
                .unwrap()
                .contains("VARDE_LEARN_STORE")
        );
        assert!(
            error["data"]["error"]["message"]
                .as_str()
                .unwrap()
                .contains("paths set --learn")
        );
        assert!(!store_dir.exists());
    }

    let outside_store = root.path().join("outside-store");
    std::fs::create_dir(&outside_store).expect("create outside store directory");
    std::os::unix::fs::symlink(repo.join("future.db"), outside_store.join("learn.db"))
        .expect("symlink database into repository");
    let output = list_command(&root)
        .env("VARDE_LEARN_STORE", &outside_store)
        .assert()
        .code(2)
        .get_output()
        .clone();
    let error: Value = serde_json::from_slice(&output.stderr).expect("error JSON envelope");
    assert_eq!(error["data"]["error"]["code"], "store_inside_git");
    assert!(!repo.join("future.db").exists());
}

#[test]
fn concurrent_list_initialization_succeeds_for_both_processes() {
    let root = TempDir::new().expect("temp root");
    let store_dir = root.path().join("shared-store");
    let binary = env!("CARGO_BIN_EXE_varde-learn");
    let commands = (0..2)
        .map(|_| {
            let mut command = ProcessCommand::new(binary);
            command
                .current_dir(root.path())
                .env_remove("VARDE_CONFIG_DIR")
                .env_remove("XDG_CONFIG_HOME")
                .env("HOME", root.path().join("home"))
                .env("VARDE_LEARN_STORE", &store_dir)
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .args(["friction", "list", "--json"]);
            command.spawn().expect("spawn list process")
        })
        .collect::<Vec<_>>();

    for child in commands {
        let output = child.wait_with_output().expect("wait for list process");
        assert!(
            output.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_empty_json_list(&output.stdout);
    }
    assert!(store_dir.join("learn.db").is_file());
}

#[test]
fn add_and_append_return_ids_and_duplicate_titles_get_safe_slugs() {
    let root = TempDir::new().expect("temp root");
    let cwd = root.path().join("outside-repository");
    let store_dir = root.path().join("store");
    std::fs::create_dir_all(&cwd).expect("create cwd");

    let created = run_add(
        &root,
        &cwd,
        &store_dir,
        &[
            "--source",
            "varde-change orchestrate",
            "--title",
            "Repeated title",
            "--target",
            "learn-cli/src/store.rs::Store::open",
            "--json",
        ],
        "The configured path was surprising.\n",
    );
    assert!(
        created.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&created.stderr)
    );
    let created: Value = serde_json::from_slice(&created.stdout).expect("add JSON");
    assert_eq!(created["ok"], true);
    assert_eq!(created["outcome"], "success");
    assert_eq!(created["data"]["slug"], "repeated-title");
    assert_eq!(created["meta"]["truncated"], false);
    let id = created["data"]["id"].as_i64().expect("item ID").to_string();

    let appended = run_add(
        &root,
        &cwd,
        &store_dir,
        &["--item", &id, "--json"],
        "A second occurrence for the same friction.\n",
    );
    assert!(
        appended.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&appended.stderr)
    );
    let appended: Value = serde_json::from_slice(&appended.stdout).expect("append JSON");
    assert_eq!(appended["data"]["id"], created["data"]["id"]);

    let duplicate = run_add(
        &root,
        &cwd,
        &store_dir,
        &[
            "--source",
            "varde-change",
            "--title",
            "Repeated title",
            "--json",
        ],
        "Same title, distinct observation.\n",
    );
    assert!(
        duplicate.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&duplicate.stderr)
    );
    let duplicate: Value = serde_json::from_slice(&duplicate.stdout).expect("duplicate JSON");
    assert_eq!(duplicate["data"]["slug"], "repeated-title-2");

    let listed = list_command(&root)
        .env("VARDE_LEARN_STORE", &store_dir)
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let listed: Value = serde_json::from_slice(&listed).expect("list JSON");
    assert_eq!(listed["data"]["items"].as_array().unwrap().len(), 2);
}

#[test]
fn friction_json_wraps_clap_errors_and_keeps_help_and_version() {
    let root = TempDir::new().expect("temp root");
    let run = |args: &[&str]| {
        ProcessCommand::new(env!("CARGO_BIN_EXE_varde-learn"))
            .current_dir(root.path())
            .env_remove("VARDE_CONFIG_DIR")
            .env_remove("XDG_CONFIG_HOME")
            .env_remove("VARDE_LEARN_STORE")
            .env("HOME", root.path().join("home"))
            .args(args)
            .output()
            .expect("run varde-learn")
    };

    for args in [
        vec!["friction", "list", "--limit", "nope", "--json"],
        vec!["friction", "import", "/tmp/source", "--json"],
    ] {
        let output = run(&args);
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stdout.is_empty());
        let error: Value = serde_json::from_slice(&output.stderr).expect("error JSON envelope");
        assert_eq!(error["schema_version"], 1);
        assert_eq!(error["envelope_version"], 1);
        assert_eq!(error["ok"], false);
        assert_eq!(error["outcome"], "tool-error");
        assert_eq!(error["data"]["error"]["code"], "usage_error");
        assert!(
            error["data"]["error"]["message"]
                .as_str()
                .is_some_and(|message| !message.is_empty())
        );
        assert_eq!(error["meta"]["truncated"], false);
    }

    let help = run(&["friction", "list", "--help"]);
    assert!(help.status.success());
    assert!(String::from_utf8_lossy(&help.stdout).contains("Usage: varde-learn friction list"));
    assert!(help.stderr.is_empty());

    let version = run(&["--version"]);
    assert!(version.status.success());
    assert!(String::from_utf8_lossy(&version.stdout).starts_with("varde-learn "));
    assert!(version.stderr.is_empty());
}

#[test]
fn invalid_add_arguments_return_json_errors_without_creating_items() {
    let root = TempDir::new().expect("temp root");
    let cwd = root.path().join("cwd");
    let store_dir = root.path().join("store");
    std::fs::create_dir_all(&cwd).expect("create cwd");

    for (args, evidence) in [
        (&["--source", "skill", "--json"][..], "evidence"),
        (
            &["--item", "1", "--source", "skill", "--json"][..],
            "evidence",
        ),
        (
            &["--source", " ", "--title", "title", "--json"][..],
            "evidence",
        ),
        (
            &["--source", "skill", "--title", "title", "--json"][..],
            "  \n",
        ),
    ] {
        let output = run_add(&root, &cwd, &store_dir, args, evidence);
        assert_eq!(output.status.code(), Some(2));
        let error: Value = serde_json::from_slice(&output.stderr).expect("error JSON");
        assert_eq!(error["ok"], false);
        assert_eq!(error["outcome"], "tool-error");
        assert_eq!(error["meta"]["truncated"], false);
    }
    assert!(!store_dir.join("learn.db").exists());
}

#[test]
fn concurrent_adds_persist_both_items() {
    let root = TempDir::new().expect("temp root");
    let cwd = root.path().join("cwd");
    let store_dir = root.path().join("store");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    let binary = env!("CARGO_BIN_EXE_varde-learn");
    let mut children = (0..2)
        .map(|_| {
            let mut command = ProcessCommand::new(binary);
            command
                .current_dir(&cwd)
                .env_remove("VARDE_CONFIG_DIR")
                .env_remove("XDG_CONFIG_HOME")
                .env("HOME", root.path().join("home"))
                .env("VARDE_LEARN_STORE", &store_dir)
                .args([
                    "friction",
                    "add",
                    "--source",
                    "tool",
                    "--title",
                    "Concurrent observation",
                    "--json",
                ])
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            command.spawn().expect("spawn add process")
        })
        .collect::<Vec<_>>();

    for (index, child) in children.iter_mut().enumerate() {
        child
            .stdin
            .take()
            .expect("stdin pipe")
            .write_all(format!("evidence {index}\n").as_bytes())
            .expect("write evidence");
    }
    let outputs = children
        .into_iter()
        .map(|child| child.wait_with_output().expect("wait for add process"))
        .collect::<Vec<_>>();
    let mut ids = Vec::new();
    for output in outputs {
        assert!(
            output.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        let result: Value = serde_json::from_slice(&output.stdout).expect("add JSON");
        ids.push(result["data"]["id"].as_i64().expect("item ID"));
    }
    ids.sort_unstable();
    ids.dedup();
    assert_eq!(ids.len(), 2);

    let listed = list_command(&root)
        .env("VARDE_LEARN_STORE", &store_dir)
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let listed: Value = serde_json::from_slice(&listed).expect("list JSON");
    assert_eq!(listed["data"]["items"].as_array().unwrap().len(), 2);
    assert_eq!(listed["data"]["items"][0]["slug"], "concurrent-observation");
    assert_eq!(
        listed["data"]["items"][1]["slug"],
        "concurrent-observation-2"
    );
}

#[test]
fn list_filters_scope_and_recovers_paginated_results() {
    let root = TempDir::new().expect("temp root");
    let repository = init_test_repository(&root.path().join("repo"));
    let store_dir = root.path().join("store");

    let first = run_add(
        &root,
        &repository,
        &store_dir,
        &[
            "--source",
            "skill-a",
            "--title",
            "Néedle friction",
            "--json",
        ],
        "Observed a literal 100%_path issue.\n",
    );
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    let first: Value = serde_json::from_slice(&first.stdout).expect("first item JSON");
    let first_id = first["data"]["id"].as_i64().unwrap();

    let append = run_add(
        &root,
        &repository,
        &store_dir,
        &["--item", &first_id.to_string()],
        "The same 100%_path issue happened again.\n",
    );
    assert!(
        append.status.success(),
        "{}",
        String::from_utf8_lossy(&append.stderr)
    );

    let second = run_add(
        &root,
        &repository,
        &store_dir,
        &["--source", "skill-b", "--title", "Second item"],
        "A literal 100Xpath is not a wildcard match.\n",
    );
    assert!(
        second.status.success(),
        "{}",
        String::from_utf8_lossy(&second.stderr)
    );

    let global = run_add(
        &root,
        &repository,
        &store_dir,
        &["--source", "skill-a", "--title", "Global item", "--global"],
        "Global occurrence.\n",
    );
    assert!(
        global.status.success(),
        "{}",
        String::from_utf8_lossy(&global.stderr)
    );

    let repo_arg = repository.to_str().unwrap();
    let first_page = run_list(
        &root,
        &repository,
        &store_dir,
        &["--status", "open", "--repo", repo_arg, "--limit", "1"],
    );
    assert!(
        first_page.status.success(),
        "{}",
        String::from_utf8_lossy(&first_page.stderr)
    );
    let first_page: Value = serde_json::from_slice(&first_page.stdout).expect("list JSON");
    assert_eq!(first_page["data"]["items"].as_array().unwrap().len(), 1);
    assert_eq!(first_page["data"]["items"][0]["id"], first_id);
    assert_eq!(first_page["meta"]["total"], 2);
    assert_eq!(first_page["meta"]["offset"], 0);
    assert_eq!(first_page["meta"]["limit"], 1);
    assert_eq!(first_page["meta"]["next_offset"], 1);
    assert_eq!(first_page["meta"]["truncated"], true);

    let second_page = run_list(
        &root,
        &repository,
        &store_dir,
        &["--repo", repo_arg, "--limit", "1", "--offset", "1"],
    );
    assert!(
        second_page.status.success(),
        "{}",
        String::from_utf8_lossy(&second_page.stderr)
    );
    let second_page: Value = serde_json::from_slice(&second_page.stdout).expect("list JSON");
    assert_eq!(second_page["data"]["items"].as_array().unwrap().len(), 1);
    assert_ne!(second_page["data"]["items"][0]["id"], first_id);
    assert_eq!(second_page["meta"]["next_offset"], Value::Null);
    assert_eq!(second_page["meta"]["truncated"], false);

    let text_match = run_list(
        &root,
        &repository,
        &store_dir,
        &[
            "--repo",
            repo_arg,
            "--source",
            "skill-a",
            "--text",
            "100%_path",
        ],
    );
    assert!(
        text_match.status.success(),
        "{}",
        String::from_utf8_lossy(&text_match.stderr)
    );
    let text_match: Value = serde_json::from_slice(&text_match.stdout).expect("list JSON");
    assert_eq!(text_match["data"]["items"].as_array().unwrap().len(), 1);
    assert_eq!(text_match["data"]["items"][0]["id"], first_id);

    let title_match = run_list(
        &root,
        &repository,
        &store_dir,
        &["--text", "NÉEDLE FRICTION", "--repo", repo_arg],
    );
    assert!(
        title_match.status.success(),
        "{}",
        String::from_utf8_lossy(&title_match.stderr)
    );
    let title_match: Value = serde_json::from_slice(&title_match.stdout).expect("list JSON");
    assert_eq!(title_match["data"]["items"].as_array().unwrap().len(), 1);
    assert_eq!(title_match["data"]["items"][0]["id"], first_id);

    let global_page = run_list(&root, &repository, &store_dir, &["--global"]);
    assert!(
        global_page.status.success(),
        "{}",
        String::from_utf8_lossy(&global_page.stderr)
    );
    let global_page: Value = serde_json::from_slice(&global_page.stdout).expect("list JSON");
    assert_eq!(global_page["data"]["items"].as_array().unwrap().len(), 1);
    assert_eq!(global_page["data"]["items"][0]["repo_root"], Value::Null);

    let conflict = run_list(
        &root,
        &repository,
        &store_dir,
        &["--repo", repo_arg, "--global"],
    );
    assert_eq!(conflict.status.code(), Some(2));
    let conflict: Value = serde_json::from_slice(&conflict.stderr).expect("error JSON");
    assert_eq!(conflict["data"]["error"]["code"], "store_invalid");

    let invalid_status = run_list(&root, &repository, &store_dir, &["--status", "waiting"]);
    assert_eq!(invalid_status.status.code(), Some(2));
    let invalid_status: Value = serde_json::from_slice(&invalid_status.stderr).expect("error JSON");
    assert_eq!(invalid_status["data"]["error"]["code"], "store_invalid");

    let oversized_page = run_list(&root, &repository, &store_dir, &["--limit", "1001"]);
    assert_eq!(oversized_page.status.code(), Some(2));
    let oversized_page: Value = serde_json::from_slice(&oversized_page.stderr).expect("error JSON");
    assert_eq!(oversized_page["data"]["error"]["code"], "store_invalid");
}

#[test]
fn show_resolves_id_or_slug_and_paginates_occurrences() {
    let root = TempDir::new().expect("temp root");
    let cwd = root.path().join("cwd");
    let store_dir = root.path().join("store");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    let created = run_add(
        &root,
        &cwd,
        &store_dir,
        &["--source", "tool", "--title", "Readable friction", "--json"],
        "First occurrence.\n",
    );
    assert!(
        created.status.success(),
        "{}",
        String::from_utf8_lossy(&created.stderr)
    );
    let created: Value = serde_json::from_slice(&created.stdout).expect("add JSON");
    let id = created["data"]["id"].as_i64().unwrap().to_string();
    let slug = created["data"]["slug"].as_str().unwrap();
    let appended = run_add(
        &root,
        &cwd,
        &store_dir,
        &["--item", &id],
        "Second occurrence.\n",
    );
    assert!(
        appended.status.success(),
        "{}",
        String::from_utf8_lossy(&appended.stderr)
    );

    let first_page = run_show(&root, &cwd, &store_dir, &id, &["--limit", "1"]);
    assert!(
        first_page.status.success(),
        "{}",
        String::from_utf8_lossy(&first_page.stderr)
    );
    let first_page: Value = serde_json::from_slice(&first_page.stdout).expect("show JSON");
    assert_eq!(first_page["data"]["item"]["id"], id.parse::<i64>().unwrap());
    assert_eq!(
        first_page["data"]["occurrences"].as_array().unwrap().len(),
        1
    );
    assert_eq!(first_page["meta"]["total"]["occurrences"], 2);
    assert_eq!(first_page["meta"]["total"]["status_changes"], 0);
    assert_eq!(first_page["meta"]["next_offset"], 1);
    assert_eq!(first_page["meta"]["truncated"], true);

    let second_page = run_show(
        &root,
        &cwd,
        &store_dir,
        slug,
        &["--limit", "1", "--offset", "1"],
    );
    assert!(
        second_page.status.success(),
        "{}",
        String::from_utf8_lossy(&second_page.stderr)
    );
    let second_page: Value = serde_json::from_slice(&second_page.stdout).expect("show JSON");
    assert_eq!(second_page["data"]["item"]["slug"], slug);
    assert_eq!(
        second_page["data"]["occurrences"].as_array().unwrap().len(),
        1
    );
    assert_eq!(second_page["meta"]["next_offset"], Value::Null);
    assert_eq!(second_page["meta"]["truncated"], false);

    let numeric = run_add(
        &root,
        &cwd,
        &store_dir,
        &["--source", "tool", "--title", "123", "--json"],
        "Numeric title remains addressable by slug.\n",
    );
    assert!(
        numeric.status.success(),
        "{}",
        String::from_utf8_lossy(&numeric.stderr)
    );
    let numeric: Value = serde_json::from_slice(&numeric.stdout).expect("numeric add JSON");
    assert_eq!(numeric["data"]["slug"], "friction-123");
    let numeric_show = run_show(&root, &cwd, &store_dir, "friction-123", &[]);
    assert!(
        numeric_show.status.success(),
        "{}",
        String::from_utf8_lossy(&numeric_show.stderr)
    );

    let missing = run_show(&root, &cwd, &store_dir, "not-a-real-item", &[]);
    assert_eq!(missing.status.code(), Some(2));
    let missing: Value = serde_json::from_slice(&missing.stderr).expect("error JSON");
    assert_eq!(missing["data"]["error"]["code"], "store_item_not_found");
}

#[test]
fn set_status_records_repeated_and_concurrent_audit_events() {
    let root = TempDir::new().expect("temp root");
    let cwd = root.path().join("cwd");
    let store_dir = root.path().join("store");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    let created = run_add(
        &root,
        &cwd,
        &store_dir,
        &["--source", "tool", "--title", "Auditable status", "--json"],
        "Status transition evidence.\n",
    );
    assert!(
        created.status.success(),
        "{}",
        String::from_utf8_lossy(&created.stderr)
    );
    let created: Value = serde_json::from_slice(&created.stdout).expect("add JSON");
    let id = created["data"]["id"].as_i64().unwrap().to_string();

    for reason in ["first resolution", "repeat resolution"] {
        let changed = run_set_status(&root, &cwd, &store_dir, &id, "resolved", reason);
        assert!(
            changed.status.success(),
            "{}",
            String::from_utf8_lossy(&changed.stderr)
        );
    }

    let first_show = run_show(&root, &cwd, &store_dir, &id, &[]);
    assert!(
        first_show.status.success(),
        "{}",
        String::from_utf8_lossy(&first_show.stderr)
    );
    let first_show: Value = serde_json::from_slice(&first_show.stdout).expect("show JSON");
    let history = first_show["data"]["status_changes"].as_array().unwrap();
    assert_eq!(first_show["data"]["item"]["status"], "resolved");
    assert_eq!(history.len(), 2);
    assert_eq!(history[0]["from_status"], "open");
    assert_eq!(history[0]["to_status"], "resolved");
    assert_eq!(history[0]["reason"], "first resolution");
    assert_eq!(history[1]["from_status"], "resolved");
    assert_eq!(history[1]["to_status"], "resolved");
    assert_eq!(history[1]["reason"], "repeat resolution");

    let first = spawn_set_status(&root, &cwd, &store_dir, &id, "promoted", "promotion");
    let second = spawn_set_status(&root, &cwd, &store_dir, &id, "archived", "archive");
    let first = first
        .wait_with_output()
        .expect("wait for first status update");
    let second = second
        .wait_with_output()
        .expect("wait for second status update");
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    assert!(
        second.status.success(),
        "{}",
        String::from_utf8_lossy(&second.stderr)
    );

    let final_show = run_show(&root, &cwd, &store_dir, &id, &[]);
    assert!(
        final_show.status.success(),
        "{}",
        String::from_utf8_lossy(&final_show.stderr)
    );
    let final_show: Value = serde_json::from_slice(&final_show.stdout).expect("show JSON");
    let history = final_show["data"]["status_changes"].as_array().unwrap();
    assert_eq!(history.len(), 4);
    assert_eq!(history[2]["to_status"], history[3]["from_status"]);
    assert_eq!(
        final_show["data"]["item"]["status"],
        history[3]["to_status"]
    );
}

#[test]
fn set_status_rejects_blank_reasons_invalid_statuses_and_missing_items() {
    let root = TempDir::new().expect("temp root");
    let cwd = root.path().join("cwd");
    let store_dir = root.path().join("store");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    let created = run_add(
        &root,
        &cwd,
        &store_dir,
        &["--source", "tool", "--title", "Validated status", "--json"],
        "Status validation evidence.\n",
    );
    assert!(
        created.status.success(),
        "{}",
        String::from_utf8_lossy(&created.stderr)
    );
    let created: Value = serde_json::from_slice(&created.stdout).expect("add JSON");
    let id = created["data"]["id"].as_i64().unwrap().to_string();

    for (identifier, status, reason, expected_error) in [
        (id.as_str(), "resolved", "   ", "store_invalid"),
        (id.as_str(), "waiting", "valid reason", "store_invalid"),
        ("999", "resolved", "valid reason", "store_item_not_found"),
    ] {
        let result = run_set_status(&root, &cwd, &store_dir, identifier, status, reason);
        assert_eq!(result.status.code(), Some(2));
        let error: Value = serde_json::from_slice(&result.stderr).expect("error JSON");
        assert_eq!(error["data"]["error"]["code"], expected_error);
    }

    let unchanged = run_show(&root, &cwd, &store_dir, &id, &[]);
    assert!(
        unchanged.status.success(),
        "{}",
        String::from_utf8_lossy(&unchanged.stderr)
    );
    let unchanged: Value = serde_json::from_slice(&unchanged.stdout).expect("show JSON");
    assert_eq!(unchanged["data"]["item"]["status"], "open");
    assert_eq!(unchanged["meta"]["total"]["status_changes"], 0);
}

#[test]
fn export_writes_deterministic_yaml_and_preserves_unrelated_entries() {
    let root = TempDir::new().expect("temp root");
    let cwd = init_test_repository(&root.path().join("repository"));
    let store_dir = root.path().join("store");
    let export_dir = root.path().join("export");
    let repeat_export_dir = root.path().join("repeat-export");
    let title = "First: \"quoted\"\nline";
    let first_evidence = "Evidence: \"quoted\"\nsecond line with \\\\ and ```";
    let reason = "resolved: \"approved\"\nby review";
    let first = run_add(
        &root,
        &cwd,
        &store_dir,
        &[
            "--source",
            "tool: \"source\"",
            "--title",
            title,
            "--target",
            "src/file.rs",
            "--json",
        ],
        first_evidence,
    );
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    let first: Value = serde_json::from_slice(&first.stdout).expect("add JSON");
    let first_id = first["data"]["id"].as_i64().unwrap().to_string();
    let first_slug = first["data"]["slug"].as_str().unwrap();
    assert!(!first_slug.contains('/'));
    assert!(!first_slug.contains('\\'));

    let appended_evidence = "Second occurrence\nwith another line";
    let appended = run_add(
        &root,
        &cwd,
        &store_dir,
        &["--item", &first_id],
        appended_evidence,
    );
    assert!(
        appended.status.success(),
        "{}",
        String::from_utf8_lossy(&appended.stderr)
    );
    let status = run_set_status(&root, &cwd, &store_dir, &first_id, "resolved", reason);
    assert!(
        status.status.success(),
        "{}",
        String::from_utf8_lossy(&status.stderr)
    );

    let second = run_add(
        &root,
        &cwd,
        &store_dir,
        &[
            "--source",
            "skill",
            "--title",
            "Global item",
            "--global",
            "--json",
        ],
        "Global evidence.\n",
    );
    assert!(
        second.status.success(),
        "{}",
        String::from_utf8_lossy(&second.stderr)
    );
    let second: Value = serde_json::from_slice(&second.stdout).expect("add JSON");
    let second_slug = second["data"]["slug"].as_str().unwrap();

    std::fs::create_dir(&export_dir).expect("create export directory");
    let unrelated_file = export_dir.join("keep.txt");
    std::fs::write(&unrelated_file, "keep this file\n").expect("write unrelated file");
    let link_target = root.path().join("link-target.txt");
    std::fs::write(&link_target, "keep symlink target\n").expect("write symlink target");
    let unrelated_link = export_dir.join("keep-link");
    std::os::unix::fs::symlink(&link_target, &unrelated_link).expect("create unrelated symlink");

    for destination in [&export_dir, &repeat_export_dir] {
        let exported = run_export(&root, &cwd, &store_dir, destination);
        assert!(
            exported.status.success(),
            "{}",
            String::from_utf8_lossy(&exported.stderr)
        );
        let exported: Value = serde_json::from_slice(&exported.stdout).expect("export JSON");
        assert_eq!(exported["data"]["exported"], 2);
        assert_eq!(exported["meta"]["truncated"], false);
    }

    let first_file = format!("{first_slug}.md");
    let first_content =
        std::fs::read_to_string(export_dir.join(&first_file)).expect("first export");
    assert!(first_content.starts_with("---\nformat: \"varde-friction-item\"\nversion: 1\n"));
    assert!(first_content.contains(&format!(
        "title: {}\n",
        serde_json::to_string(title).unwrap()
    )));
    assert!(first_content.contains(&format!(
        "source: {}\n",
        serde_json::to_string("tool: \"source\"").unwrap()
    )));
    assert!(first_content.contains(&format!(
        "repo_root: {}\n",
        serde_json::to_string(cwd.to_str().unwrap()).unwrap()
    )));
    assert!(first_content.contains(&format!(
        "evidence: {}\n",
        serde_json::to_string(first_evidence).unwrap()
    )));
    assert!(first_content.contains(&format!(
        "reason: {}\n",
        serde_json::to_string(reason).unwrap()
    )));
    assert!(first_content.contains("status: \"resolved\"\n"));
    assert!(first_content.contains("repo_root: "));
    assert!(first_content.contains("## Occurrences"));
    assert!(first_content.contains("## Status history"));
    assert!(first_content.contains("Second occurrence"));
    assert!(first_content.contains("````text\nEvidence: \"quoted\""));

    let second_file = format!("{second_slug}.md");
    let second_content =
        std::fs::read_to_string(export_dir.join(&second_file)).expect("second export");
    assert!(second_content.contains("repo_root: null\n"));
    assert!(second_content.contains("Global evidence."));
    assert_eq!(
        first_content,
        std::fs::read_to_string(repeat_export_dir.join(&first_file)).expect("repeat first export")
    );
    assert_eq!(
        second_content,
        std::fs::read_to_string(repeat_export_dir.join(&second_file))
            .expect("repeat second export")
    );
    assert_eq!(
        std::fs::read_to_string(&unrelated_file).unwrap(),
        "keep this file\n"
    );
    assert!(
        std::fs::symlink_metadata(&unrelated_link)
            .expect("read unrelated symlink metadata")
            .file_type()
            .is_symlink()
    );
    assert_eq!(std::fs::read_link(&unrelated_link).unwrap(), link_target);

    let collision_dir = root.path().join("collision-export");
    std::fs::create_dir(&collision_dir).expect("create collision directory");
    let collision_target = root.path().join("collision-target.txt");
    std::fs::write(&collision_target, "preserve collision target\n")
        .expect("write collision target");
    std::os::unix::fs::symlink(&collision_target, collision_dir.join(&first_file))
        .expect("create colliding symlink");
    let collision = run_export(&root, &cwd, &store_dir, &collision_dir);
    assert_eq!(collision.status.code(), Some(2));
    let collision: Value = serde_json::from_slice(&collision.stderr).expect("error JSON");
    assert_eq!(collision["data"]["error"]["code"], "store_invalid");
    assert_eq!(
        std::fs::read_to_string(&collision_target).unwrap(),
        "preserve collision target\n"
    );
    assert!(
        std::fs::symlink_metadata(collision_dir.join(&first_file))
            .expect("read collision symlink metadata")
            .file_type()
            .is_symlink()
    );
    assert_eq!(std::fs::read_dir(&collision_dir).unwrap().count(), 1);
}

#[test]
fn export_import_preserves_unicode_nel_in_yaml_strings() {
    let root = TempDir::new().expect("temp root");
    let cwd = init_test_repository(&root.path().join("repository"));
    let store_dir = root.path().join("store");
    let title = "Title\u{0085}part";
    let source = "varde-review\u{0085}tool";
    let target = "src/file\u{0085}.rs";
    let evidence = "before\u{0085}middle\u{2028}line\u{2029}end";
    let reason = "reason\u{0085}middle\u{2028}line\u{2029}end";

    let added = run_add(
        &root,
        &cwd,
        &store_dir,
        &[
            "--source", source, "--title", title, "--target", target, "--json",
        ],
        evidence,
    );
    assert!(
        added.status.success(),
        "{}",
        String::from_utf8_lossy(&added.stderr)
    );
    let added: Value = serde_json::from_slice(&added.stdout).expect("add JSON");
    let id = added["data"]["id"].as_i64().unwrap().to_string();
    let status = run_set_status(&root, &cwd, &store_dir, &id, "resolved", reason);
    assert!(
        status.status.success(),
        "{}",
        String::from_utf8_lossy(&status.stderr)
    );

    let export_dir = root.path().join("export");
    let exported = run_export(&root, &cwd, &store_dir, &export_dir);
    assert!(exported.status.success());

    let restored_store = root.path().join("restored-store");
    let restored = run_import(&root, &cwd, &restored_store, &export_dir, &cwd, &["--json"]);
    assert!(
        restored.status.success(),
        "{}",
        String::from_utf8_lossy(&restored.stderr)
    );
    let restored: Value = serde_json::from_slice(&restored.stdout).expect("restore JSON");
    assert_eq!(restored["data"]["summary"]["imported"], 1);
    let restored_id = restored["data"]["results"][0]["id"]
        .as_i64()
        .unwrap()
        .to_string();
    let item = run_show(&root, &cwd, &restored_store, &restored_id, &[]);
    assert!(item.status.success());
    let item: Value = serde_json::from_slice(&item.stdout).expect("restored show JSON");
    assert_eq!(item["data"]["item"]["title"], title);
    assert_eq!(item["data"]["item"]["source"], source);
    assert_eq!(item["data"]["item"]["target"], target);
    assert_eq!(item["data"]["occurrences"][0]["evidence"], evidence);
    assert_eq!(item["data"]["status_changes"][0]["reason"], reason);
}

#[test]
fn import_handles_mixed_legacy_and_export_files_with_dry_run_and_reimport() {
    let root = TempDir::new().expect("temp root");
    let cwd = init_test_repository(&root.path().join("repository"));
    let source_dir = root.path().join("legacy-friction");
    std::fs::create_dir(&source_dir).expect("create import directory");
    let legacy_body = "Legacy report with no title or source metadata.\nSecond evidence line.\n";
    std::fs::write(
        source_dir.join("legacy-no-source.md"),
        format!("---\ntype: friction\ndate: 2026-09-25\nhead_sha: abc123\n---\n\n{legacy_body}"),
    )
    .expect("write source-less legacy file");
    let tool_body = "A tool sourced report.\n";
    std::fs::write(
        source_dir.join("legacy-tool-source.md"),
        format!(
            "---\ntype: friction-item\ntool: varde-tool\nstatus: promoted\ncreated: 2026-09-17\n---\n\n# Tool-sourced friction\n\n{tool_body}"
        ),
    )
    .expect("write tool-source legacy file");

    let structured_title = "Structured: \"quoted\" title";
    let structured_evidence = "Imported evidence\nwith YAML: [special]";
    let structured_reason = "Reviewed: \"approved\"";
    let structured = format!(
        "---\nformat: \"varde-friction-item\"\nversion: 1\nid: 900\nslug: \"round-trip\"\ntitle: {}\nsource: \"varde-review\"\nrepo_root: null\nstatus: \"resolved\"\ntarget: null\ncreated_at: \"2026-09-20T12:00:00Z\"\noccurrences:\n  - id: 901\n    item_id: 900\n    at: \"2026-09-20T12:01:00Z\"\n    cwd: \"/tmp/old-project\"\n    repo_root: null\n    head_sha: \"deadbeef\"\n    evidence: {}\n    cost: null\nstatus_changes:\n  - id: 902\n    item_id: 900\n    at: \"2026-09-20T12:02:00Z\"\n    from_status: \"open\"\n    to_status: \"resolved\"\n    reason: {}\n---\n\n# Readable export body\n",
        serde_json::to_string(structured_title).unwrap(),
        serde_json::to_string(structured_evidence).unwrap(),
        serde_json::to_string(structured_reason).unwrap(),
    );
    std::fs::write(source_dir.join("round-trip.md"), structured)
        .expect("write structured export file");
    std::fs::write(
        source_dir.join("untyped.md"),
        "---\ntitle: not a friction item\n---\n\nNo type marker.\n",
    )
    .expect("write untyped file");
    std::fs::write(
        source_dir.join("malformed.md"),
        "---\ntype: [broken\n---\n\nMalformed YAML.\n",
    )
    .expect("write malformed file");
    std::fs::write(
        source_dir.join("invalid-status.md"),
        "---\ntype: friction\nsource: varde-review\nstatus: waiting\n---\n\nInvalid status.\n",
    )
    .expect("write invalid-status file");

    let dry_store = root.path().join("dry-run-store");
    let dry_run = run_import(
        &root,
        &cwd,
        &dry_store,
        &source_dir,
        &cwd,
        &["--dry-run", "--json"],
    );
    assert!(
        dry_run.status.success(),
        "{}",
        String::from_utf8_lossy(&dry_run.stderr)
    );
    let dry_run: Value = serde_json::from_slice(&dry_run.stdout).expect("dry-run JSON");
    assert_eq!(dry_run["data"]["summary"]["total"], 6);
    assert_eq!(dry_run["data"]["summary"]["would_import"], 3);
    assert_eq!(dry_run["data"]["summary"]["skipped"], 3);
    assert_eq!(dry_run["data"]["results"].as_array().unwrap().len(), 6);
    assert_eq!(dry_run["meta"]["truncated"], false);
    assert!(!dry_store.exists(), "dry-run must not create the store");
    let results = dry_run["data"]["results"].as_array().unwrap();
    let legacy_result = results
        .iter()
        .find(|result| result["file"] == "legacy-no-source.md")
        .unwrap();
    assert_eq!(legacy_result["outcome"], "would_import");
    assert_eq!(legacy_result["slug"], "legacy-no-source");
    assert_eq!(legacy_result["title"], "Legacy No Source");
    assert_eq!(legacy_result["source"], "legacy-import");
    assert_eq!(legacy_result["status"], "open");
    assert!(results.iter().any(|result| {
        result["file"] == "untyped.md"
            && result["outcome"] == "skipped"
            && result["reason"].as_str().unwrap().contains("type")
    }));

    let store_dir = root.path().join("import-store");
    let imported = run_import(&root, &cwd, &store_dir, &source_dir, &cwd, &["--json"]);
    assert!(
        imported.status.success(),
        "{}",
        String::from_utf8_lossy(&imported.stderr)
    );
    let imported: Value = serde_json::from_slice(&imported.stdout).expect("import JSON");
    assert_eq!(imported["data"]["summary"]["imported"], 3);
    assert_eq!(imported["data"]["summary"]["skipped"], 3);
    assert_eq!(imported["data"]["summary"]["total"], 6);

    let legacy_id = imported["data"]["results"]
        .as_array()
        .unwrap()
        .iter()
        .find(|result| result["file"] == "legacy-no-source.md")
        .unwrap()["id"]
        .as_i64()
        .unwrap()
        .to_string();
    let legacy_show = run_show(&root, &cwd, &store_dir, &legacy_id, &[]);
    assert!(
        legacy_show.status.success(),
        "{}",
        String::from_utf8_lossy(&legacy_show.stderr)
    );
    let legacy_show: Value = serde_json::from_slice(&legacy_show.stdout).expect("legacy show JSON");
    assert_eq!(legacy_show["data"]["item"]["title"], "Legacy No Source");
    assert_eq!(legacy_show["data"]["item"]["source"], "legacy-import");
    assert_eq!(legacy_show["data"]["item"]["status"], "open");
    assert_eq!(
        legacy_show["data"]["item"]["repo_root"],
        cwd.to_str().unwrap()
    );
    assert!(
        legacy_show["data"]["occurrences"][0]["evidence"]
            .as_str()
            .unwrap()
            .contains(legacy_body.trim())
    );
    assert_eq!(legacy_show["data"]["occurrences"][0]["head_sha"], "abc123");

    let structured_id = imported["data"]["results"]
        .as_array()
        .unwrap()
        .iter()
        .find(|result| result["file"] == "round-trip.md")
        .unwrap()["id"]
        .as_i64()
        .unwrap()
        .to_string();
    let structured_show = run_show(&root, &cwd, &store_dir, &structured_id, &[]);
    assert!(
        structured_show.status.success(),
        "{}",
        String::from_utf8_lossy(&structured_show.stderr)
    );
    let structured_show: Value =
        serde_json::from_slice(&structured_show.stdout).expect("structured show JSON");
    assert_eq!(structured_show["data"]["item"]["title"], structured_title);
    assert_eq!(structured_show["data"]["item"]["status"], "resolved");
    assert_eq!(structured_show["data"]["item"]["repo_root"], Value::Null);
    assert_eq!(
        structured_show["data"]["occurrences"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        structured_show["data"]["occurrences"][0]["evidence"],
        structured_evidence
    );
    assert_eq!(
        structured_show["data"]["status_changes"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        structured_show["data"]["status_changes"][0]["reason"],
        structured_reason
    );

    let repeated = run_import(&root, &cwd, &store_dir, &source_dir, &cwd, &["--json"]);
    assert!(
        repeated.status.success(),
        "{}",
        String::from_utf8_lossy(&repeated.stderr)
    );
    let repeated: Value = serde_json::from_slice(&repeated.stdout).expect("reimport JSON");
    assert_eq!(repeated["data"]["summary"]["imported"], 0);
    assert_eq!(repeated["data"]["summary"]["skipped"], 6);
    assert!(
        repeated["data"]["results"]
            .as_array()
            .unwrap()
            .iter()
            .any(|result| {
                result["file"] == "round-trip.md"
                    && result["outcome"] == "skipped"
                    && result["reason"]
                        .as_str()
                        .unwrap()
                        .contains("already exists")
            })
    );
}

#[test]
fn legacy_import_skips_blank_cwd_and_remaining_records_round_trip() {
    let root = TempDir::new().expect("temp root");
    let cwd = root.path().join("project");
    let source_dir = root.path().join("legacy-friction");
    std::fs::create_dir_all(&cwd).expect("create project directory");
    std::fs::create_dir(&source_dir).expect("create legacy friction directory");
    std::fs::write(
        source_dir.join("blank-cwd.md"),
        "---\ntype: friction-item\nsource: varde-review\ntitle: Blank cwd\ncwd: ''\n---\n\nInvalid evidence.\n",
    )
    .expect("write invalid legacy friction");
    let evidence = "Valid legacy evidence.";
    std::fs::write(
        source_dir.join("valid.md"),
        format!(
            "---\ntype: friction-item\nsource: varde-review\ntitle: Valid record\nstatus: resolved\ncwd: /legacy/project\n---\n\n{evidence}\n"
        ),
    )
    .expect("write valid legacy friction");

    let store_dir = root.path().join("import-store");
    let imported = run_import(&root, &cwd, &store_dir, &source_dir, &cwd, &["--json"]);
    assert!(
        imported.status.success(),
        "{}",
        String::from_utf8_lossy(&imported.stderr)
    );
    let imported: Value = serde_json::from_slice(&imported.stdout).expect("import JSON");
    assert_eq!(imported["data"]["summary"]["imported"], 1);
    assert_eq!(imported["data"]["summary"]["skipped"], 1);
    let results = imported["data"]["results"].as_array().unwrap();
    let invalid = results
        .iter()
        .find(|result| result["file"] == "blank-cwd.md")
        .unwrap();
    assert_eq!(invalid["outcome"], "skipped");
    assert!(
        invalid["reason"]
            .as_str()
            .unwrap()
            .contains("`cwd` must not be blank")
    );
    let valid_id = results
        .iter()
        .find(|result| result["file"] == "valid.md")
        .unwrap()["id"]
        .as_i64()
        .unwrap()
        .to_string();

    let export_dir = root.path().join("export");
    let exported = run_export(&root, &cwd, &store_dir, &export_dir);
    assert!(
        exported.status.success(),
        "{}",
        String::from_utf8_lossy(&exported.stderr)
    );
    assert!(!export_dir.join("blank-cwd.md").exists());
    let restored_store = root.path().join("restored-store");
    let restored = run_import(&root, &cwd, &restored_store, &export_dir, &cwd, &["--json"]);
    assert!(
        restored.status.success(),
        "{}",
        String::from_utf8_lossy(&restored.stderr)
    );
    let restored: Value = serde_json::from_slice(&restored.stdout).expect("restore JSON");
    assert_eq!(restored["data"]["summary"]["imported"], 1);
    let restored_id = restored["data"]["results"][0]["id"]
        .as_i64()
        .unwrap()
        .to_string();
    let restored_item = run_show(&root, &cwd, &restored_store, &restored_id, &[]);
    assert!(restored_item.status.success());
    let restored_item: Value =
        serde_json::from_slice(&restored_item.stdout).expect("restored show JSON");
    assert_eq!(restored_item["data"]["item"]["status"], "resolved");
    assert_eq!(
        restored_item["data"]["occurrences"][0]["cwd"],
        "/legacy/project"
    );
    assert_eq!(
        restored_item["data"]["occurrences"][0]["evidence"],
        evidence
    );
    assert!(
        store_dir.join("learn.db").is_file(),
        "the valid legacy item must be imported"
    );
    assert!(!store_dir.join("valid.md").exists());
    let original = run_show(&root, &cwd, &store_dir, &valid_id, &[]);
    assert!(original.status.success());
}

#[test]
fn import_dry_run_checks_store_path_and_reports_nonregular_markdown() {
    let root = TempDir::new().expect("temp root");
    let cwd = init_test_repository(&root.path().join("repository"));
    let source_dir = root.path().join("import-source");
    std::fs::create_dir(&source_dir).expect("create source directory");
    let target = root.path().join("outside.md");
    std::fs::write(&target, "do not follow this symlink\n").expect("write symlink target");
    #[cfg(unix)]
    std::os::unix::fs::symlink(&target, source_dir.join("linked.md"))
        .expect("create Markdown symlink");
    std::fs::create_dir(source_dir.join("nested.md")).expect("create Markdown directory");

    let store_dir = root.path().join("safe-store");
    let report = run_import(
        &root,
        &cwd,
        &store_dir,
        &source_dir,
        &cwd,
        &["--dry-run", "--json"],
    );
    assert!(
        report.status.success(),
        "{}",
        String::from_utf8_lossy(&report.stderr)
    );
    let report: Value = serde_json::from_slice(&report.stdout).expect("import report JSON");
    #[cfg(unix)]
    assert_eq!(report["data"]["summary"]["total"], 2);
    #[cfg(not(unix))]
    assert_eq!(report["data"]["summary"]["total"], 1);
    assert_eq!(
        report["data"]["summary"]["skipped"],
        report["data"]["summary"]["total"]
    );
    assert!(!store_dir.exists());

    let unsafe_store = cwd.join("learn-store");
    let rejected = run_import(
        &root,
        &cwd,
        &unsafe_store,
        &source_dir,
        &cwd,
        &["--dry-run", "--json"],
    );
    assert_eq!(rejected.status.code(), Some(2));
    let error: Value = serde_json::from_slice(&rejected.stderr).expect("error JSON");
    assert_eq!(error["data"]["error"]["code"], "store_inside_git");
    assert!(!unsafe_store.exists());
}

#[test]
fn adoption_record_promotes_multiple_items_and_invalid_inputs_do_not_partially_apply() {
    let root = TempDir::new().expect("temp root");
    let cwd = root.path().join("outside-git");
    std::fs::create_dir(&cwd).expect("create outside-Git cwd");
    let store_dir = root.path().join("adoption-store");
    let first = run_add(
        &root,
        &cwd,
        &store_dir,
        &[
            "--source",
            "varde-change",
            "--title",
            "First obstacle",
            "--global",
            "--json",
        ],
        "first occurrence evidence",
    );
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    let first: Value = serde_json::from_slice(&first.stdout).expect("first add JSON");
    let first_id = first["data"]["id"].as_i64().expect("first item ID");
    let second = run_add(
        &root,
        &cwd,
        &store_dir,
        &[
            "--source",
            "varde-change",
            "--title",
            "Second obstacle",
            "--global",
            "--json",
        ],
        "second occurrence evidence",
    );
    assert!(
        second.status.success(),
        "{}",
        String::from_utf8_lossy(&second.stderr)
    );
    let second: Value = serde_json::from_slice(&second.stdout).expect("second add JSON");
    let second_id = second["data"]["id"].as_i64().expect("second item ID");

    let before = root.path().join("before.json");
    let after = root.path().join("after.json");
    std::fs::write(&before, r#"{"score":0.5,"cases":["same"]}"#).expect("write baseline");
    std::fs::write(&after, r#"{"score":0.9,"cases":["same"]}"#).expect("write after result");
    let before_path = before.to_str().expect("baseline path");
    let after_path = after.to_str().expect("after path");
    let ids = format!("{first_id},{second_id}");
    let record = run_adopt_record(
        &root,
        &cwd,
        &store_dir,
        &[
            "--items",
            &ids,
            "--summary",
            "Use the configured learn store path",
            "--files",
            "learn-cli/src/friction.rs,skills/varde-learn/SKILL.md",
            "--commit",
            "0123456789abcdef",
            "--eval-before",
            before_path,
            "--eval-after",
            after_path,
        ],
    );
    assert!(
        record.status.success(),
        "{}",
        String::from_utf8_lossy(&record.stderr)
    );
    let record: Value = serde_json::from_slice(&record.stdout).expect("adoption JSON");
    let adoption_id = record["data"]["adoption_id"].as_i64().expect("adoption ID");
    assert_eq!(
        record["data"]["items"],
        serde_json::json!([first_id, second_id])
    );

    for id in [first_id, second_id] {
        let shown = run_show(&root, &cwd, &store_dir, &id.to_string(), &[]);
        assert!(
            shown.status.success(),
            "{}",
            String::from_utf8_lossy(&shown.stderr)
        );
        let shown: Value = serde_json::from_slice(&shown.stdout).expect("show JSON");
        assert_eq!(shown["data"]["item"]["status"], "promoted");
        assert_eq!(shown["data"]["status_changes"].as_array().unwrap().len(), 1);
        assert_eq!(shown["data"]["status_changes"][0]["from_status"], "open");
        assert_eq!(shown["data"]["status_changes"][0]["to_status"], "promoted");
        assert!(
            shown["data"]["status_changes"][0]["reason"]
                .as_str()
                .unwrap()
                .contains(&adoption_id.to_string())
        );
    }

    let invalid_ids = format!("{first_id},999999");
    let missing = run_adopt_record(
        &root,
        &cwd,
        &store_dir,
        &[
            "--items",
            &invalid_ids,
            "--summary",
            "This must roll back",
            "--files",
            "skills/varde-learn/SKILL.md",
        ],
    );
    assert_eq!(missing.status.code(), Some(2));
    let missing: Value = serde_json::from_slice(&missing.stderr).expect("missing ID error JSON");
    assert_eq!(missing["data"]["error"]["code"], "store_item_not_found");

    let invalid_eval = root.path().join("invalid.json");
    std::fs::write(&invalid_eval, "not JSON").expect("write invalid benchmark");
    let invalid_eval_path = invalid_eval.to_str().expect("invalid benchmark path");
    let rejected = run_adopt_record(
        &root,
        &cwd,
        &store_dir,
        &[
            "--items",
            &first_id.to_string(),
            "--summary",
            "This input is invalid",
            "--files",
            "skills/varde-learn/SKILL.md",
            "--eval-before",
            invalid_eval_path,
        ],
    );
    assert_eq!(rejected.status.code(), Some(2));
    let rejected: Value =
        serde_json::from_slice(&rejected.stderr).expect("invalid eval error JSON");
    assert_eq!(rejected["data"]["error"]["code"], "store_invalid");

    let shown = run_show(&root, &cwd, &store_dir, &first_id.to_string(), &[]);
    let shown: Value = serde_json::from_slice(&shown.stdout).expect("unchanged show JSON");
    assert_eq!(shown["data"]["item"]["status"], "promoted");
    assert_eq!(shown["data"]["status_changes"].as_array().unwrap().len(), 1);
}

#[test]
fn adoption_recurrence_reports_later_occurrence_with_adoption_context() {
    let root = TempDir::new().expect("temp root");
    let cwd = root.path().join("outside-git");
    std::fs::create_dir(&cwd).expect("create outside-Git cwd");
    let store_dir = root.path().join("adoption-store");
    let created = run_add(
        &root,
        &cwd,
        &store_dir,
        &[
            "--source",
            "varde-change",
            "--title",
            "Configured learn store path",
            "--global",
            "--json",
        ],
        "The configured store path is unclear.",
    );
    assert!(
        created.status.success(),
        "{}",
        String::from_utf8_lossy(&created.stderr)
    );
    let created: Value = serde_json::from_slice(&created.stdout).expect("add JSON");
    let item_id = created["data"]["id"].as_i64().expect("friction item ID");
    let item_id_arg = item_id.to_string();
    let adoption = run_adopt_record(
        &root,
        &cwd,
        &store_dir,
        &[
            "--items",
            &item_id_arg,
            "--summary",
            "Document the configured learn store path",
            "--files",
            "skills/varde-learn/SKILL.md",
        ],
    );
    assert!(
        adoption.status.success(),
        "{}",
        String::from_utf8_lossy(&adoption.stderr)
    );
    let adoption: Value = serde_json::from_slice(&adoption.stdout).expect("adoption JSON");
    let adoption_id = adoption["data"]["adoption_id"]
        .as_i64()
        .expect("adoption ID");

    let later = run_add(
        &root,
        &cwd,
        &store_dir,
        &["--item", &item_id_arg, "--json"],
        "The configured path still surprised me.",
    );
    assert!(
        later.status.success(),
        "{}",
        String::from_utf8_lossy(&later.stderr)
    );
    let recurrence = run_adopt_recurrence(&root, &cwd, &store_dir, &[]);
    assert!(
        recurrence.status.success(),
        "{}",
        String::from_utf8_lossy(&recurrence.stderr)
    );
    let recurrence: Value = serde_json::from_slice(&recurrence.stdout).expect("recurrence JSON");
    assert_eq!(recurrence["data"]["items"].as_array().unwrap().len(), 1);
    let row = &recurrence["data"]["items"][0];
    assert_eq!(row["adoption_id"], adoption_id);
    assert_eq!(row["summary"], "Document the configured learn store path");
    assert_eq!(row["item"]["id"], item_id);
    assert_eq!(
        row["occurrence"]["evidence"],
        "The configured path still surprised me."
    );
    assert_eq!(recurrence["meta"]["total"], 1);
    assert_eq!(recurrence["meta"]["truncated"], false);
    assert_eq!(recurrence["meta"]["skipped_invalid_timestamps"], 0);
}

#[test]
fn adoption_recurrence_skips_imported_relative_timestamp_but_keeps_fixed_date() {
    let root = TempDir::new().expect("temp root");
    let cwd = root.path().join("project");
    let source_dir = root.path().join("legacy-friction");
    std::fs::create_dir_all(&cwd).expect("create project directory");
    std::fs::create_dir(&source_dir).expect("create legacy friction directory");
    std::fs::write(
        source_dir.join("future-date.md"),
        "---\ntype: friction-item\nsource: varde-review\ntitle: Imported date-only occurrence\ndate: 2099-01-01\ncwd: /legacy/project\n---\n\nThe old record stored a date without a time.\n",
    )
    .expect("write legacy friction file");
    std::fs::write(
        source_dir.join("relative-now.md"),
        "---\ntype: friction-item\nsource: varde-review\ntitle: Imported relative timestamp\ndate: now\ncwd: /legacy/project\n---\n\nThis legacy timestamp is relative, not recorded evidence.\n",
    )
    .expect("write relative-timestamp legacy friction file");

    let store_dir = root.path().join("adoption-store");
    let imported = run_import(&root, &cwd, &store_dir, &source_dir, &cwd, &["--json"]);
    assert!(
        imported.status.success(),
        "{}",
        String::from_utf8_lossy(&imported.stderr)
    );
    let imported: Value = serde_json::from_slice(&imported.stdout).expect("import JSON");
    assert_eq!(imported["data"]["summary"]["imported"], 2);
    let results = imported["data"]["results"].as_array().unwrap();
    let date_item_id = results
        .iter()
        .find(|result| result["file"] == "future-date.md")
        .unwrap()["id"]
        .as_i64()
        .expect("imported date-only item ID");
    let relative_item_id = results
        .iter()
        .find(|result| result["file"] == "relative-now.md")
        .unwrap()["id"]
        .as_i64()
        .expect("imported relative-timestamp item ID");
    let item_ids_arg = format!("{date_item_id},{relative_item_id}");
    let adoption = run_adopt_record(
        &root,
        &cwd,
        &store_dir,
        &[
            "--items",
            &item_ids_arg,
            "--summary",
            "Document legacy occurrence timestamps",
            "--files",
            "skills/varde-learn/references/recurrence.md",
        ],
    );
    assert!(
        adoption.status.success(),
        "{}",
        String::from_utf8_lossy(&adoption.stderr)
    );
    let adoption: Value = serde_json::from_slice(&adoption.stdout).expect("adoption JSON");
    let adoption_id = adoption["data"]["adoption_id"]
        .as_i64()
        .expect("adoption ID");

    let recurrence = run_adopt_recurrence(&root, &cwd, &store_dir, &[]);
    assert!(
        recurrence.status.success(),
        "{}",
        String::from_utf8_lossy(&recurrence.stderr)
    );
    let recurrence: Value = serde_json::from_slice(&recurrence.stdout).expect("recurrence JSON");
    assert_eq!(recurrence["data"]["items"].as_array().unwrap().len(), 1);
    let row = &recurrence["data"]["items"][0];
    assert_eq!(row["adoption_id"], adoption_id);
    assert_eq!(row["item"]["id"], date_item_id);
    assert_eq!(row["occurrence"]["at"], "2099-01-01");
    assert_eq!(
        row["occurrence"]["evidence"],
        "The old record stored a date without a time."
    );
    assert_eq!(recurrence["meta"]["skipped_invalid_timestamps"], 1);
}
