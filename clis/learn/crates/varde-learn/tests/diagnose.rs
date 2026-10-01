use assert_cmd::Command;
use serde_json::{Value, json};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use tempfile::TempDir;
use varde_learn_core::diagnose::{
    ClaudeHookContext, DiagnosticHarness, InspectRequest, Intake, MAX_DISCOVERY_FILES,
    MAX_FAMILY_SOURCE_BYTES, MAX_RECORD_BYTES, RecordAnchor, SourceSnapshot, inspect,
    revalidate_record_anchor,
};

const THREAD: &str = "thread-codex-fixture";
const ROOT_SESSION: &str = "root-session-fixture";

#[test]
fn codex_duplicate_child_identity_is_partial_without_selecting_a_candidate() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let message = |text: &str| {
        json!({
            "timestamp":"2026-09-27T10:01:00Z",
            "type":"response_item",
            "payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":text}]}
        })
    };
    let source = rollout(&home, THREAD, None, &[message("root cutoff boundary")]);
    let first = rollout(
        &home,
        "duplicate-child",
        Some(THREAD),
        &[message("first candidate")],
    );
    fs::rename(
        &first,
        first.with_file_name("rollout-first-candidate.jsonl"),
    )
    .unwrap();
    rollout(
        &home,
        "duplicate-child",
        Some(THREAD),
        &[message("second candidate")],
    );
    rollout(
        &home,
        "grandchild",
        Some("duplicate-child"),
        &[message("ambiguous branch")],
    );
    rollout(
        &home,
        "unique-sibling",
        Some(THREAD),
        &[message("retained sibling")],
    );
    let value = inspect_codex_snapshot(&home, THREAD, &root.path().join("snapshot.json"));
    let data = &value["data"];
    for flag in ["complete", "source_complete", "analysis_ready"] {
        assert_eq!(data["coverage"][flag], false, "{flag}: {value}");
    }
    assert_eq!(data["overlap"], "unknown");
    assert!(
        data["coverage"]["warnings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|warning| warning
                .as_str()
                .unwrap()
                .contains("ambiguous child branches"))
    );
    let children = data["children"].as_array().unwrap();
    assert_eq!(children.len(), 1);
    assert_eq!(children[0]["thread_id"], "unique-sibling");
    let records = data["records"].to_string();
    assert!(records.contains("retained sibling"));
    for omitted in ["first candidate", "second candidate", "ambiguous branch"] {
        assert!(
            !records.contains(omitted),
            "ambiguous evidence was retained: {omitted}"
        );
    }
    let frozen: Value =
        serde_json::from_slice(&fs::read(root.path().join("snapshot.json")).unwrap()).unwrap();
    assert_eq!(frozen["sources"].as_array().unwrap().len(), 2);
    let cutoff = root.path().join("cutoff.json");
    let anchor = data["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["session_thread_id"] == THREAD)
        .unwrap();
    fs::write(
        &cutoff,
        json!({"source_path":source,"record_anchor":anchor["anchor"]}).to_string(),
    )
    .unwrap();
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            THREAD,
            "--cutoff-anchor",
            cutoff.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env("CODEX_THREAD_ID", "another-current-thread")
        .output()
        .unwrap();
    let bounded = success_json(&output);
    assert_eq!(bounded["data"]["coverage"]["cutoff_verified"], true);
    for flag in ["complete", "source_complete", "analysis_ready"] {
        assert_eq!(
            bounded["data"]["coverage"][flag], false,
            "cutoff must not conceal ambiguity"
        );
    }
}

#[test]
fn codex_duplicate_root_identity_still_requires_explicit_path() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let source = rollout(&home, THREAD, None, &[]);
    fs::copy(&source, source.with_file_name("rollout-root-copy.jsonl")).unwrap();
    rollout(&home, "unique-child", Some(THREAD), &[]);
    let ambiguous = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            THREAD,
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env("CODEX_THREAD_ID", "another-current-thread")
        .output()
        .unwrap();
    error_json(&ambiguous, 2, "diagnose_session_ambiguous");
    let selected = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            source.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env("CODEX_THREAD_ID", "another-current-thread")
        .output()
        .unwrap();
    let value = success_json(&selected);
    assert_eq!(value["data"]["coverage"]["source_complete"], true);
    assert_eq!(value["data"]["coverage"]["analysis_ready"], true);
    assert_eq!(value["data"]["children"].as_array().unwrap().len(), 1);
}

fn rollout(
    home: &Path,
    thread_id: &str,
    parent_thread_id: Option<&str>,
    extra: &[Value],
) -> PathBuf {
    let path = home
        .join("sessions/2026/09/27")
        .join(format!("rollout-2026-09-27T10-00-00-{thread_id}.jsonl"));
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    let mut lines = vec![json!({
        "timestamp": "2026-09-27T10:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "session_id": ROOT_SESSION,
            "parent_thread_id": parent_thread_id,
            "source": parent_thread_id.map(|parent| json!({
                "subagent": {"thread_spawn": {"parent_thread_id": parent}}
            })),
            "timestamp": "2026-09-27T10:00:00Z",
            "cwd": "/historical/worktree",
            "originator": "codex",
            "cli_version": "0.155.1",
            "source": "cli",
            "git": {
                "commit_hash": "0123456789abcdef",
                "branch": "diagnosis-fixture",
                "repository_url": "https://example.invalid/varde.git"
            }
        }
    })];
    lines.extend_from_slice(extra);
    fs::write(
        &path,
        lines
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n")
            + "\n",
    )
    .unwrap();
    path
}

fn command() -> Command {
    Command::cargo_bin("varde-learn").expect("varde-learn binary")
}

fn claude_jsonl(path: &Path, records: &[Value]) {
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

fn claude_request(projects_root: &Path, session_id: &str) -> Value {
    let inspection = inspect(&InspectRequest {
        harness: Some(DiagnosticHarness::Claude),
        intake: Intake::Session {
            source_root: projects_root.to_path_buf(),
            session_id: session_id.to_owned(),
        },
        offset: 0,
        limit: 100,
        snapshot_out: None,
        cutoff_anchor: None,
    })
    .expect("Claude fixture should be inspectable");
    serde_json::to_value(inspection).unwrap()
}

fn claude_main(project_dir: &Path, session_id: &str, records: &[Value]) -> PathBuf {
    let path = project_dir.join(format!("{session_id}.jsonl"));
    claude_jsonl(&path, records);
    path
}

fn codex_capture_rollout(home: &Path, thread_id: &str, cwd: &str, reason: &str) -> PathBuf {
    rollout(
        home,
        thread_id,
        None,
        &[
            json!({
                "timestamp":"2026-09-27T10:01:00Z",
                "type":"turn_context",
                "payload":{"turn_id":"turn-capture", "cwd":cwd}
            }),
            json!({
                "timestamp":"2026-09-27T10:02:00Z",
                "type":"response_item",
                "id":"native-failure-1",
                "payload":{"type":"function_call_output", "call_id":"call-capture", "status":"failed", "error":reason}
            }),
        ],
    )
}

fn inspect_codex_snapshot(home: &Path, thread_id: &str, snapshot_path: &Path) -> Value {
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            thread_id,
            "--snapshot-out",
            snapshot_path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", home)
        .env("CODEX_THREAD_ID", "another-current-thread")
        .output()
        .unwrap();
    success_json(&output)
}

fn capture_request(snapshot_path: &Path, inspection: &Value, title: &str, evidence: &str) -> Value {
    let record = inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "native-failure-1")
        .expect("selected native failure record");
    json!({
        "snapshot_path": snapshot_path.to_string_lossy(),
        "snapshot_digest": inspection["data"]["snapshot"]["digest"],
        "session_id": inspection["data"]["session"]["thread_id"],
        "anchor": record["anchor"],
        "incident_kind": "failed-tool",
        "item": {
            "mode":"new",
            "source":"varde-learn diagnosis",
            "title":title,
            "target":"clis/learn"
        },
        "evidence":evidence
    })
}

fn capture_request_for_anchor(
    snapshot_path: &Path,
    inspection: &Value,
    anchor: &Value,
    incident_kind: &str,
) -> Value {
    json!({
        "snapshot_path": snapshot_path.to_string_lossy(),
        "snapshot_digest": inspection["data"]["snapshot"]["digest"],
        "session_id": inspection["data"]["session"]["thread_id"],
        "anchor": anchor,
        "incident_kind": incident_kind,
        "item": {
            "mode":"new",
            "source":"varde-learn diagnosis",
            "title":"Synthetic diagnosis fixture",
            "target":"clis/learn"
        },
        "evidence":"Analyst-observed synthetic failure evidence."
    })
}

fn run_capture(request_path: &Path, store_path: &Path) -> std::process::Output {
    command()
        .args([
            "diagnose",
            "capture",
            "--file",
            request_path.to_str().unwrap(),
            "--json",
        ])
        .env("VARDE_LEARN_STORE", store_path)
        .output()
        .unwrap()
}

fn claude_agent(
    project_dir: &Path,
    session_id: &str,
    relative_path: &str,
    records: &[Value],
    sidecar: Option<Value>,
) -> PathBuf {
    let path = project_dir
        .join(session_id)
        .join("subagents")
        .join(relative_path);
    claude_jsonl(&path, records);
    if let Some(sidecar) = sidecar {
        fs::write(
            path.with_extension("meta.json"),
            serde_json::to_vec(&sidecar).unwrap(),
        )
        .unwrap();
    }
    path
}

fn success_json(output: &std::process::Output) -> Value {
    assert!(
        output.status.success(),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let value: Value = serde_json::from_slice(&output.stdout).expect("success JSON");
    assert_eq!(value["outcome"], "success");
    value
}

fn error_json(output: &std::process::Output, code: i32, expected_error: &str) -> Value {
    assert_eq!(output.status.code(), Some(code));
    let value: Value = serde_json::from_slice(&output.stderr).expect("error JSON");
    assert_eq!(value["schema_version"], 1);
    assert_eq!(value["envelope_version"], 1);
    assert_eq!(value["data"]["error"]["code"], expected_error);
    value
}

#[test]
fn diagnose_inspect_help_exposes_bounded_mutually_exclusive_intakes() {
    command()
        .args(["diagnose", "inspect", "--help"])
        .assert()
        .success()
        .stdout(predicates::str::contains("--harness"))
        .stdout(predicates::str::contains("--current"))
        .stdout(predicates::str::contains("--session"))
        .stdout(predicates::str::contains("--path"))
        .stdout(predicates::str::contains("--snapshot-out"))
        .stdout(predicates::str::contains("--snapshot-in"))
        .stdout(predicates::str::contains("--cutoff-anchor"))
        .stdout(predicates::str::contains("--offset"))
        .stdout(predicates::str::contains("--limit"));
}

#[test]
fn diagnose_capture_help_exposes_strict_incident_file_input() {
    command()
        .args(["diagnose", "capture", "--help"])
        .assert()
        .success()
        .stdout(predicates::str::contains("--file"))
        .stdout(predicates::str::contains("--json"));
}

#[test]
fn capture_revalidates_context_and_deduplicates_full_native_facts() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let source = codex_capture_rollout(&home, THREAD, "/historic/turn-cwd", "permission denied");
    let snapshot_path = root.path().join("evidence.json");
    let inspection = inspect_codex_snapshot(&home, THREAD, &snapshot_path);
    assert_eq!(inspection["data"]["coverage"]["analysis_ready"], true);
    let request_path = root.path().join("incident.json");
    let request = capture_request(
        &snapshot_path,
        &inspection,
        "Synthetic failed tool",
        "Observed a tool failure in the historical session.",
    );
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let store_path = root.path().join("learn-store");

    let mut file = fs::OpenOptions::new().append(true).open(&source).unwrap();
    writeln!(
        file,
        "{}",
        json!({"timestamp":"2026-09-27T10:03:00Z", "type":"response_item", "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"Unrelated later activity"}]}})
    )
    .unwrap();

    let created = success_json(&run_capture(&request_path, &store_path));
    assert_eq!(created["data"]["disposition"], "created");
    assert_eq!(created["data"]["at"], "2026-09-27T10:02:00Z");
    assert_eq!(created["data"]["cwd"], "/historic/turn-cwd");
    assert_eq!(created["data"]["repo_root"], Value::Null);
    assert_eq!(created["data"]["head_sha"], Value::Null);

    let mut retry = request.clone();
    retry["evidence"] = json!("The report text changed, not the event.");
    retry["item"]["title"] = json!("A changed generated title");
    fs::write(&request_path, serde_json::to_vec(&retry).unwrap()).unwrap();
    let repeated = success_json(&run_capture(&request_path, &store_path));
    assert_eq!(repeated["data"]["disposition"], "already-recorded");
    assert_eq!(repeated["data"]["item_id"], created["data"]["item_id"]);
    assert_eq!(
        repeated["data"]["occurrence_id"],
        created["data"]["occurrence_id"]
    );

    let copied_home = root.path().join("relocated-codex-home");
    let copied_source = codex_capture_rollout(
        &copied_home,
        THREAD,
        "/historic/turn-cwd",
        "permission denied",
    );
    let copied_contents = fs::read_to_string(&copied_source).unwrap();
    fs::write(
        &copied_source,
        copied_contents.replace("\"payload\":", "\"payload\" : "),
    )
    .unwrap();
    let copied_snapshot = root.path().join("copied-evidence.json");
    let copied_inspection = inspect_codex_snapshot(&copied_home, THREAD, &copied_snapshot);
    let copied_request = capture_request(
        &copied_snapshot,
        &copied_inspection,
        "Another generated title",
        "Another report explanation.",
    );
    fs::write(&request_path, serde_json::to_vec(&copied_request).unwrap()).unwrap();
    let relocated = success_json(&run_capture(&request_path, &store_path));
    assert_eq!(relocated["data"]["disposition"], "already-recorded");
    assert_eq!(
        relocated["data"]["occurrence_id"],
        created["data"]["occurrence_id"]
    );

    let mut other_kind = copied_request.clone();
    other_kind["incident_kind"] = json!("repeated-work");
    fs::write(&request_path, serde_json::to_vec(&other_kind).unwrap()).unwrap();
    error_json(
        &run_capture(&request_path, &store_path),
        2,
        "diagnose_incident_kind_conflict",
    );

    let mut unexpected_field = copied_request.clone();
    unexpected_field["unexpected"] = json!(true);
    fs::write(
        &request_path,
        serde_json::to_vec(&unexpected_field).unwrap(),
    )
    .unwrap();
    error_json(
        &run_capture(&request_path, &store_path),
        2,
        "diagnose_capture_invalid",
    );

    let changed_home = root.path().join("changed-codex-home");
    let changed_source = codex_capture_rollout(
        &changed_home,
        THREAD,
        "/historic/turn-cwd",
        "permission denied after retry",
    );
    assert!(changed_source.is_file());
    let changed_snapshot = root.path().join("changed-evidence.json");
    let changed_inspection = inspect_codex_snapshot(&changed_home, THREAD, &changed_snapshot);
    let changed_request = capture_request(
        &changed_snapshot,
        &changed_inspection,
        "Changed native event",
        "The underlying failure content changed.",
    );
    fs::write(&request_path, serde_json::to_vec(&changed_request).unwrap()).unwrap();
    let conflict = run_capture(&request_path, &store_path);
    error_json(&conflict, 2, "diagnose_incident_conflict");
}

#[test]
fn selected_codex_child_can_capture_its_own_native_event_with_external_parent() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let parent_id = "thread-external-parent";
    rollout(&home, parent_id, None, &[]);
    let child = rollout(
        &home,
        "thread-selected-child",
        Some(parent_id),
        &[
            json!({
                "timestamp":"2026-09-27T10:01:00Z",
                "type":"turn_context",
                "payload":{"turn_id":"child-turn","cwd":"/historical/child"}
            }),
            json!({
                "timestamp":"2026-09-27T10:02:00Z",
                "type":"response_item",
                "id":"child-native-failure",
                "payload":{"type":"function_call_output","call_id":"child-call","status":"failed","error":"synthetic child failure"}
            }),
        ],
    );
    let snapshot_path = root.path().join("child-evidence.json");
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            child.to_str().unwrap(),
            "--snapshot-out",
            snapshot_path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env("CODEX_THREAD_ID", "another-current-thread")
        .output()
        .unwrap();
    let inspection = success_json(&output);
    assert_eq!(
        inspection["data"]["session"]["thread_id"],
        "thread-selected-child"
    );
    assert_eq!(inspection["data"]["session"]["parent_thread_id"], parent_id);
    assert_eq!(inspection["data"]["coverage"]["analysis_ready"], true);
    let record = inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "child-native-failure")
        .unwrap();
    let request_path = root.path().join("child-incident.json");
    let request = capture_request_for_anchor(
        &snapshot_path,
        &inspection,
        &record["anchor"],
        "failed-tool",
    );
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let store_path = root.path().join("learn-store");
    let created = success_json(&run_capture(&request_path, &store_path));
    assert_eq!(created["data"]["disposition"], "created");
    assert_eq!(created["data"]["cwd"], "/historical/child");
    let repeated = success_json(&run_capture(&request_path, &store_path));
    assert_eq!(repeated["data"]["disposition"], "already-recorded");
    assert_eq!(
        repeated["data"]["occurrence_id"],
        created["data"]["occurrence_id"]
    );
}

#[test]
fn codex_failed_output_without_native_message_id_uses_verified_record_anchor() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let thread_id = "thread-codex-no-native-id";
    rollout(
        &home,
        thread_id,
        None,
        &[
            json!({
                "timestamp":"2026-09-27T10:01:00Z",
                "type":"turn_context",
                "payload":{"turn_id":"turn-no-id", "cwd":"/historic/no-id"}
            }),
            json!({
                "timestamp":"2026-09-27T10:02:00Z",
                "type":"response_item",
                "payload":{"type":"function_call_output", "call_id":"call-no-id", "output":"permission denied"}
            }),
        ],
    );
    let snapshot_path = root.path().join("evidence.json");
    let inspection = inspect_codex_snapshot(&home, thread_id, &snapshot_path);
    let selected = inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["kind"] == "tool_result")
        .expect("native tool output without a message ID");
    assert_eq!(selected["anchor"]["native_id"], Value::Null);
    assert_eq!(selected["tool_output_excerpt"], "permission denied");

    let request_path = root.path().join("incident.json");
    let request = capture_request_for_anchor(
        &snapshot_path,
        &inspection,
        &selected["anchor"],
        "failed-tool",
    );
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let store_path = root.path().join("learn-store");
    let captured = success_json(&run_capture(&request_path, &store_path));
    assert_eq!(captured["data"]["disposition"], "created");
    assert_eq!(captured["data"]["at"], "2026-09-27T10:02:00Z");
    assert_eq!(captured["data"]["cwd"], "/historic/no-id");

    let copied_home = root.path().join("relocated-codex-home");
    let copied = rollout(
        &copied_home,
        thread_id,
        None,
        &[
            json!({
                "timestamp":"2026-09-27T10:01:00Z",
                "type":"turn_context",
                "payload":{"turn_id":"turn-no-id", "cwd":"/historic/no-id"}
            }),
            json!({
                "timestamp":"2026-09-27T10:02:00Z",
                "type":"response_item",
                "payload":{"type":"function_call_output", "call_id":"call-no-id", "output":"permission denied"}
            }),
        ],
    );
    assert!(copied.is_file());
    let copied_snapshot = root.path().join("copied-evidence.json");
    let copied_inspection = inspect_codex_snapshot(&copied_home, thread_id, &copied_snapshot);
    let copied_record = copied_inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["kind"] == "tool_result")
        .unwrap();
    assert_eq!(copied_record["anchor"]["native_id"], Value::Null);
    let copied_request = capture_request_for_anchor(
        &copied_snapshot,
        &copied_inspection,
        &copied_record["anchor"],
        "failed-tool",
    );
    fs::write(&request_path, serde_json::to_vec(&copied_request).unwrap()).unwrap();
    let repeated = success_json(&run_capture(&request_path, &store_path));
    assert_eq!(repeated["data"]["disposition"], "already-recorded");
    assert_eq!(
        repeated["data"]["occurrence_id"],
        captured["data"]["occurrence_id"]
    );

    let mut other_kind = copied_request.clone();
    other_kind["incident_kind"] = json!("repeated-work");
    fs::write(&request_path, serde_json::to_vec(&other_kind).unwrap()).unwrap();
    error_json(
        &run_capture(&request_path, &store_path),
        2,
        "diagnose_incident_kind_conflict",
    );

    let rewritten_home = root.path().join("rewritten-codex-home");
    rollout(
        &rewritten_home,
        thread_id,
        None,
        &[
            json!({
                "timestamp":"2026-09-27T10:01:00Z",
                "type":"turn_context",
                "payload":{"turn_id":"turn-no-id", "cwd":"/historic/no-id"}
            }),
            json!({
                "timestamp":"2026-09-27T10:02:00Z",
                "type":"response_item",
                "payload":{"type":"function_call_output", "call_id":"call-no-id", "output":"different output"}
            }),
        ],
    );
    let rewritten_snapshot = root.path().join("rewritten-evidence.json");
    let rewritten_inspection =
        inspect_codex_snapshot(&rewritten_home, thread_id, &rewritten_snapshot);
    let rewritten_record = rewritten_inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["kind"] == "tool_result")
        .unwrap();
    let rewritten_request = capture_request_for_anchor(
        &rewritten_snapshot,
        &rewritten_inspection,
        &rewritten_record["anchor"],
        "failed-tool",
    );
    fs::write(
        &request_path,
        serde_json::to_vec(&rewritten_request).unwrap(),
    )
    .unwrap();
    error_json(
        &run_capture(&request_path, &store_path),
        2,
        "diagnose_capture_uncertain",
    );

    let repositioned_home = root.path().join("repositioned-codex-home");
    rollout(
        &repositioned_home,
        thread_id,
        None,
        &[
            json!({
                "timestamp":"2026-09-27T10:01:00Z",
                "type":"turn_context",
                "payload":{"turn_id":"turn-no-id", "cwd":"/historic/no-id"}
            }),
            json!({
                "timestamp":"2026-09-27T10:01:30Z",
                "type":"response_item",
                "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"inserted record"}]}
            }),
            json!({
                "timestamp":"2026-09-27T10:02:00Z",
                "type":"response_item",
                "payload":{"type":"function_call_output", "call_id":"call-no-id", "output":"permission denied"}
            }),
        ],
    );
    let repositioned_snapshot = root.path().join("repositioned-evidence.json");
    let repositioned_inspection =
        inspect_codex_snapshot(&repositioned_home, thread_id, &repositioned_snapshot);
    let repositioned_record = repositioned_inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["kind"] == "tool_result")
        .unwrap();
    let repositioned_request = capture_request_for_anchor(
        &repositioned_snapshot,
        &repositioned_inspection,
        &repositioned_record["anchor"],
        "failed-tool",
    );
    fs::write(
        &request_path,
        serde_json::to_vec(&repositioned_request).unwrap(),
    )
    .unwrap();
    error_json(
        &run_capture(&request_path, &store_path),
        2,
        "diagnose_capture_uncertain",
    );
}

#[test]
fn unknown_overlap_with_verified_native_cutoff_can_capture_pre_cutoff_event() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let thread_id = "thread-codex-unknown-cutoff";
    let source = rollout(
        &home,
        thread_id,
        None,
        &[
            json!({
                "timestamp":"2026-09-27T10:01:00Z",
                "type":"turn_context",
                "payload":{"turn_id":"turn-cutoff", "cwd":"/historic/cutoff"}
            }),
            json!({
                "timestamp":"2026-09-27T10:02:00Z",
                "type":"response_item",
                "id":"event-before-cutoff",
                "payload":{"type":"function_call_output", "call_id":"call-cutoff", "output":"permission denied"}
            }),
            json!({
                "timestamp":"2026-09-27T10:03:00Z",
                "type":"response_item",
                "id":"explicit-anchor-after-event",
                "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"synthetic boundary"}]}
            }),
        ],
    );
    let initial = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            thread_id,
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let initial = success_json(&initial);
    assert_eq!(initial["data"]["overlap"], "unknown");
    let cutoff_record = initial["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "explicit-anchor-after-event")
        .unwrap();
    let cutoff_path = root.path().join("cutoff.json");
    fs::write(
        &cutoff_path,
        serde_json::to_vec(&json!({
            "source_path": source.to_string_lossy(),
            "record_anchor": cutoff_record["anchor"]
        }))
        .unwrap(),
    )
    .unwrap();
    let snapshot_path = root.path().join("evidence.json");
    let bounded = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            thread_id,
            "--snapshot-out",
            snapshot_path.to_str().unwrap(),
            "--cutoff-anchor",
            cutoff_path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let inspection = success_json(&bounded);
    assert_eq!(inspection["data"]["overlap"], "unknown");
    assert_eq!(inspection["data"]["coverage"]["cutoff_verified"], true);

    let selected = inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "event-before-cutoff")
        .unwrap();
    let request_path = root.path().join("incident.json");
    let request = capture_request_for_anchor(
        &snapshot_path,
        &inspection,
        &selected["anchor"],
        "failed-tool",
    );
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let captured = success_json(&run_capture(
        &request_path,
        &root.path().join("learn-store"),
    ));
    assert_eq!(captured["data"]["disposition"], "created");
}

#[test]
fn codex_nested_child_capture_revalidates_source_only_parent_chain() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let root_thread = "thread-family-root";
    rollout(&home, root_thread, None, &[]);
    rollout(
        &home,
        "thread-family-child",
        Some(root_thread),
        &[json!({
            "timestamp":"2026-09-27T10:01:00Z",
            "type":"response_item",
            "id":"child-message",
            "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"child"}]}
        })],
    );
    let grandchild_path = rollout(
        &home,
        "thread-family-grandchild",
        Some("thread-family-child"),
        &[
            json!({
                "timestamp":"2026-09-27T10:02:00Z",
                "type":"turn_context",
                "payload":{"turn_id":"turn-grandchild", "cwd":"/historic/grandchild"}
            }),
            json!({
                "timestamp":"2026-09-27T10:03:00Z",
                "type":"response_item",
                "id":"grandchild-event",
                "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"nested event"}]}
            }),
        ],
    );
    let mut lines = fs::read_to_string(&grandchild_path)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .collect::<Vec<_>>();
    lines[0]["payload"]
        .as_object_mut()
        .unwrap()
        .remove("parent_thread_id");
    lines[0]["payload"]["source"] = json!({
        "subagent":{"thread_spawn":{"parent_thread_id":"thread-family-child"}}
    });
    fs::write(
        &grandchild_path,
        lines
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n")
            + "\n",
    )
    .unwrap();

    let snapshot_path = root.path().join("family.json");
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            root_thread,
            "--snapshot-out",
            snapshot_path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env("CODEX_THREAD_ID", "different-thread")
        .output()
        .unwrap();
    let inspection = success_json(&output);
    let record = inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "grandchild-event")
        .expect("nested Codex event is included");
    let request_path = root.path().join("incident.json");
    let request = capture_request_for_anchor(
        &snapshot_path,
        &inspection,
        &record["anchor"],
        "workflow-deviation",
    );
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let captured = success_json(&run_capture(
        &request_path,
        &root.path().join("learn-store"),
    ));
    assert_eq!(captured["data"]["disposition"], "created");
}

#[test]
fn claude_native_output_with_success_flag_remains_analyst_reviewable() {
    let root = TempDir::new().unwrap();
    let config = root.path().join("claude-config");
    let projects_root = config.join("projects");
    let project_dir = projects_root.join("project-success");
    let session_id = "00000000-0000-4000-8000-000000000006";
    let source = claude_main(
        &project_dir,
        session_id,
        &[
            json!({
                "type":"assistant","uuid":"record-tool-start","parentUuid":null,
                "sessionId":session_id,"timestamp":"2026-09-27T10:00:00Z","cwd":"/historic/claude",
                "message":{"id":"provider-tool-start","role":"assistant","content":[
                    {"type":"tool_use","id":"tool-success","name":"Bash","input":{"command":"true"}}
                ]}
            }),
            json!({
                "type":"user","uuid":"record-tool-success","parentUuid":"record-tool-start",
                "sessionId":session_id,"timestamp":"2026-09-27T10:01:00Z","cwd":"/historic/claude",
                "message":{"role":"user","content":[
                    {"type":"tool_result","tool_use_id":"tool-success","is_error":false,"content":"Error: permission denied"}
                ]}
            }),
            json!({
                "type":"assistant","uuid":"record-cutoff","parentUuid":"record-tool-success",
                "sessionId":session_id,"timestamp":"2026-09-27T10:02:00Z","cwd":"/historic/claude",
                "message":{"id":"provider-cutoff","role":"assistant","content":[{"type":"text","text":"synthetic cutoff"}]}
            }),
        ],
    );
    let initial = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "claude",
            "--session",
            session_id,
            "--json",
        ])
        .env("CLAUDE_CONFIG_DIR", &config)
        .output()
        .unwrap();
    let initial = success_json(&initial);
    assert_eq!(initial["data"]["overlap"], "unknown");
    let cutoff_record = initial["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "record-cutoff")
        .unwrap();
    let cutoff_path = root.path().join("cutoff.json");
    fs::write(
        &cutoff_path,
        serde_json::to_vec(&json!({
            "source_path": source.to_string_lossy(),
            "record_anchor": cutoff_record["anchor"]
        }))
        .unwrap(),
    )
    .unwrap();
    let snapshot_path = root.path().join("claude-snapshot.json");
    let bounded = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "claude",
            "--session",
            session_id,
            "--snapshot-out",
            snapshot_path.to_str().unwrap(),
            "--cutoff-anchor",
            cutoff_path.to_str().unwrap(),
            "--json",
        ])
        .env("CLAUDE_CONFIG_DIR", &config)
        .output()
        .unwrap();
    let inspection = success_json(&bounded);
    let selected = inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "record-tool-success")
        .unwrap();
    assert_eq!(selected["tool_observations"][0]["status"], "success");
    assert_eq!(
        selected["tool_observations"][0]["output_excerpt"],
        "Error: permission denied"
    );
    let request_path = root.path().join("incident.json");
    let request = capture_request_for_anchor(
        &snapshot_path,
        &inspection,
        &selected["anchor"],
        "failed-tool",
    );
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let output = run_capture(&request_path, &root.path().join("learn-store"));
    let captured = success_json(&output);
    assert_eq!(captured["data"]["disposition"], "created");
}

#[test]
fn claude_nested_subagent_capture_revalidates_exact_path_and_sidecar_chain() {
    let root = TempDir::new().unwrap();
    let config = root.path().join("claude-config");
    let projects_root = config.join("projects");
    let project_dir = projects_root.join("project-nested");
    let session_id = "00000000-0000-4000-8000-000000000016";
    let main = claude_main(
        &project_dir,
        session_id,
        &[
            json!({
                "type":"assistant", "uuid":"main-spawn", "parentUuid":null,
                "sessionId":session_id, "timestamp":"2026-09-27T10:00:00Z", "cwd":"/historic/claude",
                "message":{"id":"main-message", "role":"assistant", "content":[
                    {"type":"tool_use", "id":"tool-direct", "name":"Agent", "input":{"description":"direct child"}}
                ]}
            }),
            json!({
                "type":"assistant", "uuid":"main-cutoff", "parentUuid":"main-spawn",
                "sessionId":session_id, "timestamp":"2026-09-27T10:04:00Z", "cwd":"/historic/claude",
                "message":{"id":"main-cutoff-message", "role":"assistant", "content":[{"type":"text", "text":"synthetic cutoff"}]}
            }),
        ],
    );
    claude_agent(
        &project_dir,
        session_id,
        "workflows/run-1/agent-agent-direct.jsonl",
        &[json!({
            "type":"assistant", "uuid":"direct-spawn", "parentUuid":null,
            "sessionId":session_id, "agentId":"agent-direct", "isSidechain":true,
            "timestamp":"2026-09-27T10:01:00Z", "cwd":"/historic/claude",
            "message":{"id":"direct-spawn-message", "role":"assistant", "content":[
                {"type":"tool_use", "id":"tool-nested", "name":"Agent", "input":{"description":"nested child"}}
            ]}
        })],
        Some(json!({"toolUseId":"tool-direct", "parentAgentId":null})),
    );
    let nested = claude_agent(
        &project_dir,
        session_id,
        "workflows/run-1/nested/agent-agent-nested.jsonl",
        &[json!({
            "type":"user", "uuid":"nested-failure", "parentUuid":null,
            "sessionId":session_id, "agentId":"agent-nested", "isSidechain":true,
            "timestamp":"2026-09-27T10:02:00Z", "cwd":"/historic/claude",
            "message":{"role":"user", "content":[
                {"type":"tool_result", "tool_use_id":"tool-work", "is_error":true, "content":"permission denied"}
            ]}
        })],
        Some(json!({"toolUseId":"tool-nested", "parentAgentId":"agent-direct"})),
    );

    let initial = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "claude",
            "--session",
            session_id,
            "--json",
        ])
        .env("CLAUDE_CONFIG_DIR", &config)
        .output()
        .unwrap();
    let initial = success_json(&initial);
    let cutoff_record = initial["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "main-cutoff")
        .unwrap();
    let cutoff_path = root.path().join("cutoff.json");
    fs::write(
        &cutoff_path,
        serde_json::to_vec(&json!({
            "source_path": main.to_string_lossy(),
            "record_anchor": cutoff_record["anchor"]
        }))
        .unwrap(),
    )
    .unwrap();
    let snapshot_path = root.path().join("nested-snapshot.json");
    let bounded = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "claude",
            "--session",
            session_id,
            "--snapshot-out",
            snapshot_path.to_str().unwrap(),
            "--cutoff-anchor",
            cutoff_path.to_str().unwrap(),
            "--json",
        ])
        .env("CLAUDE_CONFIG_DIR", &config)
        .output()
        .unwrap();
    let inspection = success_json(&bounded);
    let selected = inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "nested-failure")
        .expect("linked nested child event is included");
    assert!(
        selected["transcript_id"]
            .as_str()
            .unwrap()
            .ends_with("subagents/workflows/run-1/nested/agent-agent-nested.jsonl")
    );
    let request_path = root.path().join("nested-incident.json");
    let request = capture_request_for_anchor(
        &snapshot_path,
        &inspection,
        &selected["anchor"],
        "failed-tool",
    );
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let store_path = root.path().join("learn-store");
    let captured = success_json(&run_capture(&request_path, &store_path));
    assert_eq!(captured["data"]["disposition"], "created");

    fs::write(
        nested.with_extension("meta.json"),
        serde_json::to_vec(&json!({"toolUseId":"tool-nested", "parentAgentId":"forged-parent"}))
            .unwrap(),
    )
    .unwrap();
    error_json(
        &run_capture(&request_path, &store_path),
        2,
        "diagnose_source_changed",
    );
}

#[test]
fn capture_rejects_changed_historical_context_without_creating_store_items() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let source = codex_capture_rollout(&home, THREAD, "/historic/turn-cwd", "permission denied");
    let snapshot_path = root.path().join("evidence.json");
    let inspection = inspect_codex_snapshot(&home, THREAD, &snapshot_path);
    let request_path = root.path().join("incident.json");
    let request = capture_request(
        &snapshot_path,
        &inspection,
        "Synthetic failed tool",
        "Observed a tool failure in the historical session.",
    );
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let contents = fs::read_to_string(&source).unwrap();
    fs::write(&source, contents.replace("turn-cwd", "other-cwd")).unwrap();

    let store_path = root.path().join("learn-store");
    let changed = run_capture(&request_path, &store_path);
    error_json(&changed, 2, "diagnose_source_changed");
    assert!(
        !store_path.exists(),
        "rejected source context must not initialize or write the learn store"
    );
}

#[test]
fn capture_allows_a_current_session_witness_before_an_explicit_cutoff() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let source = codex_capture_rollout(&home, THREAD, "/historic/turn-cwd", "permission denied");
    let mut file = fs::OpenOptions::new().append(true).open(&source).unwrap();
    writeln!(
        file,
        "{}",
        json!({
            "timestamp":"2026-09-27T10:03:00Z",
            "type":"response_item",
            "id":"pre-orchestration-anchor",
            "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"Synthetic diagnostic request boundary"}]}
        })
    )
    .unwrap();

    let initial = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            THREAD,
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env("CODEX_THREAD_ID", THREAD)
        .output()
        .unwrap();
    let initial = success_json(&initial);
    assert_eq!(initial["data"]["coverage"]["analysis_ready"], false);
    let cutoff_record = initial["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "pre-orchestration-anchor")
        .unwrap();
    let cutoff_path = root.path().join("cutoff.json");
    fs::write(
        &cutoff_path,
        serde_json::to_vec(&json!({
            "source_path": source.to_string_lossy(),
            "record_anchor": cutoff_record["anchor"]
        }))
        .unwrap(),
    )
    .unwrap();
    let snapshot_path = root.path().join("evidence.json");
    let snapshot_command = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            THREAD,
            "--snapshot-out",
            snapshot_path.to_str().unwrap(),
            "--cutoff-anchor",
            cutoff_path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env("CODEX_THREAD_ID", THREAD)
        .output()
        .unwrap();
    let inspection = success_json(&snapshot_command);
    assert_eq!(inspection["data"]["coverage"]["cutoff_verified"], true);
    assert_eq!(inspection["data"]["coverage"]["analysis_ready"], true);

    let request_path = root.path().join("incident.json");
    let request = capture_request(
        &snapshot_path,
        &inspection,
        "Synthetic current-session failure",
        "The failure predates the explicit diagnostic cutoff.",
    );
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let output = run_capture(&request_path, &root.path().join("learn-store"));
    let captured = success_json(&output);
    assert_eq!(captured["data"]["disposition"], "created");
    assert_eq!(captured["data"]["at"], "2026-09-27T10:02:00Z");
}

#[test]
fn path_inspection_preserves_history_and_never_opens_the_learn_store() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let store = root.path().join("must-not-be-created");
    let path = rollout(
        &home,
        THREAD,
        None,
        &[
            json!({
                "timestamp": "2026-09-27T10:01:00Z",
                "type": "turn_context",
                "payload": {"turn_id":"turn-fixture", "cwd":"/historic/turn-cwd"}
            }),
            json!({
                "timestamp": "2026-09-27T10:02:00Z",
                "type": "response_item",
                "payload": {"type":"message", "role":"user", "content":[{"type":"input_text", "text":"Synthetic failure"}]}
            }),
            json!({
                "timestamp": "2026-09-27T10:03:00Z",
                "type": "event_msg",
                "payload": {
                    "type":"token_count",
                    "info": {
                        "total_token_usage":{"input_tokens":120,"cached_input_tokens":20,"cache_write_input_tokens":0,"output_tokens":30,"reasoning_output_tokens":10,"total_tokens":150},
                        "last_token_usage":{"input_tokens":70,"cached_input_tokens":10,"cache_write_input_tokens":0,"output_tokens":20,"reasoning_output_tokens":5,"total_tokens":90},
                        "model_context_window":200000
                    }
                }
            }),
            json!({
                "timestamp": "2026-09-27T10:04:00Z",
                "type": "event_msg",
                "payload": {"type":"turn_failed", "reason":"Synthetic failure"}
            }),
            json!({
                "timestamp": "2026-09-27T10:05:00Z",
                "type": "compacted",
                "payload": {"tokens_before": 4000, "replacement_history": []}
            }),
        ],
    );
    fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap()
        .write_all(b"{\"type\":\"response_item\",\"payload\":")
        .unwrap();

    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .env("VARDE_LEARN_STORE", &store)
        .output()
        .unwrap();
    let value = success_json(&output);
    assert_eq!(value["data"]["session"]["thread_id"], THREAD);
    assert_eq!(value["data"]["session"]["session_id"], ROOT_SESSION);
    assert_eq!(value["data"]["session"]["cwd"], "/historical/worktree");
    assert_eq!(
        value["data"]["session"]["git"]["commit_hash"],
        "0123456789abcdef"
    );
    assert_eq!(value["data"]["overlap"], "unknown");
    assert_eq!(value["data"]["coverage"]["incomplete_tail"], true);
    assert_eq!(value["data"]["coverage"]["record_count"], 5);
    let records = value["data"]["records"].as_array().unwrap();
    assert!(
        records
            .iter()
            .any(|record| record["kind"] == "turn_context")
    );
    assert!(records.iter().any(|record| record["kind"] == "compacted"));
    assert!(records.iter().any(|record| record["kind"] == "turn_failed"));
    let failure = records
        .iter()
        .find(|record| record["kind"] == "turn_failed")
        .unwrap();
    assert_eq!(failure["git_head"], Value::Null);
    assert_eq!(
        value["data"]["session"]["git"]["commit_hash"],
        "0123456789abcdef"
    );
    let context = records
        .iter()
        .find(|record| record["kind"] == "turn_context")
        .unwrap();
    assert_eq!(context["cwd"], "/historic/turn-cwd");
    let usage = records
        .iter()
        .find(|record| record["kind"] == "token_count")
        .unwrap();
    assert_eq!(usage["usage_total"]["input_tokens"], 120);
    assert_eq!(usage["usage_last"]["input_tokens"], 70);
    assert_eq!(usage["usage_total"]["total_tokens"], 150);
    assert!(
        usage["anchor"]["record_digest"]
            .as_str()
            .unwrap()
            .starts_with("sha256:")
    );
    assert!(
        value["data"]["snapshot"]["digest"]
            .as_str()
            .unwrap()
            .starts_with("sha256:")
    );
    assert!(
        !store.exists(),
        "inspect must not initialize the friction store"
    );
}

#[test]
fn session_lookup_uses_canonical_thread_id_and_includes_evidence_linked_children() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let parent = rollout(&home, THREAD, None, &[]);
    let child_id = "thread-child-fixture";
    let child = rollout(
        &home,
        child_id,
        Some(THREAD),
        &[json!({
            "timestamp":"2026-09-27T10:10:00Z",
            "type":"response_item",
            "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"Child evidence"}]}
        })],
    );
    let unrelated = rollout(&home, "thread-unrelated-fixture", None, &[]);
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            THREAD,
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env("CODEX_THREAD_ID", "some-other-active-thread")
        .output()
        .unwrap();
    let value = success_json(&output);
    assert_eq!(value["data"]["session"]["thread_id"], THREAD);
    assert_eq!(value["data"]["session"]["session_id"], ROOT_SESSION);
    assert_eq!(value["data"]["overlap"], "not_current");
    assert!(
        value["data"]["children"]
            .as_array()
            .unwrap()
            .iter()
            .any(|child| child["thread_id"] == child_id)
    );
    assert!(
        value["data"]["records"]
            .as_array()
            .unwrap()
            .iter()
            .any(|record| record["session_thread_id"] == child_id)
    );
    assert_eq!(value["meta"]["truncated"], false);
    assert!(parent.exists() && child.exists() && unrelated.exists());
}

#[test]
fn skipped_metadata_subtrees_make_discovery_coverage_partial() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let parent = rollout(&home, THREAD, None, &[]);
    let deep = home.join("sessions/a/b/c/d/e/f/g/h/i");
    fs::create_dir_all(&deep).unwrap();
    rollout(&home, "thread-deep-child", Some(THREAD), &[]);
    let deep_path = deep.join("rollout-2026-09-27T10-00-00-thread-deep-child.jsonl");
    fs::rename(
        home.join("sessions/2026/09/27/rollout-2026-09-27T10-00-00-thread-deep-child.jsonl"),
        &deep_path,
    )
    .unwrap();

    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            parent.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let value = success_json(&output);
    assert_eq!(value["data"]["coverage"]["source_complete"], false);
    assert_eq!(value["data"]["coverage"]["complete"], false);
    assert_eq!(value["data"]["coverage"]["truncated"], true);
}

#[test]
fn inherited_history_in_a_child_rollout_makes_family_coverage_partial() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let parent = rollout(
        &home,
        THREAD,
        None,
        &[json!({
            "timestamp":"2026-09-27T10:04:00Z",
            "type":"response_item",
            "id":"history-cutoff",
            "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"cutoff"}]}
        })],
    );
    let child = rollout(
        &home,
        "thread-child-history",
        Some(THREAD),
        &[
            json!({
                "timestamp":"2026-09-27T10:01:00Z",
                "type":"turn_context",
                "payload":{"turn_id":"turn-inherited", "cwd":"/historic/inherited"}
            }),
            json!({
                "timestamp":"2026-09-27T10:02:00Z",
                "type":"response_item",
                "payload":{"type":"function_call_output", "call_id":"call-inherited", "output":"permission denied"}
            }),
        ],
    );
    let contents = fs::read_to_string(&child).unwrap();
    let mut lines = contents
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .collect::<Vec<_>>();
    lines[0]["payload"]["history_base"] = json!({"source_thread_id":"older-thread"});
    fs::write(
        &child,
        lines
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n")
            + "\n",
    )
    .unwrap();

    let initial = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            THREAD,
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env("CODEX_THREAD_ID", "another-current-thread")
        .output()
        .unwrap();
    let value = success_json(&initial);
    assert_eq!(value["data"]["coverage"]["source_complete"], false);
    assert_eq!(value["data"]["coverage"]["complete"], false);
    assert!(
        value["data"]["coverage"]["warnings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|warning| {
                warning
                    .as_str()
                    .unwrap()
                    .contains("inherited or forked history")
            })
    );

    let cutoff_record = value["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "history-cutoff")
        .unwrap();
    let cutoff_path = root.path().join("cutoff.json");
    fs::write(
        &cutoff_path,
        serde_json::to_vec(&json!({
            "source_path": parent.to_string_lossy(),
            "record_anchor": cutoff_record["anchor"]
        }))
        .unwrap(),
    )
    .unwrap();
    let snapshot_path = root.path().join("inherited-snapshot.json");
    let bounded = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            THREAD,
            "--snapshot-out",
            snapshot_path.to_str().unwrap(),
            "--cutoff-anchor",
            cutoff_path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env("CODEX_THREAD_ID", "another-current-thread")
        .output()
        .unwrap();
    let inspection = success_json(&bounded);
    let selected = inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["kind"] == "tool_result")
        .expect("inherited child event remains inspectable");
    let request_path = root.path().join("inherited-incident.json");
    let request = capture_request_for_anchor(
        &snapshot_path,
        &inspection,
        &selected["anchor"],
        "failed-tool",
    );
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let store_path = root.path().join("learn-store");
    error_json(
        &run_capture(&request_path, &store_path),
        2,
        "diagnose_capture_uncertain",
    );
    assert!(
        !store_path.exists(),
        "inherited history cannot create a witness"
    );
}

#[test]
fn pagination_reuses_a_frozen_prefix_after_append() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let path = rollout(
        &home,
        THREAD,
        None,
        &[
            json!({"timestamp":"2026-09-27T10:01:00Z", "type":"response_item", "payload":{"type":"message", "role":"user", "content":[{"type":"input_text", "text":"First"}]}}),
            json!({"timestamp":"2026-09-27T10:02:00Z", "type":"response_item", "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"Second"}]}}),
        ],
    );
    let snapshot_path = root.path().join("bounded-evidence.json");
    let first = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            THREAD,
            "--offset",
            "0",
            "--limit",
            "1",
            "--snapshot-out",
            snapshot_path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let first = success_json(&first);
    assert_eq!(first["meta"]["total"], 2);
    assert_eq!(first["meta"]["truncated"], true);
    assert!(snapshot_path.exists());
    let frozen: Value = serde_json::from_slice(&fs::read(&snapshot_path).unwrap()).unwrap();
    assert_eq!(frozen["schema_version"], 1);
    assert_eq!(frozen["records"].as_array().unwrap().len(), 2);
    assert!(frozen["session"]["thread_id"].as_str().is_some());

    let mut file = fs::OpenOptions::new().append(true).open(&path).unwrap();
    writeln!(
        file,
        "{}",
            json!({"timestamp":"2026-09-27T10:03:00Z", "type":"response_item", "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"Appended later"}]}})
    )
    .unwrap();

    let second = command()
        .args([
            "diagnose",
            "inspect",
            "--snapshot-in",
            snapshot_path.to_str().unwrap(),
            "--offset",
            "1",
            "--limit",
            "1",
            "--json",
        ])
        .env("CODEX_HOME", root.path().join("missing-home"))
        .env("CODEX_THREAD_ID", "different-current-session")
        .output()
        .unwrap();
    let second = success_json(&second);
    assert_eq!(second["meta"]["total"], 2);
    assert_eq!(second["data"]["records"][0]["text_excerpt"], "Second");
    assert_eq!(second["data"]["session"]["thread_id"], THREAD);
    assert!(
        !second["data"]["records"]
            .as_array()
            .unwrap()
            .iter()
            .any(|record| record["text_excerpt"] == "Appended later")
    );
    assert_eq!(
        first["data"]["snapshot"]["digest"],
        second["data"]["snapshot"]["digest"]
    );
}

#[test]
fn snapshot_output_never_overwrites_or_aliases_the_source() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let path = rollout(&home, THREAD, None, &[]);
    let original = fs::read(&path).unwrap();
    let source_alias = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            path.to_str().unwrap(),
            "--snapshot-out",
            path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .output()
        .unwrap();
    error_json(&source_alias, 2, "diagnose_snapshot_alias");
    assert_eq!(fs::read(&path).unwrap(), original);

    let existing = root.path().join("existing-bundle.json");
    fs::write(&existing, b"keep me").unwrap();
    let no_clobber = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            path.to_str().unwrap(),
            "--snapshot-out",
            existing.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .output()
        .unwrap();
    error_json(&no_clobber, 2, "diagnose_snapshot_exists");
    assert_eq!(fs::read(&existing).unwrap(), b"keep me");
}

#[test]
fn current_session_without_a_verified_cutoff_is_explicitly_partial() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let path = rollout(
        &home,
        THREAD,
        None,
        &[
            json!({"timestamp":"2026-09-27T10:01:00Z", "type":"response_item", "payload":{"type":"message", "role":"user", "content":[{"type":"input_text", "text":"Please diagnose this session"}]}}),
        ],
    );
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            THREAD,
            "--json",
        ])
        .env("CODEX_HOME", home)
        .env("CODEX_THREAD_ID", THREAD)
        .output()
        .unwrap();
    let value = success_json(&output);
    assert_eq!(value["data"]["overlap"], "current");
    assert_eq!(value["data"]["coverage"]["cutoff_verified"], false);
    assert_eq!(value["data"]["coverage"]["analysis_ready"], false);
    assert_eq!(value["data"]["coverage"]["incomplete_tail"], false);
    assert!(path.exists());
}

#[test]
fn cutoff_anchor_verifies_a_request_record_and_snapshot_rejects_tampering() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let path = rollout(
        &home,
        THREAD,
        None,
        &[
            json!({"timestamp":"2026-09-27T10:01:00Z", "type":"response_item", "payload":{"type":"message", "role":"user", "content":[{"type":"input_text", "text":"Please diagnose this session"}]}}),
            json!({"timestamp":"2026-09-27T10:02:00Z", "type":"response_item", "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"Diagnosis orchestration follows"}]}}),
        ],
    );
    let discovery = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let discovered = success_json(&discovery);
    let request = discovered["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["role"] == "user")
        .unwrap();
    let anchor = json!({
        "source_path": path.canonicalize().unwrap(),
        "record_anchor": request["anchor"],
    });
    let cutoff = root.path().join("cutoff.json");
    fs::write(&cutoff, anchor.to_string()).unwrap();
    let frozen = root.path().join("bundle.json");
    let accepted = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            path.to_str().unwrap(),
            "--cutoff-anchor",
            cutoff.to_str().unwrap(),
            "--snapshot-out",
            frozen.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let accepted = success_json(&accepted);
    assert_eq!(accepted["data"]["coverage"]["cutoff_verified"], true);
    assert_eq!(accepted["data"]["coverage"]["analysis_ready"], true);
    assert_eq!(
        accepted["data"]["coverage"]["cutoff_anchor"]["record_digest"],
        request["anchor"]["record_digest"]
    );

    let mut tampered: Value = serde_json::from_slice(&fs::read(&frozen).unwrap()).unwrap();
    tampered["records"][0]["text_excerpt"] = json!("tampered evidence");
    fs::write(&frozen, tampered.to_string()).unwrap();
    let rejected = command()
        .args([
            "diagnose",
            "inspect",
            "--snapshot-in",
            frozen.to_str().unwrap(),
            "--json",
        ])
        .output()
        .unwrap();
    error_json(&rejected, 2, "diagnose_snapshot_invalid");
}

#[test]
fn codex_records_keep_bounded_tool_failure_and_per_response_usage_details() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let path = rollout(
        &home,
        THREAD,
        None,
        &[
            json!({
                "timestamp":"2026-09-27T10:01:00Z",
                "type":"response_item",
                "payload":{"type":"function_call", "name":"shell", "call_id":"call-1", "arguments":{"command":"cargo test", "cwd":"/historic/worktree"}}
            }),
            json!({
                "timestamp":"2026-09-27T10:01:01Z",
                "type":"response_item",
                "payload":{"type":"function_call_output", "call_id":"call-1", "output":"command failed: missing fixture"}
            }),
            json!({
                "timestamp":"2026-09-27T10:01:02Z",
                "type":"event_msg",
                "payload":{"type":"turn_failed", "turn_id":"turn-1", "reason":"test process exited 101"}
            }),
            json!({
                "timestamp":"2026-09-27T10:01:03Z",
                "type":"token_usage_record",
                "payload":{
                    "thread_id":"thread-native",
                    "turn_id":"turn-1",
                    "response_id":"response-1",
                    "usage":{"input_tokens":10,"cached_input_tokens":4,"output_tokens":3,"reasoning_output_tokens":1,"total_tokens":13},
                    "turn_token_usage":{"input_tokens":10,"output_tokens":3,"total_tokens":13},
                    "thread_token_usage":{"input_tokens":80,"output_tokens":12,"total_tokens":92}
                }
            }),
            json!({
                "timestamp":"2026-09-27T10:01:04Z",
                "type":"future_record_v9",
                "payload":{"detail":"x".repeat(2_000)}
            }),
        ],
    );
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let value = success_json(&output);
    let records = value["data"]["records"].as_array().unwrap();
    let call = records
        .iter()
        .find(|record| record["kind"] == "tool_call")
        .unwrap();
    assert_eq!(call["tool_name"], "shell");
    assert!(
        call["tool_input_excerpt"]
            .as_str()
            .unwrap()
            .contains("cargo test")
    );
    let result = records
        .iter()
        .find(|record| record["kind"] == "tool_result")
        .unwrap();
    assert!(
        result["tool_output_excerpt"]
            .as_str()
            .unwrap()
            .contains("missing fixture")
    );
    let failure = records
        .iter()
        .find(|record| record["kind"] == "turn_failed")
        .unwrap();
    assert_eq!(failure["failure_reason"], "test process exited 101");
    let usage = records
        .iter()
        .find(|record| record["kind"] == "token_usage_record")
        .unwrap();
    assert_eq!(usage["response_id"], "response-1");
    assert_eq!(usage["usage_record"]["usage"]["input_tokens"], 10);
    assert_eq!(
        usage["usage_record"]["thread_token_usage"]["total_tokens"],
        92
    );
    let unknown = records
        .iter()
        .find(|record| record["kind"] == "future_record_v9")
        .unwrap();
    assert!(unknown["unknown_payload_excerpt"].as_str().unwrap().len() <= 515);
    assert_eq!(unknown["detail_truncated"], true);
    assert!(
        value["data"]["coverage"]["warnings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|warning| warning
                .as_str()
                .unwrap()
                .contains("unknown Codex event types"))
    );
}

#[test]
fn record_revalidation_accepts_append_but_rejects_rewrite_and_inode_replacement() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let path = rollout(
        &home,
        THREAD,
        None,
        &[
            json!({"timestamp":"2026-09-27T10:01:00Z", "type":"turn_context", "payload":{"turn_id":"turn-1", "cwd":"/historic/event-cwd"}}),
            json!({"timestamp":"2026-09-27T10:02:00Z", "type":"event_msg", "payload":{"type":"turn_failed", "turn_id":"turn-1", "reason":"fixture failure"}}),
        ],
    );
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let value = success_json(&output);
    let source: SourceSnapshot =
        serde_json::from_value(value["data"]["sources"][0].clone()).unwrap();
    let anchor: RecordAnchor = serde_json::from_value(
        value["data"]["records"]
            .as_array()
            .unwrap()
            .iter()
            .find(|record| record["kind"] == "turn_failed")
            .unwrap()["anchor"]
            .clone(),
    )
    .unwrap();
    let original_contents = fs::read(&path).unwrap();
    let verified = revalidate_record_anchor(&source, &anchor).unwrap();
    assert_eq!(verified.cwd.as_deref(), Some("/historic/event-cwd"));

    let mut file = fs::OpenOptions::new().append(true).open(&path).unwrap();
    writeln!(
        file,
        "{}",
        json!({"type":"event_msg", "payload":{"type":"task_complete"}})
    )
    .unwrap();
    assert_eq!(
        revalidate_record_anchor(&source, &anchor).unwrap().kind,
        "turn_failed"
    );

    fs::write(&path, &original_contents).unwrap();
    let rewritten = std::fs::OpenOptions::new().write(true).open(&path).unwrap();
    rewritten
        .set_times(
            std::fs::FileTimes::new()
                .set_modified(std::time::SystemTime::now() + std::time::Duration::from_secs(5)),
        )
        .unwrap();
    assert!(revalidate_record_anchor(&source, &anchor).is_err());

    let replacement = root.path().join("replacement.jsonl");
    fs::write(&replacement, &original_contents).unwrap();
    fs::rename(&replacement, &path).unwrap();
    assert!(revalidate_record_anchor(&source, &anchor).is_err());
}

#[test]
fn record_revalidation_rederives_native_identity_and_jsonl_line_position() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let path = rollout(
        &home,
        THREAD,
        None,
        &[json!({
            "timestamp":"2026-09-27T10:01:00Z",
            "type":"event_msg",
            "id":"actual-native-id",
            "payload":{"type":"turn_failed", "reason":"fixture"}
        })],
    );
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let inspection = success_json(&output);
    let source: SourceSnapshot =
        serde_json::from_value(inspection["data"]["sources"][0].clone()).unwrap();
    let failure = inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["kind"] == "turn_failed")
        .unwrap();
    let mut anchor: RecordAnchor = serde_json::from_value(failure["anchor"].clone()).unwrap();
    assert_eq!(anchor.native_id.as_deref(), Some("actual-native-id"));

    anchor.native_id = Some("invented-native-id".into());
    assert!(revalidate_record_anchor(&source, &anchor).is_err());
    anchor.native_id = Some("actual-native-id".into());
    anchor.record_index = 999;
    assert!(revalidate_record_anchor(&source, &anchor).is_err());
}

#[test]
fn unknown_codex_version_and_oversized_record_fail_closed_with_coverage() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let unknown_version = rollout(&home, THREAD, None, &[]);
    let mut first: Value = serde_json::from_str(
        fs::read_to_string(&unknown_version)
            .unwrap()
            .lines()
            .next()
            .unwrap(),
    )
    .unwrap();
    first["payload"]["cli_version"] = json!("0.156.0");
    let rest = fs::read_to_string(&unknown_version)
        .unwrap()
        .lines()
        .skip(1)
        .collect::<Vec<_>>()
        .join("\n");
    fs::write(&unknown_version, format!("{}\n{}\n", first, rest)).unwrap();
    let unsupported = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            unknown_version.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .output()
        .unwrap();
    error_json(&unsupported, 2, "diagnose_codex_version_unsupported");

    let oversized_home = root.path().join("oversized-home");
    let oversized_path = rollout(
        &oversized_home,
        "thread-oversized-fixture",
        None,
        &[
            json!({"timestamp":"2026-09-27T10:01:00Z", "type":"event_msg", "payload":{"type":"future_payload", "text":"x".repeat(300_000)}}),
        ],
    );
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--path",
            oversized_path.to_str().unwrap(),
            "--json",
        ])
        .env("CODEX_HOME", &oversized_home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let value = success_json(&output);
    assert_eq!(value["data"]["coverage"]["complete"], false);
    assert_eq!(value["data"]["coverage"]["truncated"], true);
    assert!(
        value["data"]["coverage"]["malformed_records"]
            .as_u64()
            .unwrap()
            > 0
    );
}

#[test]
fn current_target_requires_verified_thread_context() {
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--current",
            "--json",
        ])
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    error_json(&output, 2, "diagnose_current_unavailable");
}

#[test]
fn conflicting_intakes_are_typed_errors() {
    let conflicting = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--current",
            "--session",
            THREAD,
            "--json",
        ])
        .output()
        .unwrap();
    error_json(&conflicting, 2, "usage_error");
}

#[test]
fn opencode_export_path_preserves_failed_tools_and_discloses_export_limits() {
    let root = TempDir::new().unwrap();
    let data_root = root.path().join("share");
    let export_path = data_root
        .join("opencode/exports")
        .join("session-export.json");
    fs::create_dir_all(export_path.parent().unwrap()).unwrap();
    fs::write(
        &export_path,
        serde_json::to_vec(&json!({
            "info": {
                "id": "ses_export_fixture",
                "projectID": "project_fixture",
                "parentID": null,
                "fork": null,
                "title": "Synthetic export",
                "location": {"directory": "/fixture/A"},
                "time": {"created": "2026-09-27T10:00:00Z"}
            },
            "messages": [
                {
                    "id": "msg_export_user",
                    "type": "user",
                    "text": "Synthetic question",
                    "time": {"created": "2026-09-27T10:00:00Z"}
                },
                {
                    "id": "msg_export_tool",
                    "type": "assistant",
                    "agent": "build",
                    "model": {"id":"synthetic-model", "providerID":"synthetic-provider"},
                    "content": [{
                        "type":"tool", "id":"tool_export_fail", "name":"bash",
                        "state": {
                            "status":"error", "input":{"command":"false"},
                            "error":{"type":"tool.execution", "message":"Synthetic exit 1"}
                        },
                        "time": {
                            "created":"2026-09-27T10:00:00.010Z",
                            "ran":"2026-09-27T10:00:00.020Z",
                            "completed":"2026-09-27T10:00:00.030Z"
                        }
                    }],
                    "time": {
                        "created":"2026-09-27T10:00:00.010Z",
                        "completed":"2026-09-27T10:00:00.040Z"
                    },
                    "tokens": {"input":10, "output":3, "reasoning":2, "cache":{"read":7, "write":4}}
                }
            ]
        }))
        .unwrap(),
    )
    .unwrap();

    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "opencode",
            "--path",
            export_path.to_str().unwrap(),
            "--json",
        ])
        .env("HOME", root.path())
        .env("XDG_DATA_HOME", &data_root)
        .env_remove("OPENCODE_DB")
        .output()
        .unwrap();
    let value = success_json(&output);
    assert_eq!(value["data"]["session"]["harness"], "opencode");
    assert_eq!(value["data"]["session"]["session_id"], "ses_export_fixture");
    assert!(!value["data"]["coverage"]["complete"].as_bool().unwrap());
    assert!(
        value["data"]["coverage"]["warnings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|warning| warning.as_str().unwrap().contains("export"))
    );
    let tool = value["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["kind"] == "tool_call")
        .unwrap();
    assert_eq!(tool["tool_status"], "error");
    assert_eq!(tool["tool_error"], "Synthetic exit 1");
    assert_eq!(tool["timestamp"], "2026-09-27T10:00:00.010Z");
    assert_eq!(tool["usage_record"]["total_tokens"], 26);
}

#[test]
fn opencode_export_preserves_all_tool_blocks_and_top_level_failures() {
    let root = TempDir::new().unwrap();
    let export_path = root.path().join("session.json");
    fs::write(
        &export_path,
        serde_json::to_vec(&json!({
            "info": {
                "id":"ses_multi_tool",
                "projectID":"project_fixture",
                "parentID":null,
                "fork":null,
                "title":"Synthetic multi-tool export",
                "location":{"directory":"/fixture/repo"},
                "time":{"created":"2023-11-14T22:13:20Z"}
            },
            "messages":[
                {
                    "id":"msg_multi_tool",
                    "type":"assistant",
                    "agent":"build",
                    "model":{"id":"fixture-model","providerID":"fixture-provider"},
                    "content":[
                        {
                            "type":"tool","id":"tool_first","name":"bash",
                            "state":{"status":"completed","input":{"command":"true"},
                                "content":[{"type":"text","text":"synthetic successful output"}]},
                            "time":{"created":"2023-11-14T22:13:20.010Z","completed":"2023-11-14T22:13:20.030Z"}
                        },
                        {
                            "type":"tool","id":"tool_second","name":"bash",
                            "state":{"status":"error","input":{"command":"false"},
                                "error":{"type":"tool.execution","message":"synthetic second failure"},
                                "content":[{"type":"text","text":"synthetic failed output"}]},
                            "time":{"created":"2023-11-14T22:13:20.010Z","completed":"2023-11-14T22:13:20.030Z"}
                        }
                    ],
                    "time":{"created":"2023-11-14T22:13:20Z","completed":"2023-11-14T22:13:20.040Z"},
                    "tokens":{"input":10,"output":3,"reasoning":2,"cache":{"read":7,"write":4}}
                },
                {
                    "id":"msg_assistant_error","type":"assistant","content":[],
                    "error":{"type":"provider.quota","message":"synthetic quota failure"},
                    "time":{"created":"2023-11-14T22:13:21Z","completed":"2023-11-14T22:13:21.010Z"}
                },
                {
                    "id":"msg_compaction_error","type":"compaction","status":"failed","reason":"manual",
                    "error":{"type":"provider.transport","message":"synthetic compaction failure"},
                    "time":{"created":"2023-11-14T22:13:22Z"}
                }
            ]
        }))
        .unwrap(),
    )
    .unwrap();

    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "opencode",
            "--path",
            export_path.to_str().unwrap(),
            "--json",
        ])
        .env("HOME", root.path())
        .env("XDG_DATA_HOME", root.path().join("share"))
        .env_remove("OPENCODE_DB")
        .output()
        .unwrap();
    let value = success_json(&output);
    let records = value["data"]["records"].as_array().unwrap();
    let tool = records
        .iter()
        .find(|record| record["anchor"]["native_id"] == "msg_multi_tool")
        .unwrap();
    assert_eq!(tool["usage_record"]["total_tokens"], 26);
    let observations = tool["tool_observations"].as_array().unwrap();
    assert_eq!(observations.len(), 2);
    assert_eq!(observations[0]["tool_use_id"], "tool_first");
    assert_eq!(observations[0]["status"], "completed");
    assert!(
        observations[0]["output_excerpt"]
            .as_str()
            .unwrap()
            .contains("synthetic successful output")
    );
    assert_eq!(observations[1]["tool_use_id"], "tool_second");
    assert_eq!(observations[1]["status"], "error");
    assert!(
        observations[1]["error"]
            .as_str()
            .unwrap()
            .contains("synthetic second failure")
    );
    assert!(tool["anchor"]["native_id"].is_string());
    assert!(
        observations
            .iter()
            .all(|observation| observation.get("record_anchor").is_none())
    );

    let assistant_error = records
        .iter()
        .find(|record| record["anchor"]["native_id"] == "msg_assistant_error")
        .unwrap();
    assert!(
        assistant_error["failure_reason"]
            .as_str()
            .unwrap()
            .contains("synthetic quota failure")
    );
    let compaction = records
        .iter()
        .find(|record| record["anchor"]["native_id"] == "msg_compaction_error")
        .unwrap();
    assert_eq!(compaction["tool_status"], "failed");
    assert!(
        compaction["failure_reason"]
            .as_str()
            .unwrap()
            .contains("synthetic compaction failure")
    );
}

#[test]
fn claude_multi_tool_result_retains_later_failure_with_shared_anchor() {
    let root = TempDir::new().unwrap();
    let projects_root = root.path().join("claude-config/projects");
    let project_dir = projects_root.join("project-fixture");
    let session_id = "00000000-0000-4000-8000-000000000002";
    claude_main(
        &project_dir,
        session_id,
        &[json!({
            "type":"user","uuid":"record-multiple-results","parentUuid":null,
            "sessionId":session_id,"timestamp":"2023-11-14T22:13:20.000Z","cwd":"/fixture/repo",
            "message":{"role":"user","content":[
                {"type":"tool_result","tool_use_id":"tool_first","is_error":false,"content":"synthetic success"},
                {"type":"tool_result","tool_use_id":"tool_second","is_error":true,"content":"synthetic second failure"}
            ]}
        })],
    );

    let value = claude_request(&projects_root, session_id);
    let record = value["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "record-multiple-results")
        .unwrap();
    let observations = record["tool_observations"].as_array().unwrap();
    assert_eq!(observations.len(), 2);
    assert_eq!(observations[0]["tool_use_id"], "tool_first");
    assert_eq!(observations[0]["status"], "success");
    assert_eq!(observations[1]["tool_use_id"], "tool_second");
    assert_eq!(observations[1]["status"], "error");
    assert!(
        observations[1]["error"]
            .as_str()
            .unwrap()
            .contains("synthetic second failure")
    );
    assert!(record["anchor"]["native_id"].is_string());
    assert!(
        observations
            .iter()
            .all(|observation| observation.get("record_anchor").is_none())
    );
}

#[test]
fn codex_failed_header_reads_exhaust_the_byte_budget_separately_from_entry_limit() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let sessions = home.join("sessions/2026/09/27");
    fs::create_dir_all(&sessions).unwrap();
    let per_header = MAX_RECORD_BYTES + 1;
    let header = vec![b'x'; per_header];
    let count = (16 * 1024 * 1024 / per_header) + 1;
    for index in 0..count {
        fs::write(
            sessions.join(format!("rollout-invalid-{index:03}.jsonl")),
            &header,
        )
        .unwrap();
    }
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            "missing",
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let value = error_json(&output, 2, "diagnose_discovery_incomplete");
    assert!(
        value["data"]["error"]["message"]
            .as_str()
            .unwrap()
            .contains("byte budget")
    );
    assert!(
        !value["data"]["error"]["message"]
            .as_str()
            .unwrap()
            .contains("entry scan limit")
    );
}

#[test]
fn codex_entry_exhaustion_keeps_its_distinct_discovery_reason() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    let sessions = home.join("sessions/2026/09/27");
    fs::create_dir_all(&sessions).unwrap();
    for index in 0..=MAX_DISCOVERY_FILES {
        fs::write(sessions.join(format!("ignored-{index:04}.txt")), b"").unwrap();
    }
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            "missing",
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env_remove("CODEX_THREAD_ID")
        .output()
        .unwrap();
    let value = error_json(&output, 2, "diagnose_discovery_incomplete");
    assert!(
        value["data"]["error"]["message"]
            .as_str()
            .unwrap()
            .contains("entry scan limit")
    );
}

#[test]
fn claude_failed_child_attempt_consumes_remaining_family_byte_budget() {
    let root = TempDir::new().unwrap();
    let projects_root = root.path().join("claude-config/projects");
    let project_dir = projects_root.join("project-fixture");
    let session_id = "00000000-0000-4000-8000-000000000003";
    claude_main(
        &project_dir,
        session_id,
        &[json!({
            "type":"assistant","uuid":"record-spawn","parentUuid":null,"sessionId":session_id,
            "timestamp":"2023-11-14T22:13:20.000Z","cwd":"/fixture/repo",
            "message":{"id":"message-spawn","role":"assistant","content":[
                {"type":"tool_use","id":"tool-spawn","name":"Agent","input":{"description":"spawn"}}
            ]}
        })],
    );
    for (suffix, agent_id) in [("a", "invalid-a"), ("b", "invalid-b")] {
        let invalid = claude_agent(
            &project_dir,
            session_id,
            &format!("agent-{suffix}-invalid.jsonl"),
            &[json!({
                "type":"assistant","uuid":format!("record-invalid-child-{suffix}"),"parentUuid":null,
                "sessionId":session_id,"agentId":agent_id,"isSidechain":true,
                "message":{"id":format!("child-invalid-{suffix}"),"role":"assistant","content":[{"type":"text","text":"wrong header"}]}
            })],
            Some(json!({"toolUseId":"tool-spawn"})),
        );
        let mut invalid_first: Value = serde_json::from_str(
            fs::read_to_string(&invalid)
                .unwrap()
                .lines()
                .next()
                .unwrap(),
        )
        .unwrap();
        invalid_first["sessionId"] = json!("different-session");
        fs::write(
            &invalid,
            format!(
                "{}\n{}",
                invalid_first,
                "x".repeat(MAX_FAMILY_SOURCE_BYTES / 2 + 1024)
            ),
        )
        .unwrap();
    }
    claude_agent(
        &project_dir,
        session_id,
        "agent-z-valid.jsonl",
        &[json!({
            "type":"assistant","uuid":"record-valid-child","parentUuid":null,
            "sessionId":session_id,"agentId":"valid","isSidechain":true,
            "timestamp":"2023-11-14T22:13:21.000Z",
            "message":{"id":"child-valid","role":"assistant","content":[{"type":"text","text":"must remain unread"}]}
        })],
        Some(json!({"toolUseId":"tool-spawn"})),
    );

    let value = claude_request(&projects_root, session_id);
    assert!(
        !value["records"]
            .as_array()
            .unwrap()
            .iter()
            .any(|record| record["anchor"]["native_id"] == "record-valid-child"),
        "the invalid child read consumes the family byte allowance before the next child attempt: {value:#}"
    );
    assert_eq!(value["coverage"]["source_complete"], false);
    assert_eq!(value["coverage"]["truncated"], true);
    assert!(
        value["coverage"]["warnings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|warning| { warning.as_str().unwrap().contains("aggregate byte") })
    );
}

#[test]
fn opencode_current_requires_a_verified_native_caller_context() {
    let root = TempDir::new().unwrap();
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "opencode",
            "--current",
            "--json",
        ])
        .env("HOME", root.path())
        .env("XDG_DATA_HOME", root.path().join("share"))
        .env("OPENCODE_SESSION_ID", "must-not-be-trusted")
        .output()
        .unwrap();
    error_json(&output, 2, "diagnose_current_unavailable");
}

#[test]
fn claude_selected_session_preserves_transcript_namespaces_links_and_usage() {
    let root = TempDir::new().unwrap();
    let projects_root = root.path().join("claude-config/projects");
    let project_dir = projects_root.join("project-namespace");
    let session_id = "00000000-0000-4000-8000-000000000001";
    let main = claude_main(
        &project_dir,
        session_id,
        &[
            json!({
                "type":"assistant", "uuid":"record-collision", "parentUuid":null,
                "sessionId":session_id, "cwd":"/historic/main", "isSidechain":false,
                "timestamp":"2026-09-27T10:00:00Z",
                "message":{
                    "id":"provider-message-shared", "role":"assistant",
                    "content":[{"type":"tool_use", "id":"tool-spawn", "name":"Agent", "input":{"description":"spawn a child"}}],
                    "usage":{"input_tokens":10,"cache_read_input_tokens":5,"cache_creation_input_tokens":3,"output_tokens":2}
                }
            }),
            json!({
                "type":"assistant", "uuid":"record-main-snapshot", "parentUuid":"record-collision",
                "sessionId":session_id,
                "message":{
                    "id":"provider-message-shared", "role":"assistant",
                    "content":[{"type":"text", "text":"A later cumulative snapshot"}],
                    "usage":{"output_tokens":4}
                }
            }),
            json!({
                "type":"user", "uuid":"record-tool-failure", "parentUuid":"record-main-snapshot",
                "sessionId":session_id, "cwd":"/historic/main",
                "message":{"role":"user", "content":[{"type":"tool_result", "tool_use_id":"tool-shared", "is_error":true, "content":"synthetic failed tool"}]}
            }),
            json!({
                "type":"progress", "uuid":"record-progress", "parentUuid":"record-tool-failure",
                "sessionId":session_id, "data":{"message":"synthetic progress detail"}
            }),
            json!({
                "type":"user", "uuid":"record-compaction", "parentUuid":"record-progress",
                "sessionId":session_id, "isCompactSummary":true,
                "message":{"role":"user", "content":[{"type":"text", "text":"synthetic compacted context"}]}
            }),
            json!({
                "type":"future_native_record", "uuid":"record-future", "parentUuid":"record-compaction",
                "sessionId":session_id, "future_field":{"detail":"preserve this bounded unknown"}
            }),
        ],
    );
    let child = claude_agent(
        &project_dir,
        session_id,
        "workflows/run-1/agent-agent-fixture.jsonl",
        &[
            json!({
                "type":"assistant", "uuid":"record-collision", "parentUuid":null,
                "sessionId":session_id, "agentId":"agent-fixture", "isSidechain":true,
                "message":{
                    "id":"provider-message-shared", "role":"assistant",
                    "content":[{"type":"tool_use", "id":"tool-shared", "name":"Bash", "input":{"command":"false"}}],
                    "usage":{"input_tokens":10,"cache_read_input_tokens":5,"cache_creation_input_tokens":3,"output_tokens":2}
                }
            }),
            json!({
                "type":"assistant", "uuid":"record-child-spawn", "parentUuid":"record-collision",
                "sessionId":session_id, "agentId":"agent-fixture", "isSidechain":true,
                "message":{"id":"provider-child-spawn", "role":"assistant", "content":[{"type":"tool_use", "id":"tool-nested-spawn", "name":"Agent", "input":{"description":"nested child"}}]}
            }),
        ],
        Some(json!({"toolUseId":"tool-spawn", "parentAgentId":null})),
    );
    let nested = claude_agent(
        &project_dir,
        session_id,
        "workflows/run-1/nested/agent-nested.jsonl",
        &[
            json!({
                "type":"assistant", "uuid":"record-nested-spawn", "parentUuid":null,
                "sessionId":session_id, "agentId":"nested", "isSidechain":true,
                "message":{"id":"provider-nested-spawn", "role":"assistant", "content":[{"type":"tool_use", "id":"tool-nested-spawn", "name":"Agent", "input":{"description":"nested child"}}]}
            }),
            json!({
                "type":"assistant", "uuid":"record-nested", "parentUuid":"record-nested-spawn",
                "sessionId":session_id, "agentId":"nested", "isSidechain":true,
                "message":{"id":"provider-nested", "role":"assistant", "content":[{"type":"text", "text":"nested child"}]}
            }),
        ],
        Some(json!({"toolUseId":"tool-nested-spawn", "parentAgentId":"agent-fixture"})),
    );
    let orphan = claude_agent(
        &project_dir,
        session_id,
        "workflows/run-1/orphan/agent-orphan.jsonl",
        &[json!({
            "type":"assistant", "uuid":"record-orphan", "parentUuid":null,
            "sessionId":session_id, "agentId":"orphan", "isSidechain":true,
            "message":{"id":"provider-orphan", "role":"assistant", "content":[{"type":"text", "text":"orphan link"}]}
        })],
        None,
    );

    let value = claude_request(&projects_root, session_id);
    assert_eq!(value["session"]["session_id"], session_id);
    assert!(
        value["session"]["thread_id"]
            .as_str()
            .unwrap()
            .contains("project-namespace")
    );
    let records = value["records"].as_array().unwrap();
    let collisions = records
        .iter()
        .filter(|record| record["provider_message_id"] == "provider-message-shared")
        .collect::<Vec<_>>();
    assert_eq!(
        collisions.len(),
        3,
        "same UUID/provider ID in main and child transcripts remains separate evidence"
    );
    assert_eq!(collisions[0]["anchor"]["native_id"], "record-collision");
    assert_eq!(
        collisions[0]["transcript_id"],
        collisions[1]["transcript_id"]
    );
    assert_ne!(
        collisions[0]["transcript_id"],
        collisions[2]["transcript_id"]
    );
    assert_eq!(
        collisions[0]["usage_record"],
        Value::Null,
        "later cumulative snapshot supersedes earlier usage in the same transcript"
    );
    assert_eq!(collisions[1]["usage_record"]["cache_read_input_tokens"], 5);
    assert_eq!(
        collisions[1]["usage_record"]["cache_creation_input_tokens"],
        3
    );
    assert_eq!(collisions[1]["usage_record"]["input_tokens"], 10);
    assert_eq!(collisions[1]["usage_record"]["output_tokens"], 4);
    assert_eq!(
        collisions[2]["usage_record"]["input_tokens"], 10,
        "child namespace usage remains distinct"
    );
    assert_eq!(collisions[2]["parent_tool_use_id"], "tool-spawn");
    assert_eq!(collisions[2]["agent_id"], "agent-fixture");
    let failure = records
        .iter()
        .find(|record| record["kind"] == "tool_result")
        .unwrap();
    assert_eq!(failure["tool_status"], "error");
    assert_eq!(failure["tool_error"], "synthetic failed tool");
    assert_eq!(failure["tool_use_id"], "tool-shared");
    let source: SourceSnapshot = serde_json::from_value(
        value["sources"]
            .as_array()
            .unwrap()
            .iter()
            .find(|source| source["source_id"] == failure["anchor"]["source_id"])
            .unwrap()
            .clone(),
    )
    .unwrap();
    let anchor: RecordAnchor = serde_json::from_value(failure["anchor"].clone()).unwrap();
    let revalidated = revalidate_record_anchor(&source, &anchor).unwrap();
    assert_eq!(revalidated.provider_message_id.as_deref(), None);
    assert_eq!(revalidated.tool_status.as_deref(), Some("error"));
    assert_eq!(
        revalidated.tool_error.as_deref(),
        Some("synthetic failed tool")
    );
    let unknown = records
        .iter()
        .find(|record| record["anchor"]["native_id"] == "record-future")
        .unwrap();
    assert!(
        unknown["unknown_payload_excerpt"]
            .as_str()
            .unwrap()
            .contains("future_field")
    );
    assert!(records.iter().any(|record| record["kind"] == "progress"));
    assert!(
        records
            .iter()
            .any(|record| record["is_compact_summary"] == true)
    );
    assert!(
        value["coverage"]["warnings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|warning| { warning.as_str().unwrap().contains("unknown Claude") })
    );
    assert_eq!(value["coverage"]["source_complete"], false);
    let children = value["children"].as_array().unwrap();
    assert_eq!(children.len(), 3);
    assert!(children.iter().any(|item| {
        item["agent_id"] == "nested"
            && item["parent_agent_id"] == "agent-fixture"
            && !item["parent_thread_id"].is_null()
    }));
    assert!(children.iter().any(|item| {
        item["agent_id"] == "agent-fixture"
            && item["parent_tool_use_id"] == "tool-spawn"
            && !item["parent_thread_id"].is_null()
    }));
    assert!(children.iter().any(|item| {
        item["agent_id"] == "orphan"
            && item["parent_tool_use_id"].is_null()
            && item["parent_thread_id"].is_null()
    }));
    assert!(child.exists() && nested.exists() && orphan.exists() && main.exists());
}

#[test]
fn claude_duplicate_session_ids_across_project_namespaces_are_ambiguous() {
    let root = TempDir::new().unwrap();
    let projects_root = root.path().join("claude-config/projects");
    let session_id = "00000000-0000-4000-8000-000000000002";
    let entry = json!({
        "type":"user", "uuid":"record-user", "sessionId":session_id,
        "message":{"role":"user", "content":"synthetic prompt"}
    });
    claude_main(
        &projects_root.join("project-a"),
        session_id,
        std::slice::from_ref(&entry),
    );
    claude_main(&projects_root.join("project-b"), session_id, &[entry]);

    let request = InspectRequest {
        harness: Some(DiagnosticHarness::Claude),
        intake: Intake::Session {
            source_root: projects_root,
            session_id: session_id.to_owned(),
        },
        offset: 0,
        limit: 10,
        snapshot_out: None,
        cutoff_anchor: None,
    };
    let error = inspect(&request).unwrap_err();
    assert_eq!(error.code(), "diagnose_session_ambiguous");
}

#[test]
fn claude_cli_uses_configured_projects_root_and_rejects_unverified_current_input() {
    let root = TempDir::new().unwrap();
    let config = root.path().join("custom-claude-config");
    let projects_root = config.join("projects");
    let session_id = "00000000-0000-4000-8000-000000000003";
    let main = claude_main(
        &projects_root.join("project-cli"),
        session_id,
        &[json!({
            "type":"user", "uuid":"record-cli", "sessionId":session_id,
            "message":{"role":"user", "content":"configured root"}
        })],
    );
    let selected = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "claude",
            "--session",
            session_id,
            "--json",
        ])
        .env("CLAUDE_CONFIG_DIR", &config)
        .output()
        .unwrap();
    let selected = success_json(&selected);
    assert_eq!(selected["data"]["session"]["harness"], "claude");
    assert_eq!(selected["data"]["session"]["session_id"], session_id);

    let mut current = std::process::Command::new(env!("CARGO_BIN_EXE_varde-learn"))
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "claude",
            "--current",
            "--json",
        ])
        .env("CLAUDE_CONFIG_DIR", &config)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    current
        .stdin
        .take()
        .unwrap()
        .write_all(
            json!({
                "session_id":session_id,
                "transcript_path":main,
                "cwd":"/historical/current"
            })
            .to_string()
            .as_bytes(),
        )
        .unwrap();
    let current = success_json(&current.wait_with_output().unwrap());
    assert_eq!(current["data"]["overlap"], "current");
    assert_eq!(current["data"]["coverage"]["analysis_ready"], false);

    let unavailable = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "claude",
            "--current",
            "--json",
        ])
        .env("CLAUDE_CONFIG_DIR", &config)
        .output()
        .unwrap();
    error_json(&unavailable, 2, "diagnose_current_unavailable");
}

#[test]
fn claude_current_hook_must_match_a_child_in_the_verified_session_family() {
    let root = TempDir::new().unwrap();
    let projects_root = root.path().join("claude-config/projects");
    let project_dir = projects_root.join("project-current");
    let session_id = "00000000-0000-4000-8000-000000000004";
    let main = claude_main(
        &project_dir,
        session_id,
        &[json!({
            "type":"user", "uuid":"record-current", "sessionId":session_id,
            "message":{"role":"user", "content":"current hook context"}
        })],
    );
    let child = claude_agent(
        &project_dir,
        session_id,
        "run/agent-current-child.jsonl",
        &[json!({
            "type":"assistant", "uuid":"record-current-child", "sessionId":session_id,
            "agentId":"current-child", "isSidechain":true,
            "message":{"id":"message-current-child", "role":"assistant", "content":"child"}
        })],
        Some(json!({"toolUseId":"tool-parent", "parentAgentId":null})),
    );
    let inspection = inspect(&InspectRequest {
        harness: Some(DiagnosticHarness::Claude),
        intake: Intake::Current {
            source_root: projects_root.clone(),
            session_id: Some(session_id.to_owned()),
            claude_hook: Some(ClaudeHookContext {
                transcript_path: main.clone(),
                cwd: Some(project_dir),
                agent_id: Some("current-child".into()),
                agent_transcript_path: Some(child.clone()),
            }),
        },
        offset: 0,
        limit: 100,
        snapshot_out: None,
        cutoff_anchor: None,
    })
    .unwrap();
    assert!(matches!(
        inspection.overlap,
        varde_learn_core::diagnose::CurrentOverlap::Current
    ));
    assert!(!inspection.coverage.analysis_ready);
    assert!(
        inspection
            .records
            .iter()
            .any(|record| record.text_excerpt.as_deref() == Some("child"))
    );

    let invalid = inspect(&InspectRequest {
        harness: Some(DiagnosticHarness::Claude),
        intake: Intake::Current {
            source_root: projects_root,
            session_id: Some(session_id.to_owned()),
            claude_hook: Some(ClaudeHookContext {
                transcript_path: main,
                cwd: None,
                agent_id: Some("wrong-agent".into()),
                agent_transcript_path: Some(child),
            }),
        },
        offset: 0,
        limit: 100,
        snapshot_out: None,
        cutoff_anchor: None,
    })
    .unwrap_err();
    assert_eq!(invalid.code(), "diagnose_current_context_invalid");
}

#[test]
fn claude_cutoff_orders_fractional_rfc3339_times_as_instants() {
    let root = TempDir::new().unwrap();
    let projects_root = root.path().join("claude-config/projects");
    let project_dir = projects_root.join("project-time");
    let session_id = "00000000-0000-4000-8000-000000000005";
    let main = claude_main(
        &project_dir,
        session_id,
        &[
            json!({
                "type":"user", "uuid":"record-cutoff", "sessionId":session_id,
                "timestamp":"2026-09-27T10:00:00Z",
                "message":{"role":"user", "content":"verified request"}
            }),
            json!({
                "type":"assistant", "uuid":"record-cutoff-spawn", "sessionId":session_id,
                "timestamp":"2026-09-27T10:00:00Z",
                "message":{"id":"message-cutoff-spawn", "role":"assistant", "content":[{"type":"tool_use", "id":"tool-later", "name":"Agent", "input":{"description":"later child"}}]}
            }),
        ],
    );
    let child = claude_agent(
        &project_dir,
        session_id,
        "run/agent-later.jsonl",
        &[json!({
            "type":"assistant", "uuid":"record-later", "sessionId":session_id,
            "timestamp":"2026-09-27T10:00:00.100Z", "agentId":"later",
            "message":{"id":"message-later", "role":"assistant", "content":"after cutoff"}
        })],
        Some(json!({"toolUseId":"tool-later", "parentAgentId":null})),
    );
    let current = Intake::Current {
        source_root: projects_root,
        session_id: Some(session_id.to_owned()),
        claude_hook: Some(ClaudeHookContext {
            transcript_path: main.clone(),
            cwd: None,
            agent_id: None,
            agent_transcript_path: None,
        }),
    };
    let initial = inspect(&InspectRequest {
        harness: Some(DiagnosticHarness::Claude),
        intake: current.clone(),
        offset: 0,
        limit: 100,
        snapshot_out: None,
        cutoff_anchor: None,
    })
    .unwrap();
    let cutoff_record = initial
        .records
        .iter()
        .find(|record| record.role.as_deref() == Some("user"))
        .unwrap();
    let cutoff_file = root.path().join("cutoff.json");
    fs::write(
        &cutoff_file,
        serde_json::to_vec(&json!({
            "source_path": main,
            "record_anchor": cutoff_record.anchor,
        }))
        .unwrap(),
    )
    .unwrap();
    let frozen = inspect(&InspectRequest {
        harness: Some(DiagnosticHarness::Claude),
        intake: current,
        offset: 0,
        limit: 100,
        snapshot_out: None,
        cutoff_anchor: Some(cutoff_file),
    })
    .unwrap();
    assert!(frozen.coverage.cutoff_verified);
    assert!(frozen.coverage.analysis_ready);
    assert!(
        !frozen
            .sources
            .iter()
            .any(|source| source.canonical_path == child.canonicalize().unwrap().to_string_lossy())
    );
    assert!(
        frozen
            .records
            .iter()
            .all(|record| record.timestamp.as_deref() != Some("2026-09-27T10:00:00.100Z"))
    );
}

#[test]
fn codex_family_overlap_includes_a_current_linked_child() {
    let root = TempDir::new().unwrap();
    let home = root.path().join("codex-home");
    rollout(&home, THREAD, None, &[]);
    rollout(&home, "thread-current-child", Some(THREAD), &[]);
    let output = command()
        .args([
            "diagnose",
            "inspect",
            "--harness",
            "codex",
            "--session",
            THREAD,
            "--json",
        ])
        .env("CODEX_HOME", &home)
        .env("CODEX_THREAD_ID", "thread-current-child")
        .output()
        .unwrap();
    let value = success_json(&output);
    assert_eq!(value["data"]["overlap"], "current");
    assert_eq!(value["data"]["coverage"]["analysis_ready"], false);
}

const OPENCODE_FAILED_TOOL: &str = r#"{"cwd":"/tool/actual","agent":"build","model":{"id":"synthetic-model","providerID":"synthetic-provider","variant":"default"},"content":[{"type":"tool","id":"TOOLID","name":"bash","state":{"status":"error","input":{"command":"false"},"error":{"type":"tool.execution","message":"Synthetic exit 1"}},"time":{"created":1700000000010,"ran":1700000000020,"completed":1700000000030}}],"time":{"created":1700000000010,"completed":1700000000040},"tokens":{"input":10,"output":3,"reasoning":2,"cache":{"read":7,"write":4}}}"#;

const OPENCODE_SCHEMA: &str = r#"
    CREATE TABLE project(id TEXT PRIMARY KEY);
    CREATE TABLE session_v2 (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, workspace_id TEXT,
      parent_id TEXT, fork_session_id TEXT, fork_boundary TEXT,
      slug TEXT NOT NULL, directory TEXT NOT NULL, path TEXT, title TEXT,
      version TEXT NOT NULL, share_url TEXT, summary_additions INTEGER,
      summary_deletions INTEGER, summary_files INTEGER, summary_diffs TEXT,
      metadata TEXT, cost REAL DEFAULT 0 NOT NULL,
      tokens_input INTEGER DEFAULT 0 NOT NULL, tokens_output INTEGER DEFAULT 0 NOT NULL,
      tokens_reasoning INTEGER DEFAULT 0 NOT NULL, tokens_cache_read INTEGER DEFAULT 0 NOT NULL,
      tokens_cache_write INTEGER DEFAULT 0 NOT NULL, revert TEXT, permission TEXT,
      agent TEXT, model TEXT, time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL,
      time_idle INTEGER, time_viewed INTEGER, idle_outcome TEXT, time_compacting INTEGER,
      time_archived INTEGER, time_suspended INTEGER,
      resume_attempts INTEGER DEFAULT 0 NOT NULL,
      FOREIGN KEY(project_id) REFERENCES project(id) ON DELETE CASCADE
    );
    CREATE TABLE session_message (
      id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES session_v2(id) ON DELETE CASCADE,
      type TEXT NOT NULL, seq INTEGER NOT NULL, time_created INTEGER NOT NULL,
      time_updated INTEGER NOT NULL, data TEXT NOT NULL
    );
    CREATE UNIQUE INDEX session_message_session_seq_idx ON session_message(session_id,seq);
    CREATE INDEX session_message_session_type_seq_idx ON session_message(session_id,type,seq);
"#;

fn capture_flag_run(store_path: &Path, args: &[&str]) -> std::process::Output {
    command()
        .args(["diagnose", "capture", "--json"])
        .args(args)
        .env("VARDE_LEARN_STORE", store_path)
        .output()
        .unwrap()
}

fn capture_flag_new_item(snapshot: &Path, record_index: &str, evidence: &str) -> Vec<String> {
    [
        "--snapshot",
        snapshot.to_str().unwrap(),
        "--source-id",
        "SOURCE",
        "--record-index",
        record_index,
        "--kind",
        "failed-tool",
        "--evidence",
        evidence,
        "--item-source",
        "varde-learn diagnosis",
        "--item-title",
        "Synthetic failed tool",
        "--item-target",
        "clis/learn",
    ]
    .map(String::from)
    .to_vec()
}

fn capture_flag_with_source(
    store_path: &Path,
    args: Vec<String>,
    source_id: &str,
    extra: &[&str],
) -> std::process::Output {
    let mut args: Vec<&str> = args
        .iter()
        .map(|arg| {
            if arg == "SOURCE" {
                source_id
            } else {
                arg.as_str()
            }
        })
        .collect();
    args.extend_from_slice(extra);
    capture_flag_run(store_path, &args)
}

fn capture_flag_codex_bundle(root: &Path, thread_id: &str) -> (Value, PathBuf, Value) {
    let home = root.join("codex-home");
    codex_capture_rollout(&home, thread_id, "/historic/turn-cwd", "permission denied");
    let snapshot_path = root.join(format!("{thread_id}.json"));
    let inspection = inspect_codex_snapshot(&home, thread_id, &snapshot_path);
    let anchor = inspection["data"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == "native-failure-1")
        .unwrap()["anchor"]
        .clone();
    (inspection, snapshot_path, anchor)
}

#[test]
fn capture_flag_jsonl_new_item_matches_the_file_form() {
    let root = TempDir::new().unwrap();
    let (inspection, snapshot_path, anchor) = capture_flag_codex_bundle(root.path(), THREAD);
    let store_path = root.path().join("learn-store");
    let source_id = anchor["source_id"].as_str().unwrap();
    let record_index = anchor["record_index"].to_string();
    let args = capture_flag_new_item(&snapshot_path, &record_index, "Observed a failed tool.");

    let created = success_json(&capture_flag_with_source(
        &store_path,
        args.clone(),
        source_id,
        &[],
    ));
    assert_eq!(created["data"]["disposition"], "created");
    let repeated = success_json(&capture_flag_with_source(&store_path, args, source_id, &[]));
    assert_eq!(repeated["data"]["disposition"], "already-recorded");
    assert_eq!(
        repeated["data"]["occurrence_id"],
        created["data"]["occurrence_id"]
    );

    let request = capture_request(
        &snapshot_path,
        &inspection,
        "Synthetic failed tool",
        "Observed a failed tool.",
    );
    let request_path = root.path().join("incident.json");
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let from_file = success_json(&run_capture(&request_path, &store_path));
    assert_eq!(from_file["data"]["disposition"], "already-recorded");
    assert_eq!(
        from_file["data"]["occurrence_id"],
        created["data"]["occurrence_id"]
    );
}

#[test]
fn capture_flag_existing_item_receives_a_second_occurrence() {
    let root = TempDir::new().unwrap();
    let store_path = root.path().join("learn-store");
    let (_, first_snapshot, first_anchor) = capture_flag_codex_bundle(root.path(), THREAD);
    let first_index = first_anchor["record_index"].to_string();
    let first = success_json(&capture_flag_with_source(
        &store_path,
        capture_flag_new_item(&first_snapshot, &first_index, "First failure."),
        first_anchor["source_id"].as_str().unwrap(),
        &[],
    ));
    let (_, second_snapshot, second_anchor) =
        capture_flag_codex_bundle(root.path(), "thread-codex-fixture-2");
    let item_id = first["data"]["item_id"].to_string();
    let second = success_json(&capture_flag_run(
        &store_path,
        &[
            "--snapshot",
            second_snapshot.to_str().unwrap(),
            "--source-id",
            second_anchor["source_id"].as_str().unwrap(),
            "--record-index",
            &second_anchor["record_index"].to_string(),
            "--kind",
            "failed-tool",
            "--evidence",
            "Second failure.",
            "--item-id",
            &item_id,
        ],
    ));
    assert_eq!(second["data"]["disposition"], "created");
    assert_eq!(second["data"]["item_id"], first["data"]["item_id"]);
    assert_ne!(
        second["data"]["occurrence_id"],
        first["data"]["occurrence_id"]
    );
}

#[test]
fn capture_flag_unknown_record_is_not_found() {
    let root = TempDir::new().unwrap();
    let (_, snapshot_path, anchor) = capture_flag_codex_bundle(root.path(), THREAD);
    let store_path = root.path().join("learn-store");
    let output = capture_flag_with_source(
        &store_path,
        capture_flag_new_item(&snapshot_path, "999", "Observed."),
        anchor["source_id"].as_str().unwrap(),
        &[],
    );
    error_json(&output, 2, "diagnose_record_not_found");
    assert!(!store_path.exists());
}

#[test]
fn capture_flag_rejects_an_unknown_kind_and_incomplete_item() {
    let root = TempDir::new().unwrap();
    let (_, snapshot_path, anchor) = capture_flag_codex_bundle(root.path(), THREAD);
    let store_path = root.path().join("learn-store");
    let source_id = anchor["source_id"].as_str().unwrap();
    let index = anchor["record_index"].to_string();
    let base = [
        "--snapshot",
        snapshot_path.to_str().unwrap(),
        "--source-id",
        source_id,
        "--record-index",
        &index,
        "--evidence",
        "Observed.",
    ];
    let mut unknown_kind = base.to_vec();
    unknown_kind.extend(["--kind", "bogus", "--item-id", "1"]);
    error_json(
        &capture_flag_run(&store_path, &unknown_kind),
        2,
        "diagnose_capture_invalid",
    );
    let mut no_item = base.to_vec();
    no_item.extend(["--kind", "failed-tool"]);
    error_json(
        &capture_flag_run(&store_path, &no_item),
        2,
        "diagnose_capture_invalid",
    );
    assert!(!store_path.exists());
}

#[test]
fn capture_flag_rejects_file_combined_with_flag_form_args() {
    let root = TempDir::new().unwrap();
    let request_path = root.path().join("incident.json");
    fs::write(&request_path, "{}").unwrap();
    command()
        .args(["diagnose", "capture", "--json"])
        .args(["--file", request_path.to_str().unwrap()])
        .args(["--source-id", "source"])
        .assert()
        .failure()
        .code(2)
        .stderr(predicates::str::contains("cannot be used with"));
}

#[test]
fn capture_flag_requires_exactly_one_input_form() {
    command()
        .args(["diagnose", "capture", "--json"])
        .assert()
        .failure()
        .code(2)
        .stderr(predicates::str::contains("--file"));
}

#[test]
fn capture_flag_snapshot_requires_the_record_selectors() {
    command()
        .args(["diagnose", "capture", "--json", "--snapshot", "bundle.json"])
        .assert()
        .failure()
        .code(2)
        .stderr(predicates::str::contains("--source-id"));
}

fn capture_flag_opencode_family(root: &Path) -> (PathBuf, PathBuf) {
    let db_path = root.join("opencode.db");
    let tool = |id: &str| OPENCODE_FAILED_TOOL.replace("TOOLID", id);
    let (parent_tool, child_tool) = (tool("tool_parent"), tool("tool_child"));
    let sql = format!(
        "{OPENCODE_SCHEMA}
INSERT INTO project(id) VALUES ('project_fixture');
INSERT INTO session_v2(id,project_id,slug,directory,version,time_created,time_updated)
VALUES ('ses_parent','project_fixture','parent-slug','/fixture/B','2.0.12',1700000000000,1700000000100);
INSERT INTO session_v2(id,project_id,parent_id,slug,directory,version,time_created,time_updated)
VALUES ('ses_child','project_fixture','ses_parent','child-slug','/fixture/B','2.0.12',1700000000001,1700000000100);
INSERT INTO session_message(id,session_id,type,seq,time_created,time_updated,data) VALUES
 ('msg_parent_user','ses_parent','user',1,1700000000000,1700000000000,'{{\"text\":\"Question\",\"time\":{{\"created\":1700000000000}}}}'),
 ('msg_parent_tool','ses_parent','assistant',2,1700000000010,1700000000040,'{parent_tool}'),
 ('msg_child_user','ses_child','user',1,1700000000001,1700000000001,'{{\"text\":\"Child question\",\"time\":{{\"created\":1700000000001}}}}'),
 ('msg_child_tool','ses_child','assistant',2,1700000000011,1700000000041,'{child_tool}');
"
    );
    rusqlite::Connection::open(&db_path)
        .expect("open the OpenCode fixture database")
        .execute_batch(&sql)
        .expect("build the OpenCode fixture");
    let inspect_family = |snapshot_path: &Path, cutoff: Option<&Path>| {
        let mut command = command();
        command
            .args(["diagnose", "inspect", "--harness", "opencode"])
            .args(["--session", "ses_parent", "--json"])
            .args(["--snapshot-out", snapshot_path.to_str().unwrap()]);
        if let Some(cutoff) = cutoff {
            command.args(["--cutoff-anchor", cutoff.to_str().unwrap()]);
        }
        success_json(&command.env("OPENCODE_DB", &db_path).output().unwrap())
    };
    let uncut_path = root.join("opencode-uncut.json");
    inspect_family(&uncut_path, None);
    let cutoff_path = root.join("opencode-cutoff.json");
    fs::write(
        &cutoff_path,
        serde_json::to_vec(&json!({
            "source_path": db_path.canonicalize().unwrap(),
            "record_anchor": capture_flag_opencode_record(&uncut_path, "msg_child_tool")
        }))
        .unwrap(),
    )
    .unwrap();
    let snapshot_path = root.join("opencode-family.json");
    let inspection = inspect_family(&snapshot_path, Some(&cutoff_path));
    assert_eq!(inspection["data"]["coverage"]["cutoff_verified"], true);
    (snapshot_path, db_path)
}

fn capture_flag_opencode_record(snapshot_path: &Path, native_id: &str) -> Value {
    let frozen: Value = serde_json::from_slice(&fs::read(snapshot_path).unwrap()).unwrap();
    frozen["records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|record| record["anchor"]["native_id"] == native_id)
        .unwrap()["anchor"]
        .clone()
}

#[test]
fn capture_flag_opencode_family_index_alone_is_ambiguous() {
    let root = TempDir::new().unwrap();
    let (snapshot_path, db_path) = capture_flag_opencode_family(root.path());
    let store_path = root.path().join("learn-store");
    let parent = capture_flag_opencode_record(&snapshot_path, "msg_parent_tool");
    let child = capture_flag_opencode_record(&snapshot_path, "msg_child_tool");
    assert_eq!(parent["source_id"], child["source_id"]);
    assert_eq!(parent["record_index"], child["record_index"]);
    let source_id = parent["source_id"].as_str().unwrap();
    let args = capture_flag_new_item(
        &snapshot_path,
        &parent["record_index"].to_string(),
        "Observed.",
    );

    let ambiguous = command()
        .args(["diagnose", "capture", "--json"])
        .args(
            args.iter()
                .map(|arg| if arg == "SOURCE" { source_id } else { arg }),
        )
        .env("VARDE_LEARN_STORE", &store_path)
        .env("OPENCODE_DB", &db_path)
        .output()
        .unwrap();
    let value = error_json(&ambiguous, 2, "diagnose_record_ambiguous");
    assert!(
        value["data"]["error"]["message"]
            .as_str()
            .unwrap()
            .contains("--native-id")
    );

    let capture_with_native_id = |native_id: &str| {
        command()
            .args(["diagnose", "capture", "--json", "--native-id", native_id])
            .args(
                args.iter()
                    .map(|arg| if arg == "SOURCE" { source_id } else { arg }),
            )
            .env("VARDE_LEARN_STORE", &store_path)
            .env("OPENCODE_DB", &db_path)
            .output()
            .unwrap()
    };
    let created = success_json(&capture_with_native_id("msg_child_tool"));
    assert_eq!(created["data"]["disposition"], "created");
    // The parent record is selected too, but lies outside the child-session cutoff.
    error_json(
        &capture_with_native_id("msg_parent_tool"),
        2,
        "diagnose_capture_uncertain",
    );
}

#[test]
fn capture_flag_opencode_sqlite_anchor_is_copied_whole() {
    let root = TempDir::new().unwrap();
    let (snapshot_path, db_path) = capture_flag_opencode_family(root.path());
    let store_path = root.path().join("learn-store");
    let anchor = capture_flag_opencode_record(&snapshot_path, "msg_child_tool");
    for key in ["session_id", "storage_sequence", "context_digest"] {
        assert!(!anchor[key].is_null(), "bundle anchor lacks {key}");
    }
    let source_id = anchor["source_id"].as_str().unwrap();
    let args = capture_flag_new_item(
        &snapshot_path,
        &anchor["record_index"].to_string(),
        "Observed.",
    );
    let flag_output = command()
        .args([
            "diagnose",
            "capture",
            "--json",
            "--native-id",
            "msg_child_tool",
        ])
        .args(
            args.iter()
                .map(|arg| if arg == "SOURCE" { source_id } else { arg }),
        )
        .env("VARDE_LEARN_STORE", &store_path)
        .env("OPENCODE_DB", &db_path)
        .output()
        .unwrap();
    let created = success_json(&flag_output);
    assert_eq!(created["data"]["disposition"], "created");

    let frozen: Value = serde_json::from_slice(&fs::read(&snapshot_path).unwrap()).unwrap();
    let request_path = root.path().join("opencode-incident.json");
    let request = json!({
        "snapshot_path": snapshot_path.to_string_lossy(),
        "snapshot_digest": frozen["digest"],
        "session_id": frozen["session"]["thread_id"],
        "anchor": anchor,
        "incident_kind": "failed-tool",
        "item": {"mode":"new", "source":"varde-learn diagnosis", "title":"Synthetic failed tool", "target":"clis/learn"},
        "evidence": "Observed."
    });
    fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let from_file = command()
        .args([
            "diagnose",
            "capture",
            "--json",
            "--file",
            request_path.to_str().unwrap(),
        ])
        .env("VARDE_LEARN_STORE", &store_path)
        .env("OPENCODE_DB", &db_path)
        .output()
        .unwrap();
    let from_file = success_json(&from_file);
    assert_eq!(from_file["data"]["disposition"], "already-recorded");
    assert_eq!(
        from_file["data"]["occurrence_id"],
        created["data"]["occurrence_id"]
    );
}
