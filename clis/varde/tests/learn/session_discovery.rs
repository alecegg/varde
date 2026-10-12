use assert_cmd::Command;
use serde_json::{Value, json};
use std::fs;
use std::path::Path;
use tempfile::TempDir;

fn write_session(path: &Path, id: &str, parent: Option<&str>, cwd: &Path, version: &str) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    let mut header = json!({
        "id": id,
        "session_id": format!("session-{id}"),
        "timestamp": "2026-10-08T10:00:00Z",
        "cwd": cwd,
        "originator": "codex",
        "cli_version": version
    });
    if let Some(parent) = parent {
        header["parent_thread_id"] = json!(parent);
    } else {
        header["parent_thread_id"] = Value::Null;
    }
    let mut records = vec![
        json!({"type":"session_meta","payload":header}),
        json!({"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"fixture prompt"}]}}),
    ];
    if id == "current-root" {
        records.push(json!({"type":"response_item","payload":{"type":"function_call_output","output":"started worker current-worker"}}));
    }
    fs::write(
        path,
        records
            .into_iter()
            .map(|record| record.to_string())
            .collect::<Vec<_>>()
            .join("\n")
            + "\n",
    )
    .unwrap();
}

fn list(codex_home: &Path, repo: &Path) -> Value {
    let output = Command::cargo_bin("varde")
        .expect("varde binary")
        .args(["learn", "diagnose", "list", "--harness", "codex", "--repo"])
        .arg(repo)
        .args(["--json"])
        .env("HOME", codex_home)
        .env("CODEX_HOME", codex_home)
        .output()
        .expect("run diagnose list");
    assert!(
        output.status.success(),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("JSON response")
}

#[test]
fn lists_current_and_archived_codex_sessions_and_links_worker() {
    let temp = TempDir::new().unwrap();
    let repo = temp.path().join("repo");
    let codex_home = temp.path().join("codex");
    fs::create_dir_all(&repo).unwrap();

    let active_root = codex_home.join("sessions/2026/10/08/rollout-current-root.jsonl");
    let active_worker = codex_home.join("sessions/2026/10/08/rollout-current-worker.jsonl");
    let metadata_worker = codex_home.join("sessions/2026/10/08/rollout-metadata-worker.jsonl");
    let archived = codex_home.join("sessions/archived/rollout-archived.jsonl");
    write_session(&active_root, "current-root", None, &repo, "0.165.0");
    write_session(&active_worker, "current-worker", None, &repo, "0.165.0");
    write_session(
        &metadata_worker,
        "metadata-worker",
        Some("current-root"),
        &repo,
        "0.165.0",
    );
    write_session(&archived, "archived-root", None, &repo, "0.165.0");

    let value = list(&codex_home, &repo);
    assert_eq!(value["ok"], true, "{value}");
    let sessions = value["data"]["sessions"].as_array().unwrap();
    let find = |id: &str| {
        sessions
            .iter()
            .find(|session| session["session_id"] == id)
            .unwrap_or_else(|| panic!("missing session {id}: {sessions:?}"))
    };

    let root = find("current-root");
    assert_eq!(root["source"], "active");
    assert_eq!(root["link"], "unlinked");
    let workers = root["workers"].as_array().unwrap();
    let worker = workers
        .iter()
        .find(|worker| worker["session_id"] == "current-worker")
        .unwrap();
    assert_eq!(worker["source"], "active");
    assert_eq!(worker["link"]["parent_id"], "codex:current-root");
    assert!(
        worker["link"]["evidence"]
            .as_str()
            .unwrap()
            .contains("current-worker")
    );
    let metadata_worker = workers
        .iter()
        .find(|worker| worker["session_id"] == "metadata-worker")
        .unwrap();
    assert_eq!(metadata_worker["link"]["evidence"], "codex:current-root");
    assert_eq!(find("archived-root")["source"], "archived");
    assert_eq!(root["source"], "active");
}
