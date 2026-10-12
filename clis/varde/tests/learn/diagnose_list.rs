use assert_cmd::Command;
use rusqlite::Connection;
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use tempfile::TempDir;

struct Fixture {
    _temp: TempDir,
    repo: PathBuf,
    codex_home: PathBuf,
    claude_config: PathBuf,
    opencode_db: PathBuf,
    paseo_home: PathBuf,
}

fn fixture() -> Fixture {
    let temp = TempDir::new().unwrap();
    let repo = temp.path().join("repo");
    let codex_home = temp.path().join("codex");
    let claude_config = temp.path().join("claude");
    let opencode_db = temp.path().join("opencode.db");
    let paseo_home = temp.path().join("paseo");
    fs::create_dir_all(&repo).unwrap();

    let date = "2026-10-06T10:00:00Z";
    let cwd = repo.to_str().unwrap();
    codex_session(
        &codex_home,
        "thread-root",
        Some(None),
        cwd,
        date,
        "root prompt",
    );
    codex_session(
        &codex_home,
        "thread-native",
        Some(Some("thread-root")),
        cwd,
        "2026-10-06T10:01:00Z",
        "native worker prompt",
    );
    codex_session(
        &codex_home,
        "thread-paseo-root",
        Some(None),
        cwd,
        "2026-10-06T09:00:00Z",
        "Paseo parent prompt",
    );
    codex_session(
        &codex_home,
        "thread-paseo-worker",
        Some(Some("thread-root")),
        cwd,
        "2026-10-06T09:01:00Z",
        "Paseo worker prompt",
    );
    codex_session(
        &codex_home,
        "thread-unlinked",
        None,
        cwd,
        "2026-10-06T08:00:00Z",
        "unlinked prompt",
    );
    let outside = temp.path().join("outside-repo");
    fs::create_dir_all(&outside).unwrap();
    codex_session(
        &codex_home,
        "thread-outside-repo",
        Some(None),
        outside.to_str().unwrap(),
        "2026-10-06T11:00:00Z",
        "outside prompt",
    );
    codex_session(
        &codex_home,
        "thread-analyst",
        Some(None),
        cwd,
        "2026-10-06T07:00:00Z",
        "varde-retro-analyst\nprivate analyst instructions",
    );
    for (id, directory) in [
        (
            "thread-output-sandbox",
            repo.join("varde-learn-output-sbox-fixture"),
        ),
        (
            "thread-trigger-sandbox",
            repo.join("varde-learn-trigger-sbox-fixture"),
        ),
    ] {
        fs::create_dir_all(&directory).unwrap();
        codex_session(
            &codex_home,
            id,
            Some(None),
            directory.to_str().unwrap(),
            date,
            "sandbox prompt",
        );
    }

    paseo_agent(&paseo_home, "agent-parent", "thread-paseo-root", None);
    paseo_agent(
        &paseo_home,
        "agent-worker",
        "thread-paseo-worker",
        Some("agent-parent"),
    );

    let projects = claude_config.join("projects/project-fixture");
    let claude_id = "00000000-0000-4000-8000-000000000001";
    claude_transcript(
        &projects.join(format!("{claude_id}.jsonl")),
        json!({
            "type":"user", "uuid":"claude-root-user", "parentUuid":null,
            "sessionId":claude_id, "timestamp":date, "cwd":cwd,
            "message":{"role":"user", "content":[{"type":"text", "text":"Claude root prompt"}]}
        }),
    );
    let claude_analyst_id = "00000000-0000-4000-8000-000000000002";
    claude_transcript(
        &projects.join(format!("{claude_analyst_id}.jsonl")),
        json!({
            "type":"user", "uuid":"claude-analyst-user", "parentUuid":null,
            "sessionId":claude_analyst_id, "timestamp":date, "cwd":cwd,
            "message":{"role":"user", "content":[{"type":"text", "text":"varde-retro-analyst\nprivate marker"}]}
        }),
    );
    let claude_child = projects
        .join(claude_id)
        .join("subagents/agent-claude-worker.jsonl");
    claude_transcript(
        &claude_child,
        json!({
            "type":"user", "uuid":"claude-child-user", "parentUuid":null,
            "sessionId":claude_id, "agentId":"claude-worker", "isSidechain":true,
            "timestamp":date, "cwd":cwd,
            "message":{"role":"user", "content":[{"type":"text", "text":"Claude worker prompt"}]}
        }),
    );
    fs::write(
        claude_child.with_extension("meta.json"),
        json!({"toolUseId":"claude-tool-use", "parentAgentId":null}).to_string(),
    )
    .unwrap();

    opencode_fixture(&opencode_db, cwd);
    Fixture {
        _temp: temp,
        repo,
        codex_home,
        claude_config,
        opencode_db,
        paseo_home,
    }
}

fn codex_session(
    home: &Path,
    id: &str,
    parent: Option<Option<&str>>,
    cwd: &str,
    timestamp: &str,
    prompt: &str,
) {
    let path = home
        .join("sessions/2026/10/06")
        .join(format!("rollout-{timestamp}-{id}.jsonl"));
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    let mut payload = json!({
        "id":id, "session_id":id, "timestamp":timestamp, "cwd":cwd,
        "originator":"codex", "cli_version":"0.160.0"
    });
    if let Some(parent) = parent {
        payload["parent_thread_id"] = parent.map_or(Value::Null, |value| json!(value));
    }
    let records = [
        json!({"timestamp":timestamp, "type":"session_meta", "payload":payload}),
        json!({"type":"response_item", "payload":{"type":"message", "role":"user", "content":[{"type":"input_text", "text":prompt}]}}),
    ];
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

fn paseo_agent(home: &Path, id: &str, session_id: &str, parent: Option<&str>) {
    let path = home.join("agents/codex").join(format!("{id}.json"));
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    let mut value = json!({
        "provider":"codex",
        "persistence":{"sessionId":session_id},
        "labels":{}
    });
    if let Some(parent) = parent {
        value["labels"]["paseo.parent-agent-id"] = json!(parent);
    }
    fs::write(path, value.to_string()).unwrap();
}

fn claude_transcript(path: &Path, first_user: Value) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, first_user.to_string() + "\n").unwrap();
}

fn opencode_fixture(path: &Path, cwd: &str) {
    let db = Connection::open(path).unwrap();
    db.execute_batch(
        "CREATE TABLE session_v2 (
            id TEXT, project_id TEXT, workspace_id TEXT, parent_id TEXT,
            fork_session_id TEXT, fork_boundary TEXT, slug TEXT, directory TEXT,
            path TEXT, title TEXT, version TEXT, share_url TEXT,
            summary_additions INTEGER, summary_deletions INTEGER, summary_files TEXT,
            summary_diffs TEXT, metadata TEXT, cost REAL, tokens_input INTEGER,
            tokens_output INTEGER, tokens_reasoning INTEGER, tokens_cache_read INTEGER,
            tokens_cache_write INTEGER, revert TEXT, permission TEXT, agent TEXT,
            model TEXT, time_created INTEGER, time_updated INTEGER, time_idle INTEGER,
            time_viewed INTEGER, idle_outcome TEXT, time_compacting INTEGER,
            time_archived INTEGER, time_suspended INTEGER, resume_attempts INTEGER
        );
        CREATE TABLE session_message (
            id TEXT, session_id TEXT, type TEXT, seq INTEGER,
            time_created INTEGER, time_updated INTEGER, data TEXT
        );",
    )
    .unwrap();
    for (id, parent, created, text) in [
        (
            "ses-parent",
            None,
            1_791_280_800_000_i64,
            "OpenCode root prompt",
        ),
        (
            "ses-child",
            Some("ses-parent"),
            1_791_280_860_000_i64,
            "OpenCode worker prompt",
        ),
        (
            "ses-analyst",
            None,
            1_791_280_900_000_i64,
            "varde-retro-analyst\nprivate marker",
        ),
    ] {
        db.execute(
            "INSERT INTO session_v2(id,project_id,parent_id,directory,version,time_created) VALUES (?1,'project-fixture',?2,?3,'2.0.12',?4)",
            rusqlite::params![id, parent, cwd, created],
        )
        .unwrap();
        db.execute(
            "INSERT INTO session_message(id,session_id,type,seq,time_created,time_updated,data) VALUES (?1,?2,'user',1,?3,?3,?4)",
            rusqlite::params![format!("{id}-user"), id, created, json!({"text":text,"time":{"created":created}}).to_string()],
        )
        .unwrap();
    }
}

fn command_for(fixture: &Fixture, harness: &str) -> Command {
    list_command(fixture, harness, "--repository")
}

fn list_command(fixture: &Fixture, harness: &str, repository_flag: &str) -> Command {
    let mut command = Command::cargo_bin("varde").expect("varde binary");
    command
        .args([
            "learn",
            "diagnose",
            "list",
            "--harness",
            harness,
            repository_flag,
        ])
        .arg(&fixture.repo)
        .arg("--json")
        .env("HOME", fixture._temp.path())
        .env("CODEX_HOME", &fixture.codex_home)
        .env("CLAUDE_CONFIG_DIR", &fixture.claude_config)
        .env("OPENCODE_DB", &fixture.opencode_db)
        .env("PASEO_HOME", &fixture.paseo_home);
    command
}

fn command(fixture: &Fixture) -> Command {
    command_for(fixture, "all")
}

fn assert_coverage_warning(value: &Value, expected: &str) {
    assert_eq!(value["meta"]["truncated"], true, "{value}");
    assert!(
        value["meta"]["warnings"]
            .as_array()
            .is_some_and(|warnings| {
                warnings.iter().any(|warning| {
                    warning
                        .as_str()
                        .is_some_and(|warning| warning.contains(expected))
                })
            }),
        "missing coverage warning containing {expected:?}: {value}"
    );
}

fn success(command: &mut Command) -> Value {
    let output = command.output().expect("run diagnose list");
    assert!(
        output.status.success(),
        "status: {:?}\nstdout: {}\nstderr: {}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("JSON output envelope")
}

#[test]
fn list_groups_workers_and_filters_sandboxes_and_retro_analysts() {
    let fixture = fixture();
    let value = success(&mut command(&fixture));
    assert_eq!(value["ok"], true);
    let sessions = value["data"]["sessions"].as_array().unwrap();
    assert!(
        sessions
            .windows(2)
            .all(|pair| { pair[0]["started_at"].as_str() >= pair[1]["started_at"].as_str() })
    );
    let ordered_ids = sessions
        .iter()
        .map(|session| session["session_id"].as_str().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(
        ordered_ids,
        [
            "00000000-0000-4000-8000-000000000001",
            "ses-parent",
            "thread-root",
            "thread-paseo-root",
            "thread-unlinked",
        ]
    );

    let codex_root = sessions
        .iter()
        .find(|entry| entry["harness"] == "codex" && entry["session_id"] == "thread-root")
        .expect("Codex root");
    assert_eq!(codex_root["root"], true);
    assert!(
        codex_root["workers"]
            .as_array()
            .unwrap()
            .iter()
            .any(|worker| {
                worker["harness"] == "codex" && worker["session_id"] == "thread-native"
            })
    );

    let paseo_root = sessions
        .iter()
        .find(|entry| entry["harness"] == "codex" && entry["session_id"] == "thread-paseo-root")
        .expect("Paseo-linked root");
    assert!(
        paseo_root["workers"]
            .as_array()
            .unwrap()
            .iter()
            .any(|worker| { worker["session_id"] == "thread-paseo-worker" })
    );
    assert!(
        !codex_root["workers"]
            .to_string()
            .contains("thread-paseo-worker")
    );

    let claude_root = sessions
        .iter()
        .find(|entry| entry["harness"] == "claude")
        .expect("Claude root");
    assert_eq!(claude_root["root"], true);
    assert!(
        claude_root["workers"]
            .as_array()
            .unwrap()
            .iter()
            .any(|worker| {
                worker["harness"] == "claude" && worker["session_id"] == "claude-worker"
            })
    );

    let opencode_root = sessions
        .iter()
        .find(|entry| entry["harness"] == "opencode" && entry["session_id"] == "ses-parent")
        .expect("OpenCode root");
    assert!(
        opencode_root["workers"]
            .as_array()
            .unwrap()
            .iter()
            .any(|worker| { worker["session_id"] == "ses-child" })
    );

    let unlinked = sessions
        .iter()
        .find(|entry| entry["session_id"] == "thread-unlinked")
        .expect("unlinked session");
    assert_eq!(unlinked["root"], "unknown");
    let serialized = serde_json::to_string(sessions).unwrap();
    for excluded in [
        "thread-analyst",
        "thread-outside-repo",
        "thread-output-sandbox",
        "thread-trigger-sandbox",
        "00000000-0000-4000-8000-000000000002",
        "ses-analyst",
    ] {
        assert!(
            !serialized.contains(excluded),
            "included excluded session {excluded}"
        );
    }
}

#[test]
fn list_run_resolves_a_worker_to_its_root() {
    let fixture = fixture();
    let mut command = command(&fixture);
    command.args(["--run", "thread-native"]);
    let value = success(&mut command);
    let sessions = value["data"]["sessions"].as_array().unwrap();
    assert_eq!(sessions.len(), 1);
    assert_eq!(sessions[0]["session_id"], "thread-root");
    assert_eq!(sessions[0]["workers"].as_array().unwrap().len(), 1);
}

#[test]
fn list_all_keeps_each_available_harness_in_the_default_limit() {
    let fixture = fixture();
    let projects = fixture.claude_config.join("projects/project-fixture");
    for index in 0..6 {
        let session_id = format!("recent-claude-{index}");
        let timestamp = format!("2026-10-06T12:{index:02}:00Z");
        claude_transcript(
            &projects.join(format!("{session_id}.jsonl")),
            json!({
                "type":"user",
                "uuid":format!("{session_id}-user"),
                "parentUuid":null,
                "sessionId":session_id.clone(),
                "timestamp":timestamp,
                "cwd":fixture.repo.to_str().unwrap(),
                "message":{"role":"user", "content":[{"type":"text", "text":"recent prompt"}]}
            }),
        );
    }

    let value = success(&mut command(&fixture));
    let sessions = value["data"]["sessions"].as_array().unwrap();
    assert_eq!(sessions.len(), 5);
    assert!(sessions.iter().any(|session| session["harness"] == "codex"));
    assert!(
        sessions
            .iter()
            .any(|session| session["harness"] == "claude")
    );
    assert!(
        sessions
            .iter()
            .any(|session| session["harness"] == "opencode")
    );
    assert!(
        sessions
            .windows(2)
            .all(|pair| { pair[0]["started_at"].as_str() >= pair[1]["started_at"].as_str() })
    );
}

#[test]
fn list_works_without_paseo_home() {
    let fixture = fixture();
    let mut command = command(&fixture);
    command.env_remove("PASEO_HOME");
    let value = success(&mut command);
    assert!(
        value["data"]["sessions"]
            .as_array()
            .unwrap()
            .iter()
            .any(|session| session["session_id"] == "thread-root")
    );
}

#[test]
fn list_keeps_sessions_when_a_codex_header_is_malformed() {
    let fixture = fixture();
    let malformed = fixture
        .codex_home
        .join("sessions/2026/10/06/rollout-malformed.jsonl");
    fs::write(malformed, b"{malformed header}\n").unwrap();

    let value = success(&mut command_for(&fixture, "codex"));
    assert_eq!(value["ok"], true);
    assert!(
        value["data"]["sessions"]
            .to_string()
            .contains("thread-root")
    );
    assert_coverage_warning(&value, "rollout");
}

#[test]
fn list_skips_an_oversized_first_user_record_with_a_coverage_warning() {
    let fixture = fixture();
    codex_session(
        &fixture.codex_home,
        "thread-oversized-first-user",
        Some(None),
        fixture.repo.to_str().unwrap(),
        "2026-10-06T12:00:00Z",
        &"x".repeat(256 * 1024),
    );

    let value = success(&mut command_for(&fixture, "codex"));
    let sessions = value["data"]["sessions"].to_string();
    assert!(sessions.contains("thread-root"));
    assert!(!sessions.contains("thread-oversized-first-user"));
    assert_coverage_warning(&value, "first user record");
}

#[test]
fn list_uses_native_parents_when_the_paseo_store_is_unreadable() {
    let fixture = fixture();
    let agents = fixture.paseo_home.join("agents");
    fs::remove_dir_all(&agents).unwrap();
    fs::write(&agents, b"unreadable agent store").unwrap();

    let value = success(&mut command_for(&fixture, "codex"));
    let sessions = value["data"]["sessions"].as_array().unwrap();
    let native_root = sessions
        .iter()
        .find(|session| session["session_id"] == "thread-root")
        .unwrap();
    assert!(
        native_root["workers"]
            .to_string()
            .contains("thread-paseo-worker")
    );
    assert_coverage_warning(&value, "Paseo");
}

#[test]
fn list_errors_when_codex_has_no_readable_source() {
    let fixture = fixture();
    fs::remove_dir_all(fixture.codex_home.join("sessions")).unwrap();

    let output = command_for(&fixture, "codex").output().unwrap();
    assert!(
        !output.status.success(),
        "empty Codex source unexpectedly succeeded: {}",
        String::from_utf8_lossy(&output.stdout)
    );
}

#[test]
fn list_all_keeps_codex_sessions_when_claude_discovery_fails() {
    let fixture = fixture();
    let projects = fixture.claude_config.join("projects");
    fs::remove_dir_all(&projects).unwrap();
    fs::write(projects, b"not a projects directory").unwrap();

    let value = success(&mut command(&fixture));
    assert!(
        value["data"]["sessions"]
            .to_string()
            .contains("thread-root")
    );
    assert_coverage_warning(&value, "Claude");
}

#[test]
fn list_all_keeps_codex_sessions_when_opencode_discovery_fails() {
    let fixture = fixture();
    fs::write(&fixture.opencode_db, b"not an OpenCode database").unwrap();

    let value = success(&mut command(&fixture));
    assert!(
        value["data"]["sessions"]
            .to_string()
            .contains("thread-root")
    );
    assert_coverage_warning(&value, "OpenCode");
}

#[test]
fn list_accepts_the_hidden_repo_alias() {
    let fixture = fixture();
    let canonical = success(&mut command_for(&fixture, "all"));
    let alias = success(&mut list_command(&fixture, "all", "--repo"));
    assert_eq!(canonical["data"], alias["data"]);
}

#[test]
fn list_reports_unreadable_claude_sessions_as_a_coverage_warning() {
    let fixture = fixture();
    let malformed_id = "00000000-0000-4000-8000-000000000099";
    let malformed = fixture
        .claude_config
        .join("projects/project-fixture")
        .join(format!("{malformed_id}.jsonl"));
    fs::write(malformed, b"{malformed header}\n").unwrap();

    let value = success(&mut command_for(&fixture, "claude"));
    assert!(
        value["data"]["sessions"]
            .to_string()
            .contains("00000000-0000-4000-8000-000000000001")
    );
    assert_coverage_warning(&value, "Claude discovery");
}

#[test]
fn list_errors_when_claude_has_no_readable_source() {
    let fixture = fixture();
    fs::remove_dir_all(fixture.claude_config.join("projects")).unwrap();

    let output = command_for(&fixture, "claude").output().unwrap();
    assert!(!output.status.success());
}

#[test]
fn list_errors_when_opencode_has_no_readable_source() {
    let fixture = fixture();
    fs::remove_file(&fixture.opencode_db).unwrap();

    let output = command_for(&fixture, "opencode").output().unwrap();
    assert!(!output.status.success());
}

#[test]
fn list_reports_unreadable_opencode_sessions_as_a_coverage_warning() {
    let fixture = fixture();
    let db = Connection::open(&fixture.opencode_db).unwrap();
    db.execute(
        "UPDATE session_message SET data=?1 WHERE session_id='ses-child'",
        ["{malformed record}"],
    )
    .unwrap();

    let value = success(&mut command_for(&fixture, "opencode"));
    let sessions = value["data"]["sessions"].to_string();
    assert!(sessions.contains("ses-parent"));
    assert!(!sessions.contains("ses-child"));
    assert_coverage_warning(&value, "OpenCode discovery skipped 1");
}
