use assert_cmd::Command;
use serde_json::{Value, json};
use std::fs;
use std::path::Path;
use tempfile::TempDir;

fn rollout(path: &Path, records: &[Value]) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(
        path,
        records
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n")
            + "\n",
    )
    .unwrap();
}

#[test]
fn inspect_path_retains_unknown_events_and_excludes_inherited_history() {
    let root = TempDir::new().unwrap();
    let path = root.path().join("sessions/2026/09/27/rollout-worker.jsonl");
    rollout(
        &path,
        &[
            json!({
                "timestamp":"2026-09-27T10:00:00Z",
                "type":"session_meta",
                "payload":{
                    "id":"worker-thread",
                    "session_id":"worker-session",
                    "parent_thread_id":"parent-thread",
                    "forked_from_id":"parent-event",
                    "history_base":1,
                    "timestamp":"2026-09-27T10:00:00Z",
                    "cwd":"/fixture",
                    "originator":"codex",
                    "cli_version":"0.155.1"
                }
            }),
            json!({
                "timestamp":"2026-09-27T10:00:01Z",
                "type":"response_item",
                "payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"inherited parent text"}]}
            }),
            json!({
                "timestamp":"2026-09-27T10:00:01Z",
                "type":"event_msg",
                "id":"parent-event",
                "payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":99,"output_tokens":2},"total_token_usage":{"input_tokens":999,"output_tokens":20}}}
            }),
            json!({
                "timestamp":"2026-09-27T10:00:02Z",
                "type":"response_item",
                "payload":{"type":"future_event_kind","data":"preserve this bounded event"}
            }),
            json!({
                "timestamp":"2026-09-27T10:00:03Z",
                "type":"response_item",
                "payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"worker own text"}]}
            }),
        ],
    );

    let output = Command::cargo_bin("varde")
        .expect("varde binary")
        .args([
            "learn",
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", root.path())
        .env("CODEX_THREAD_ID", "unrelated-current-thread")
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let value: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["outcome"], "success");
    let data = &value["data"];
    assert_eq!(data["coverage"]["analysis_ready"], true);
    assert_eq!(data["coverage"]["unknown_events"], 1);
    let records = data["records"].as_array().unwrap();
    assert_eq!(records.len(), 2);
    assert!(records.iter().any(|record| {
        record["kind"] == "future_event_kind"
            && record["unknown_payload_excerpt"]
                .as_str()
                .is_some_and(|excerpt| excerpt.contains("preserve this bounded event"))
    }));
    assert!(
        !records
            .iter()
            .any(|record| record.to_string().contains("inherited parent text"))
    );
    assert!(
        !records
            .iter()
            .any(|record| record.to_string().contains("999"))
    );
    assert_eq!(data["coverage"]["inherited_events"], 2);
}
