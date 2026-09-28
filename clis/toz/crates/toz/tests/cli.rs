use assert_cmd::Command;
use predicates::prelude::*;
use std::path::PathBuf;
use tempfile::TempDir;

struct Env {
    _cfg: TempDir,
    cfg_path: PathBuf,
    // Empty by default so `toz` never reads the developer's real `~/.config/varde/paths.toml`;
    // tests that exercise it set their own `VARDE_CONFIG_DIR` after calling `toz(&e)`.
    _varde_cfg: TempDir,
    varde_cfg_path: PathBuf,
    project: TempDir,
}

fn env() -> Env {
    let cfg = TempDir::new().unwrap();
    let cfg_path = cfg.path().to_path_buf();
    let varde_cfg = TempDir::new().unwrap();
    let varde_cfg_path = varde_cfg.path().to_path_buf();
    Env {
        _cfg: cfg,
        cfg_path,
        _varde_cfg: varde_cfg,
        varde_cfg_path,
        project: TempDir::new().unwrap(),
    }
}

fn toz(e: &Env) -> Command {
    let mut c = Command::cargo_bin("varde-toz").unwrap();
    c.env("TOZ_CONFIG_DIR", &e.cfg_path)
        .env("VARDE_CONFIG_DIR", &e.varde_cfg_path)
        .env_remove("TOZ_THRESHOLD")
        .env_remove("TOZ_SESSION")
        .env_remove("TOZ_FALLBACK_DIR")
        .current_dir(e.project.path());
    c
}

fn capture_text(e: &Env, label: &str, body: String) -> String {
    let out = toz(e)
        .args(["capture", "--label", label, "--source", label, "--force"])
        .write_stdin(body)
        .output()
        .unwrap();
    let s = String::from_utf8_lossy(&out.stdout);
    s.split("handle ")
        .nth(1)
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap()
        .to_string()
}

#[test]
fn canonical_environment_and_script_alias_preserve_legacy_access() {
    let e = env();
    let h = capture_text(&e, "legacy", "legacy capture\n".into());
    toz(&e)
        .env("VARDE_TOZ_CONFIG_DIR", &e.cfg_path)
        .env("TOZ_CONFIG_DIR", e.project.path().join("wrong"))
        .args(["query", "--handle", &h])
        .assert()
        .success()
        .stdout(predicate::str::contains("legacy capture"));
    toz(&e)
        .env("VARDE_TOZ_CONFIG_DIR", &e.cfg_path)
        .args(["doctor", "--json"])
        .assert()
        .stdout(predicate::str::contains("source: VARDE_TOZ_CONFIG_DIR"));
    toz(&e)
        .env("VARDE_TOZ_THRESHOLD", "43")
        .env("TOZ_THRESHOLD", "9")
        .args(["doctor", "--json"])
        .assert()
        .stdout(predicate::str::contains("threshold 43 bytes"));
    let (_, output) = script_result(
        &e,
        &[
            "--handle",
            &h,
            "--code",
            "print(vardeToz === toz, vardeToz.handle.lines)",
        ],
        None,
    );
    assert_eq!(output.trim(), "true 1");
}

#[test]
fn legacy_default_config_keeps_settings_and_captures() {
    let e = env();
    let base = TempDir::new().unwrap();
    let legacy = base.path().join("tool-output-zone");
    std::fs::create_dir_all(&legacy).unwrap();
    std::fs::write(legacy.join("config.toml"), "threshold = 7\n").unwrap();
    let output = toz(&e)
        .env("TOZ_CONFIG_DIR", &legacy)
        .args(["capture", "--label", "old", "--force"])
        .write_stdin("legacy stored capture\n")
        .output()
        .unwrap();
    assert!(output.status.success());
    let text = String::from_utf8(output.stdout).unwrap();
    let handle = text
        .split("handle ")
        .nth(1)
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap();
    // A canonical directory created by another operation must not hide old resources.
    std::fs::create_dir_all(base.path().join("varde-toz")).unwrap();
    toz(&e)
        .env_remove("TOZ_CONFIG_DIR")
        .env_remove("VARDE_TOZ_CONFIG_DIR")
        .env("XDG_CONFIG_HOME", base.path())
        .args(["doctor", "--json"])
        .assert()
        .stdout(
            predicate::str::contains("tool-output-zone")
                .and(predicate::str::contains("threshold 7 bytes")),
        );
    toz(&e)
        .env_remove("TOZ_CONFIG_DIR")
        .env_remove("VARDE_TOZ_CONFIG_DIR")
        .env("XDG_CONFIG_HOME", base.path())
        .args(["query", "--handle", handle])
        .assert()
        .success()
        .stdout("legacy stored capture\n");
    toz(&e)
        .env("VARDE_TOZ_CONFIG_DIR", base.path().join("varde-toz"))
        .env("XDG_CONFIG_HOME", base.path())
        .args(["query", "--handle", handle])
        .assert()
        .failure();
}

#[cfg(unix)]
#[test]
fn legacy_root_alias_reports_canonical_and_preserves_access() {
    let e = env();
    let base = TempDir::new().unwrap();
    let canonical = base.path().join("varde-toz");
    std::fs::create_dir_all(&canonical).unwrap();
    std::os::unix::fs::symlink(&canonical, base.path().join("tool-output-zone")).unwrap();
    let handle = capture_text(&e, "old alias", "alias capture\n".into());
    // Move a real existing store to the canonical root; the old name remains an alias.
    for entry in std::fs::read_dir(&e.cfg_path).unwrap() {
        let entry = entry.unwrap();
        std::fs::rename(entry.path(), canonical.join(entry.file_name())).unwrap();
    }
    toz(&e)
        .env_remove("TOZ_CONFIG_DIR")
        .env_remove("VARDE_TOZ_CONFIG_DIR")
        .env("XDG_CONFIG_HOME", base.path())
        .args(["doctor", "--json"])
        .assert()
        .stdout(predicate::str::contains(format!(
            "config dir {}",
            canonical.display()
        )));
    toz(&e)
        .env("TOZ_CONFIG_DIR", base.path().join("tool-output-zone"))
        .args(["query", "--handle", &handle])
        .assert()
        .success()
        .stdout("alias capture\n");
}

fn capture_lines(e: &Env, label: &str, n: usize) -> String {
    let body: String = (1..=n)
        .map(|i| {
            if i % 7 == 0 {
                format!("ERROR code=500 req={i}\n")
            } else {
                format!("ok req={i}\n")
            }
        })
        .collect();
    capture_text(e, label, body)
}

fn script_result(e: &Env, args: &[&str], stdin: Option<&str>) -> (String, String) {
    let mut command = toz(e);
    command.args(["--json", "run"]).args(args);
    if let Some(source) = stdin {
        command.write_stdin(source);
    }
    let output = command.output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let handle = value["handle"].as_str().unwrap().to_string();
    let output = toz(e)
        .args(["query", "--handle", &handle])
        .output()
        .unwrap();
    assert!(output.status.success());
    (handle, String::from_utf8(output.stdout).unwrap())
}

#[test]
fn query_search_retrieve_and_list() {
    let e = env();
    let body: String = (1..=200).map(|i| format!("line {i}\n")).collect();
    let handle = capture_text(&e, "lines", body);

    toz(&e)
        .args(["query", "--handle", &handle, "--lines", "199:200"])
        .assert()
        .success()
        .stdout("line 199\nline 200\n");
    toz(&e)
        .args(["query", "--handle", &handle, "--chunk", "1"])
        .assert()
        .success()
        .stdout(predicate::str::contains("line 71\n"));
    toz(&e)
        .args(["--json", "query", "--list"])
        .assert()
        .success()
        .stdout(predicate::str::contains(handle.clone()));
    toz(&e)
        .args(["--json", "query", "line 199", "--handle", &handle])
        .assert()
        .success()
        .stdout(predicate::str::contains("line 199"));
    toz(&e)
        .args(["query", "--list", "line"])
        .assert()
        .failure()
        .stderr(predicate::str::contains("--list cannot be combined"));
}

#[test]
fn deferred_capture_reads_immediately_and_searches_after_indexing() {
    let e = env();
    let body = "alpha first\nunique-deferred-token second\nomega last\n";
    let output = toz(&e)
        .args(["capture", "--force", "--defer-index", "--label", "deferred"])
        .write_stdin(body)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let preview = String::from_utf8(output.stdout).unwrap();
    let handle = preview
        .split("handle ")
        .nth(1)
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap();
    toz(&e)
        .args(["query", "--handle", handle, "--lines", "2:2"])
        .assert()
        .success()
        .stdout("unique-deferred-token second\n");
    toz(&e)
        .args([
            "--json",
            "query",
            "--handle",
            handle,
            "unique-deferred-token",
        ])
        .assert()
        .success()
        .stdout(predicate::str::contains("unique-deferred-token second"));
}

#[test]
fn capture_from_stdin() {
    let e = env();
    let body: String = (1..=300).map(|i| format!("row {i}\n")).collect();
    toz(&e)
        .args(["capture", "--threshold", "100", "--label", "rows"])
        .write_stdin(body.clone())
        .assert()
        .success()
        .stdout(predicate::str::contains("label: \"rows\""));
    // under threshold: echoed verbatim
    toz(&e)
        .args(["capture", "--threshold", "10000"])
        .write_stdin(body.clone())
        .assert()
        .success()
        .stdout(body);
}

#[test]
fn doctor_reports_recent_hook_failures_without_payloads() {
    let e = env();
    toz(&e)
        .args([
            "event",
            "--harness",
            "pi",
            "--outcome",
            "failed",
            "--reason",
            "timeout",
            "--tool",
            "bash",
            "--bytes",
            "8192",
        ])
        .assert()
        .success();
    toz(&e)
        .args(["capture", "--hook"])
        .write_stdin("not json")
        .assert()
        .success();

    let output = toz(&e).args(["--json", "doctor"]).output().unwrap();
    assert_eq!(output.status.code(), Some(1));
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let summary = &report["hook_outcomes_7d"];
    assert_eq!(summary["failed"], 2);
    assert_eq!(summary["failures_by_reason"]["timeout"], 1);
    assert_eq!(summary["failures_by_reason"]["invalid-payload"], 1);
    assert!(!String::from_utf8_lossy(&output.stdout).contains("not json"));

    let note = toz(&e)
        .args(["note", "--harness", "codex"])
        .output()
        .unwrap();
    assert!(note.status.success());
    let notice: serde_json::Value = serde_json::from_slice(&note.stdout).unwrap();
    assert!(notice["hookSpecificOutput"]["additionalContext"]
        .as_str()
        .unwrap()
        .contains("2 hook failure(s)"));
}

#[test]
fn doctor_flags_unreadable_diagnostic_records() {
    let e = env();
    std::fs::write(e.cfg_path.join("diagnostics.jsonl"), "broken record\n").unwrap();
    let output = toz(&e).args(["--json", "doctor"]).output().unwrap();
    assert_eq!(output.status.code(), Some(1));
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["hook_outcomes_7d"]["unreadable_lines"], 1);
}

#[test]
fn hook_event_uses_fallback_when_default_diagnostics_are_unwritable() {
    let home = TempDir::new().unwrap();
    let fallback = TempDir::new().unwrap();
    std::fs::create_dir(home.path().join(".config")).unwrap();
    std::fs::write(
        home.path().join(".config/tool-output-zone"),
        "not a directory",
    )
    .unwrap();

    let mut event = Command::cargo_bin("varde-toz").unwrap();
    event
        .env("HOME", home.path())
        .env_remove("TOZ_CONFIG_DIR")
        .env("TOZ_FALLBACK_DIR", fallback.path())
        .args([
            "event",
            "--harness",
            "pi",
            "--outcome",
            "failed",
            "--reason",
            "timeout",
        ])
        .assert()
        .success();
    assert!(fallback.path().join("diagnostics.jsonl").is_file());

    let mut note = Command::cargo_bin("varde-toz").unwrap();
    note.env("HOME", home.path())
        .env_remove("TOZ_CONFIG_DIR")
        .env("TOZ_FALLBACK_DIR", fallback.path())
        .args(["note", "--harness", "codex"])
        .assert()
        .success()
        .stdout(predicate::str::contains("1 hook failure(s)"));
}

#[test]
fn hook_mode_content_blocks_and_unknown_shapes() {
    let e = env();
    let big: String = (1..=2000).map(|i| format!("l{i} ")).collect();
    let mcp = serde_json::json!({
        "tool_name": "ExampleTool",
        "tool_input": {},
        "tool_response": [{"type": "text", "text": big}]
    });
    let out = toz(&e)
        .args(["capture", "--hook"])
        .write_stdin(mcp.to_string())
        .output()
        .unwrap();
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    let upd = &v["hookSpecificOutput"]["updatedMCPToolOutput"];
    assert_eq!(upd[0]["type"], "text");
    assert!(upd[0]["text"]
        .as_str()
        .unwrap()
        .contains("varde-toz: captured"));

    // unknown object shape → dominant text field replaced in place (depth ≤ 2)
    let weird = serde_json::json!({
        "tool_name": "Mystery", "tool_input": {}, "tool_response": {"nested": {"deep": big, "n": 1}}
    });
    let out = toz(&e)
        .args(["capture", "--hook"])
        .write_stdin(weird.to_string())
        .output()
        .unwrap();
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    let u = &v["hookSpecificOutput"]["updatedToolOutput"];
    assert!(u["nested"]["deep"]
        .as_str()
        .unwrap()
        .starts_with("varde-toz: captured"));
    assert_eq!(u["nested"]["n"], 1);
    // no text anywhere → nothing
    let numeric = serde_json::json!({
        "tool_name": "Mystery", "tool_input": {}, "tool_response": {"a": 1, "b": [1, 2]}
    });
    toz(&e)
        .args(["capture", "--hook"])
        .write_stdin(numeric.to_string())
        .assert()
        .success()
        .stdout("");
    // garbage → fail open
    toz(&e)
        .args(["capture", "--hook"])
        .write_stdin("not json")
        .assert()
        .success()
        .stdout("");
}

#[test]
fn hook_mode_content_blocks_preserves_non_text_blocks() {
    let e = env();
    let big: String = (1..=2000).map(|i| format!("l{i} ")).collect();
    let image = serde_json::json!({
        "type": "image", "data": "aW1hZ2U=", "mimeType": "image/png"
    });
    let resource = serde_json::json!({
        "type": "resource_link", "name": "report", "uri": "file:///report.pdf"
    });
    let mcp = serde_json::json!({
        "tool_name": "AnotherTool",
        "tool_input": {},
        "tool_response": [
            image,
            {"type": "text", "text": big},
            resource,
            {"type": "text", "text": "trailing text"}
        ]
    });

    let out = toz(&e)
        .args(["capture", "--hook"])
        .write_stdin(mcp.to_string())
        .output()
        .unwrap();
    assert!(out.status.success());
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    let upd = v["hookSpecificOutput"]["updatedMCPToolOutput"]
        .as_array()
        .unwrap();

    assert_eq!(upd.len(), 3);
    assert_eq!(upd[0], image);
    assert_eq!(upd[1]["type"], "text");
    assert!(upd[1]["text"]
        .as_str()
        .unwrap()
        .starts_with("varde-toz: captured"));
    assert_eq!(upd[2], resource);
}

#[test]
fn hook_skips_toz_commands() {
    let e = env();
    let big: String = (1..=2000).map(|i| format!("l{i} ")).collect();
    for binary in ["toz", "varde-toz"] {
        let payload = serde_json::json!({
            "tool_name": "Bash", "tool_input": {"command": format!("{binary} query --handle abcd")},
            "tool_response": {"stdout": big, "stderr": ""}
        });
        toz(&e)
            .args(["capture", "--hook"])
            .write_stdin(payload.to_string())
            .assert()
            .success()
            .stdout("");
    }
}

#[test]
fn hook_structured_shapes_replace_payload_in_place() {
    let e = env();
    let big: String = (1..=2000).map(|i| format!("l{i} ")).collect();

    // Small structured output stays inline regardless of tool name.
    let small = "short result";
    let read = serde_json::json!({
        "tool_name": "Read", "tool_input": {"file_path": "/x/a.rs"},
        "tool_response": {"type": "text", "file": {"filePath": "/x/a.rs", "content": small, "numLines": 1}}
    });
    toz(&e)
        .args(["capture", "--hook"])
        .write_stdin(read.to_string())
        .assert()
        .success()
        .stdout("");

    // Large structured output has its text replaced while sibling fields remain.
    let huge: String = (1..=8000).map(|i| format!("line {i}\n")).collect();
    let read = serde_json::json!({
        "tool_name": "Read", "tool_input": {"file_path": "/x/a.rs"},
        "tool_response": {"type": "text", "file": {"filePath": "/x/a.rs", "content": huge, "numLines": 8000}}
    });
    let out = toz(&e)
        .args(["capture", "--hook"])
        .write_stdin(read.to_string())
        .output()
        .unwrap();
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    let f = &v["hookSpecificOutput"]["updatedToolOutput"]["file"];
    assert!(f["content"]
        .as_str()
        .unwrap()
        .starts_with("varde-toz: captured"));
    assert_eq!(f["filePath"], "/x/a.rs");
    assert_eq!(f["numLines"], 8000);
    assert_eq!(v["hookSpecificOutput"]["updatedToolOutput"]["type"], "text");

    // Explicit ranges use the same threshold as every other result.
    let ranged = serde_json::json!({
        "tool_name": "Read", "tool_input": {"file_path": "/x/a.rs", "offset": 1, "limit": 9000},
        "tool_response": {"type": "text", "file": {"filePath": "/x/a.rs", "content": huge}}
    });
    let out = toz(&e)
        .args(["capture", "--hook"])
        .write_stdin(ranged.to_string())
        .output()
        .unwrap();
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert!(
        v["hookSpecificOutput"]["updatedToolOutput"]["file"]["content"]
            .as_str()
            .unwrap()
            .starts_with("varde-toz: captured")
    );

    // Grep files mode: string array → one-element array holding the preview
    let files: Vec<String> = (1..=800).map(|i| format!("/src/file_{i}.rs")).collect();
    let grep = serde_json::json!({
        "tool_name": "Grep", "tool_input": {"pattern": "fn ", "path": "/src"},
        "tool_response": {"mode": "files_with_matches", "numFiles": 800, "filenames": files}
    });
    let out = toz(&e)
        .args(["capture", "--hook"])
        .write_stdin(grep.to_string())
        .output()
        .unwrap();
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    let u = &v["hookSpecificOutput"]["updatedToolOutput"];
    assert_eq!(u["mode"], "files_with_matches");
    assert_eq!(u["numFiles"], 800);
    assert_eq!(u["filenames"].as_array().unwrap().len(), 1);
    assert!(u["filenames"][0]
        .as_str()
        .unwrap()
        .contains("Grep: grep fn  /src"));

    // WebFetch: result field replaced, metadata kept
    let wf = serde_json::json!({
        "tool_name": "WebFetch", "tool_input": {"url": "https://example.com/doc"},
        "tool_response": {"url": "https://example.com/doc", "code": 200, "result": big}
    });
    let out = toz(&e)
        .args(["capture", "--hook"])
        .write_stdin(wf.to_string())
        .output()
        .unwrap();
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    let u = &v["hookSpecificOutput"]["updatedToolOutput"];
    assert_eq!(u["code"], 200);
    assert!(u["result"]
        .as_str()
        .unwrap()
        .contains("WebFetch: https://example.com/doc"));
}

#[test]
fn hook_log_records_raw_payloads() {
    let e = env();
    let log = e.project.path().join("hook.log");
    let small = serde_json::json!({"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {"stdout": "a"}});
    toz(&e)
        .env("TOZ_HOOK_LOG", &log)
        .args(["capture", "--hook"])
        .write_stdin(small.to_string())
        .assert()
        .success();
    assert_eq!(
        std::fs::read_to_string(&log).unwrap().trim(),
        small.to_string()
    );
}

#[test]
fn install_writes_bundle_with_absolute_binary_path() {
    let e = env();
    let dir = e.project.path().join("plugin");
    toz(&e)
        .args(["install", "claude-code", "--dir", dir.to_str().unwrap()])
        .assert()
        .success()
        .stdout(predicate::str::contains("wrote"));
    let hooks = std::fs::read_to_string(dir.join("hooks/hooks.json")).unwrap();
    assert!(!hooks.contains("{{TOZ_BIN}}"));
    assert!(hooks.contains("/varde-toz --fallback-dir"));
    assert!(hooks.contains("capture --hook"));
    assert!(dir.join(".claude-plugin/plugin.json").exists());
    assert!(!dir.join("skills/toz").exists());
    // idempotent
    toz(&e)
        .args(["install", "claude-code", "--dir", dir.to_str().unwrap()])
        .assert()
        .stdout(predicate::str::contains("wrote").not());
    toz(&e)
        .args(["install", "nope"])
        .assert()
        .failure()
        .stderr(predicate::str::contains("unknown harness"));
}

#[test]
fn note_emits_session_start_json() {
    let e = env();
    let out = toz(&e)
        .args(["note", "--harness", "claude-code"])
        .output()
        .unwrap();
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(v["hookSpecificOutput"]["hookEventName"], "SessionStart");
    assert!(v["hookSpecificOutput"]["additionalContext"]
        .as_str()
        .unwrap()
        .contains("toz query --handle"));
    toz(&e)
        .args(["note"])
        .assert()
        .stdout(predicate::str::starts_with("varde-toz (tool-output-zone)"));
}

#[test]
fn per_tool_threshold_from_config() {
    let e = env();
    std::fs::write(
        e.cfg_path.join("config.toml"),
        "[thresholds]\nBash = 100000\n",
    )
    .unwrap();
    let big: String = (1..=2000).map(|i| format!("l{i} ")).collect();
    let payload = serde_json::json!({
        "tool_name": "Bash", "tool_input": {"command": "seq"},
        "tool_response": {"stdout": big, "stderr": ""}
    });
    toz(&e)
        .args(["capture", "--hook"])
        .write_stdin(payload.to_string())
        .assert()
        .success()
        .stdout("");
}

// ---------------------------------------------------------------------------------------------
// index

#[test]
fn doctor_reports_checks() {
    let e = env();
    let out = toz(&e).args(["doctor", "--json"]).output().unwrap();
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    let msgs: Vec<String> = v["checks"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| format!("{} {}", c["ok"], c["message"].as_str().unwrap()))
        .collect();
    let joined = msgs.join("\n");
    assert!(joined.contains("true FTS5 with trigram"), "{joined}");
    assert!(joined.contains("true store opens"), "{joined}");
    assert!(joined.contains("true fetch cache writable"), "{joined}");
    assert!(joined.contains("true config dir"), "{joined}");

    // Install the plugin into a temp dir → doctor can't see it there, but with hook_log set it warns.
    std::fs::write(
        e.cfg_path.join("config.toml"),
        format!("hook_log = {:?}\n", e.cfg_path.join("hook.log")),
    )
    .unwrap();
    toz(&e)
        .args(["doctor"])
        .assert()
        .code(1)
        .stdout(predicate::str::contains("warn hook_log is on"));
}

#[test]
fn doctor_warns_when_installed_harness_version_is_unavailable() {
    let e = env();
    let home = TempDir::new().unwrap();
    let pi = home.path().join(".pi/agent/extensions");
    std::fs::create_dir_all(&pi).unwrap();
    std::fs::write(pi.join("toz.ts"), "installed shim").unwrap();
    let out = toz(&e)
        .env("HOME", home.path())
        .env("XDG_CONFIG_HOME", home.path().join(".config"))
        .env("PATH", "")
        .args(["doctor", "--json"])
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(1));
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    let pi_check = v["checks"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| {
            c["message"]
                .as_str()
                .is_some_and(|m| m.contains("pi version unknown"))
        })
        .expect("installed pi shim should be checked");
    assert_eq!(pi_check["ok"], false);
}

// ---------------------------------------------------------------------------------------------
// chunk strategies end to end

#[test]
fn cargo_test_output_titles_failures() {
    let e = env();
    let mut text = String::from("running 3 tests\ntest alpha ... ok\ntest beta ... FAILED\ntest gamma ... ok\n\nfailures:\n\n---- beta stdout ----\n");
    for i in 0..40 {
        text.push_str(&format!(
            "thread 'beta' assertion line {i}: left != right for widget {i}\n"
        ));
    }
    text.push_str("\nfailures:\n    beta\n\ntest result: FAILED. 2 passed; 1 failed\n");
    let out = toz(&e)
        .args(["capture", "--label", "cargo test", "--threshold", "100"])
        .write_stdin(text)
        .output()
        .unwrap();
    let text = String::from_utf8_lossy(&out.stdout);
    assert!(text.contains("FAIL beta"), "{text}");
    assert!(text.contains("test result: FAILED"), "{text}");
}

#[test]
fn preview_caps_line_length() {
    let e = env();
    let long = "x".repeat(100_000);
    let out = toz(&e)
        .args(["capture", "--label", "minified"])
        .write_stdin(format!("{long}\nshort\n"))
        .output()
        .unwrap();
    assert!(
        out.stdout.len() < 2000,
        "preview is {} bytes",
        out.stdout.len()
    );
    assert!(String::from_utf8_lossy(&out.stdout).contains("xxxx…"));
}

// ---------------------------------------------------------------------------------------------
// other harnesses

#[test]
fn install_pi_opencode_codex_into_dirs() {
    let e = env();
    let root = e.project.path();

    let pi = root.join("pi-ext");
    toz(&e)
        .args(["install", "pi", "--dir", pi.to_str().unwrap()])
        .assert()
        .success();
    let ext = std::fs::read_to_string(pi.join("extensions/varde-toz.ts")).unwrap();
    assert!(!pi.join("skills/toz").exists());
    assert!(
        ext.contains("const NOTE = \"varde-toz (tool-output-zone)"),
        "note not rendered"
    );
    assert!(ext.contains("--harness\", \"pi\""));
    assert!(!ext.contains("{{TOZ_"));

    let oc = root.join("oc-plugin");
    toz(&e)
        .args([
            "install",
            "opencode",
            "--dir",
            oc.to_str().unwrap(),
            "--for-version",
            "2.0.12",
        ])
        .assert()
        .success();
    assert!(std::fs::read_to_string(oc.join("plugin/varde-toz.ts"))
        .unwrap()
        .contains("\"execute.after\""));
    assert!(!oc.join("skills/toz").exists());

    // Codex: merges into an existing hooks.json and AGENTS.md, idempotently.
    let cx = root.join("codex-home");
    std::fs::create_dir_all(&cx).unwrap();
    std::fs::write(
        cx.join("hooks.json"),
        r#"{"hooks":{"PostToolUse":[{"hooks":[{"type":"command","command":"/x/other.sh"}]}]}}"#,
    )
    .unwrap();
    std::fs::write(cx.join("AGENTS.md"), "# My rules\n\nBe nice.\n").unwrap();
    toz(&e)
        .args(["install", "codex", "--dir", cx.to_str().unwrap()])
        .assert()
        .success()
        .stdout(predicate::str::contains("wrote"));
    let hooks: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(cx.join("hooks.json")).unwrap()).unwrap();
    // Codex observes supported tool results with one PostToolUse hook.
    assert_eq!(hooks["hooks"]["PostToolUse"].as_array().unwrap().len(), 2);
    assert_eq!(
        hooks["hooks"]["PostToolUse"][0]["hooks"][0]["command"],
        "/x/other.sh"
    );
    assert_eq!(hooks["hooks"]["PostToolUse"][1]["matcher"], "*");
    assert!(hooks["hooks"]["PostToolUse"][1]["hooks"][0]["command"]
        .as_str()
        .unwrap()
        .contains("capture --hook --harness codex"));
    assert!(hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        .as_str()
        .unwrap()
        .ends_with("note --harness codex"));
    let agents = std::fs::read_to_string(cx.join("AGENTS.md")).unwrap();
    assert!(
        agents.starts_with("# My rules\n\nBe nice.\n\n<!-- varde-toz:start -->"),
        "{agents}"
    );
    assert!(agents.contains("varde-toz (tool-output-zone) is active"));
    assert!(!cx.join("skills/toz").exists());
    // Second install: nothing changes.
    toz(&e)
        .args(["install", "codex", "--dir", cx.to_str().unwrap()])
        .assert()
        .success()
        .stdout(predicate::str::contains("wrote").not());

    // Uninstall reverses each mode and leaves foreign content alone.
    toz(&e)
        .args(["uninstall", "codex", "--dir", cx.to_str().unwrap()])
        .assert()
        .success()
        .stdout(predicate::str::contains("toz entries removed"));
    let hooks: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(cx.join("hooks.json")).unwrap()).unwrap();
    assert_eq!(hooks["hooks"]["PostToolUse"].as_array().unwrap().len(), 1);
    assert!(hooks["hooks"].get("SessionStart").is_none());
    assert_eq!(
        std::fs::read_to_string(cx.join("AGENTS.md")).unwrap(),
        "# My rules\n\nBe nice.\n"
    );
    assert!(!cx.join("skills/toz").exists());
    assert!(cx.exists());

    toz(&e)
        .args(["uninstall", "pi", "--dir", pi.to_str().unwrap()])
        .assert()
        .success();
    assert!(!pi.join("extensions/varde-toz.ts").exists());
    assert!(!pi.join("skills").exists(), "empty dirs pruned");
    assert!(pi.exists(), "the harness root is never removed");

    // Claude Code owns its whole plugin dir, which goes away entirely.
    let cc = root.join("cc-plugin");
    toz(&e)
        .args(["install", "claude-code", "--dir", cc.to_str().unwrap()])
        .assert()
        .success();
    toz(&e)
        .args(["uninstall", "claude-code", "--dir", cc.to_str().unwrap()])
        .assert()
        .success();
    assert!(!cc.exists());
}

#[test]
fn install_opencode_picks_the_variant_matching_the_harness_version() {
    let e = env();
    let oc = e.project.path().join("oc1");
    let plugin = oc.join("plugin/varde-toz.ts");

    // opencode 1.x gets the hook-map plugin, not the 2.x { id, setup(ctx) } one.
    toz(&e)
        .args([
            "install",
            "opencode",
            "--dir",
            oc.to_str().unwrap(),
            "--for-version",
            "1.17.7",
        ])
        .assert()
        .success()
        .stdout(predicate::str::contains("1.x plugin shim"));
    let v1 = std::fs::read_to_string(&plugin).unwrap();
    assert!(v1.contains("\"tool.execute.after\""), "{v1}");
    assert!(v1.contains("\"experimental.chat.system.transform\""));
    assert!(v1.contains("--harness\", \"opencode\""));
    assert!(!v1.contains("setup(ctx"));
    assert!(!v1.contains("{{TOZ_"));
    // Exactly one export: opencode 1.x calls every export as a plugin factory.
    assert_eq!(v1.matches("\nexport ").count(), 1, "{v1}");

    // Too old for either shim: fall back to the oldest variant we ship.
    toz(&e)
        .args([
            "install",
            "opencode",
            "--dir",
            oc.to_str().unwrap(),
            "--for-version",
            "1.0.0",
        ])
        .assert()
        .success();
    assert_eq!(std::fs::read_to_string(&plugin).unwrap(), v1);

    // Upgrading to 2.x rewrites the shim in place rather than refusing as unowned.
    toz(&e)
        .args([
            "install",
            "opencode",
            "--dir",
            oc.to_str().unwrap(),
            "--for-version",
            "2.0.12",
        ])
        .assert()
        .success();
    let v2 = std::fs::read_to_string(&plugin).unwrap();
    assert!(v2.contains("\"execute.after\""), "{v2}");

    // …and back again, then uninstall removes the 1.x file too.
    toz(&e)
        .args([
            "install",
            "opencode",
            "--dir",
            oc.to_str().unwrap(),
            "--for-version",
            "1.17.7",
        ])
        .assert()
        .success();
    toz(&e)
        .args(["uninstall", "opencode", "--dir", oc.to_str().unwrap()])
        .assert()
        .success();
    assert!(!plugin.exists());
    assert!(!oc.join("skills").exists());

    toz(&e)
        .args([
            "install",
            "opencode",
            "--dir",
            oc.to_str().unwrap(),
            "--for-version",
            "nope",
        ])
        .assert()
        .failure()
        .stderr(predicate::str::contains("not an X.Y.Z version"));
}

// ---------------------------------------------------------------------------------------------
// beta hardening

#[test]
fn hook_mode_never_exits_nonzero() {
    let e = env();
    // Unreadable store location → every other command errors; the hook must still exit 0 silently.
    let bad = e.project.path().join("not-a-dir");
    std::fs::write(&bad, "x").unwrap();
    let payload = serde_json::json!({
        "tool_name": "Bash", "tool_input": {"command": "seq 1 9999"},
        "tool_response": {"stdout": "y".repeat(20_000), "stderr": ""}
    });
    let out = toz(&e)
        .env("TOZ_CONFIG_DIR", &bad)
        .args(["capture", "--hook"])
        .write_stdin(payload.to_string())
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(0));
    assert!(
        out.stdout.is_empty(),
        "{}",
        String::from_utf8_lossy(&out.stdout)
    );
    assert!(String::from_utf8_lossy(&out.stderr).contains("failed open"));

    // Garbage on stdin is also fine.
    let out = toz(&e)
        .args(["capture", "--hook"])
        .write_stdin("{not json")
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(0));
    assert!(out.stdout.is_empty());
}

#[cfg(unix)]
#[test]
fn store_is_private_to_the_user() {
    use std::os::unix::fs::PermissionsExt;
    let e = env();
    toz(&e)
        .args(["capture", "--label", "x", "--force"])
        .write_stdin("hello")
        .assert()
        .success();
    let key = toz_core::project::key_for(&e.project.path().canonicalize().unwrap());
    let dir = e.cfg_path.join(key);
    assert_eq!(
        std::fs::metadata(&dir).unwrap().permissions().mode() & 0o777,
        0o700
    );
    assert_eq!(
        std::fs::metadata(dir.join("toz.db"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
}

/// Shapes taken from the Claude Code 2.1.267 bundle: Grep returns `{mode, numFiles, filenames,
/// content?, …}` and shows `content` in content mode, else `filenames.join("\n")`; Glob returns
/// `{filenames, durationMs, numFiles, truncated, …}` and shows `filenames.join("\n")`.

#[test]
fn harness_bundles_supply_external_fallback_for_capture_and_retrieval() {
    let e = env();
    for harness in ["codex", "claude-code", "pi", "opencode"] {
        let dir = e.cfg_path.join(format!("{harness} space ' quote"));
        toz(&e)
            .args(["install", harness, "--dir", dir.to_str().unwrap()])
            .assert()
            .success();
        let (file, is_json) = match harness {
            "codex" => ("hooks.json", true),
            "claude-code" => ("hooks/hooks.json", true),
            "pi" => ("extensions/varde-toz.ts", false),
            _ => ("plugin/varde-toz.ts", false),
        };
        let text = std::fs::read_to_string(dir.join(file)).unwrap();
        assert!(!text.contains("{{TOZ_"));
        if is_json {
            let doc: serde_json::Value = serde_json::from_str(&text).unwrap();
            let command = doc["hooks"]["SessionStart"][0]["hooks"][0]["command"]
                .as_str()
                .unwrap();
            let output = std::process::Command::new("sh")
                .args(["-c", command])
                .env_remove("TOZ_CONFIG_DIR")
                .env_remove("TOZ_FALLBACK_DIR")
                .env("VARDE_CONFIG_DIR", &e.varde_cfg_path)
                .output()
                .unwrap();
            assert!(output.status.success(), "{:?}", output);
            let note: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
            let note = note["hookSpecificOutput"]["additionalContext"]
                .as_str()
                .unwrap();
            assert!(note.contains("TOZ_FALLBACK_DIR="));
            assert!(note.contains("toz query --handle"));
        } else {
            assert!(text.contains("TOZ_FALLBACK_DIR: FALLBACK"));
            assert!(text.contains("TOZ_FALLBACK_DIR="));
        }
    }
    assert!(!e.project.path().join(".toz").exists());
}

#[test]
fn preview_lists_distinctive_terms_and_line_count() {
    let e = env();
    let mut text = String::new();
    for i in 0..400 {
        let extra = match i {
            0 => " connect_timeout exceeded for shard_replica",
            100 => " connect_timeout retry on shard_replica",
            _ => "",
        };
        text.push_str(&format!("worker {i} processed batch item ok{extra}\n"));
    }
    let out = toz(&e)
        .args(["capture", "--label", "t"])
        .write_stdin(text)
        .output()
        .unwrap();
    let s = String::from_utf8_lossy(&out.stdout);
    assert!(s.contains("(400 lines, "), "{s}");
    let terms = s
        .lines()
        .find(|l| l.starts_with("terms: "))
        .expect("terms line");
    assert!(
        terms.contains("connect_timeout") && terms.contains("shard_replica"),
        "{terms}"
    );
    assert!(
        !terms.contains("processed"),
        "boilerplate excluded: {terms}"
    );
}

#[test]
fn source_file_previews_use_definition_titles() {
    let e = env();
    let mut src = String::from("//! module\nuse std::io;\n\n");
    for i in 0..12 {
        src.push_str(&format!(
            "/// Does thing {i}.\npub fn thing_{i}(x: u32) -> u32 {{\n    let y = x + {i};\n    y * 2\n}}\n\n"
        ));
    }
    let out = toz(&e)
        .args(["capture", "--label", "lib.rs", "--threshold", "100"])
        .write_stdin(src)
        .output()
        .unwrap();
    let s = String::from_utf8_lossy(&out.stdout);
    assert!(s.contains("fn thing_0(x: u32) -> u32"), "{s}");
    assert!(
        !s.lines()
            .any(|l| l.trim_start().starts_with(char::is_numeric) && l.contains("  }  ")),
        "no brace titles: {s}"
    );
}

#[test]
fn script_computes_over_a_capture_without_returning_the_body() {
    let e = env();
    let h = capture_lines(&e, "log", 500);
    let (_, stdout) = script_result(
        &e,
        &[
            "--handle",
            &h,
            "--code",
            "let n=0; toz.eachLine(l=>{if(l.startsWith('ERROR'))n++}); print(n, toz.handle.lines)",
        ],
        None,
    );
    assert_eq!(stdout.trim(), "71 500");
    // The whole point: the body stayed in the store.
    assert!(
        !stdout.contains("req=13"),
        "body leaked into output: {stdout}"
    );
}

#[test]
fn sandboxed_script_command_captures_short_output_and_cannot_read_store_db() {
    let e = env();
    std::fs::write(
        e.cfg_path.join("config.toml"),
        "[sandbox]\nenabled = true\n",
    )
    .unwrap();
    let project = toz_core::Project::resolve(Some(e.project.path())).unwrap();
    let db = e.cfg_path.join(project.key).join("toz.db");
    let read_private = format!(
        "let r=toz.exec({{argv:['/bin/cat',{}]}}); print(r.exitCode)",
        serde_json::to_string(&db.display().to_string()).unwrap()
    );
    let (_, denied) = script_result(&e, &["--code", &read_private], None);
    assert_eq!(denied, "1\n");

    let (_, text) = script_result(&e, &["--code", "let r=toz.exec({shell:'printf short'}); print(JSON.stringify({capture:r.capture,stdout:r.stdout}))"], None);
    let result: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(result["stdout"], "short");
    assert_eq!(result["capture"]["state"], "captured");
    let handle = result["capture"]["handle"].as_str().unwrap();
    toz(&e)
        .args(["query", "--handle", handle])
        .assert()
        .success()
        .stdout("short\n");
}

#[test]
fn default_script_inherits_host_file_access() {
    let e = env();
    let outside = tempfile::tempdir().unwrap();
    let file = outside.path().join("outside.txt");
    std::fs::write(&file, "outside data").unwrap();
    let path = serde_json::to_string(&file.display().to_string()).unwrap();
    let code = format!("let r=toz.exec({{argv:['/bin/cat',{path}]}}); print(r.stdout)");
    let (_, result) = script_result(&e, &["--code", &code], None);
    assert_eq!(result, "outside data\n");
}

#[test]
fn sandbox_workspace_permissions_apply_to_child_commands() {
    let e = env();
    let file = e.project.path().join("private.txt");
    std::fs::write(&file, "workspace data").unwrap();
    let path = serde_json::to_string(&file.display().to_string()).unwrap();

    std::fs::write(
        e.cfg_path.join("config.toml"),
        "[sandbox]\nenabled = true\nworkspace = 'none'\n",
    )
    .unwrap();
    let denied = format!("let r=toz.exec({{argv:['/bin/cat',{path}]}}); print(r.exitCode)");
    let (_, result) = script_result(&e, &["--code", &denied], None);
    assert_ne!(result.trim(), "0");

    std::fs::write(
        e.cfg_path.join("config.toml"),
        "[sandbox]\nenabled = true\nworkspace = 'read-only'\n",
    )
    .unwrap();
    let read = format!("let r=toz.exec({{argv:['/bin/cat',{path}]}}); print(r.stdout)");
    let (_, result) = script_result(&e, &["--code", &read], None);
    assert_eq!(result, "workspace data\n");
    let write = format!(
        "let r=toz.exec({{shell:'printf changed > {}'}}); print(r.exitCode)",
        file.display()
    );
    let (_, result) = script_result(&e, &["--code", &write], None);
    assert_ne!(result.trim(), "0");
    assert_eq!(std::fs::read_to_string(file).unwrap(), "workspace data");
}

#[test]
fn script_command_can_request_opt_in_exact_raw_output() {
    let e = env();
    std::fs::write(e.cfg_path.join("config.toml"), "[raw]\nenabled = true\n").unwrap();
    let (_, handle) = script_result(
        &e,
        &[
            "--code",
            "let r=toz.exec({shell:'printf raw-bytes',raw:true}); print(r.raw.handle)",
        ],
        None,
    );
    toz(&e)
        .args(["query", "--raw", handle.trim()])
        .assert()
        .success()
        .stdout("raw-bytes");
}

#[test]
fn script_stdin_source_survives_shell_metacharacters() {
    let e = env();
    let h = capture_lines(&e, "log", 40);
    // Quotes, backticks, $, and a regex — the reason --file - is the documented form.
    let src = r#"
const c = {};
toz.eachLine(l => {
  const k = l.startsWith("ERROR") ? `err ${l.match(/code=(\d+)/)[1]}` : 'ok';
  c[k] = (c[k] || 0) + 1;
});
print(JSON.stringify(c));
"#;
    let (_, stdout) = script_result(&e, &["--handle", &h, "--script", "-"], Some(src));
    let counts: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(counts["err 500"], 5);
    assert_eq!(counts["ok"], 35);
}

#[test]
fn script_exit_codes_distinguish_failures_and_reserve_two() {
    let e = env();
    let h = capture_lines(&e, "log", 20);
    let cases: [(&str, i32); 4] = [
        ("while(true){}", 3),
        ("const a=[];for(;;)a.push(new Array(4096).fill(7))", 4),
        ("for(let i=0;i<1e6;i++)print('xxxxxxxxxxxxxxxxxxxxxxxx')", 5),
        ("toz.nope()", 1),
    ];
    for (code, want) in cases {
        let out = toz(&e)
            .args([
                "run",
                "--handle",
                &h,
                "--timeout-ms",
                "400",
                "--memory-mb",
                "8",
                "--code",
                code,
            ])
            .output()
            .unwrap();
        assert_eq!(out.status.code(), Some(want), "for `{code}`");
    }
    // 2 stays toz's own failure, which is why the script codes skip it.
    toz(&e)
        .args(["run", "--handle", "zzzz", "--code", "print(1)"])
        .assert()
        .code(2);
}

#[test]
fn script_large_result_becomes_a_handle() {
    let e = env();
    let h = capture_lines(&e, "log", 500);
    let out = toz(&e)
        .args([
            "run",
            "--handle",
            &h,
            "--code",
            "toz.eachLine(l => print(l, l.length))",
        ])
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("handle"), "{stdout}");
    assert!(!stdout.contains("ok req=1"), "{stdout}");
}

/// User-scope profiles (`<VARDE_CONFIG_DIR>/toz/profiles.toml`) never need `trusted_projects`;
/// only project-scope profiles do.
fn write_user_profile(varde_dir: &std::path::Path, toml: &str) {
    let dir = varde_dir.join("toz");
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("profiles.toml"), toml).unwrap();
}

#[test]
fn profile_script_replaces_preview_and_records_are_queryable() {
    let e = env();
    let varde_dir = TempDir::new().unwrap();
    write_user_profile(
        varde_dir.path(),
        r#"
[[profile]]
id = "counter"
match = { source = "script-ok" }
script = """
let n = 0;
toz.eachLine(l => { n++; toz.record('line', {l}); });
print('lines: ' + n);
"""
"#,
    );

    let out = toz(&e)
        .env("VARDE_CONFIG_DIR", varde_dir.path())
        .args([
            "capture",
            "--label",
            "script-ok",
            "--source",
            "script-ok",
            "--force",
        ])
        .write_stdin("a\nb\nc\n")
        .output()
        .unwrap();
    assert!(out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("lines: 3"), "{stdout}");
    assert!(!stdout.contains("── sections"), "{stdout}");
    let handle = stdout
        .split("handle ")
        .nth(1)
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap()
        .to_string();

    let records = toz(&e)
        .env("VARDE_CONFIG_DIR", varde_dir.path())
        .args(["query", "--handle", &handle, "--records", "line"])
        .output()
        .unwrap();
    assert!(records.status.success());
    let rows: Vec<serde_json::Value> = String::from_utf8_lossy(&records.stdout)
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    assert_eq!(rows.len(), 3);
    assert_eq!(rows[0]["l"], "a");
    assert_eq!(rows[2]["l"], "c");
}

#[test]
fn profile_script_failure_falls_back_and_surfaces_in_doctor() {
    let e = env();
    let varde_dir = TempDir::new().unwrap();
    write_user_profile(
        varde_dir.path(),
        r#"
[[profile]]
id = "boom"
match = { source = "script-throw" }
script = "throw new Error('boom')"
"#,
    );

    let out = toz(&e)
        .env("VARDE_CONFIG_DIR", varde_dir.path())
        .args([
            "capture",
            "--label",
            "script-throw",
            "--source",
            "script-throw",
            "--force",
        ])
        .write_stdin("a\nb\n")
        .output()
        .unwrap();
    assert!(out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("── sections"), "{stdout}");

    let doctor = toz(&e)
        .env("VARDE_CONFIG_DIR", varde_dir.path())
        .args(["--json", "doctor"])
        .output()
        .unwrap();
    let report: serde_json::Value = serde_json::from_slice(&doctor.stdout).unwrap();
    let diags = report["profile_diagnostics"].as_array().unwrap();
    assert_eq!(diags.len(), 1, "{report}");
    assert_eq!(diags[0]["profile_id"], "boom");
    assert!(diags[0]["reason"].as_str().unwrap().contains("boom"));
}

#[test]
fn doctor_reports_project_script_dropped_for_untrusted_project() {
    let e = env();
    let varde_dir = TempDir::new().unwrap();
    // No trusted_projects entry in user scope, so the project-scope script below is dropped.
    write_user_profile(varde_dir.path(), "");

    let project_dir = e.project.path().join(".varde");
    std::fs::create_dir_all(&project_dir).unwrap();
    std::fs::write(
        project_dir.join("toz-profiles.toml"),
        r#"
[[profile]]
id = "proj"
script = "toz.record('x', {})"
"#,
    )
    .unwrap();

    let out = toz(&e)
        .env("VARDE_CONFIG_DIR", varde_dir.path())
        .args(["--json", "doctor"])
        .output()
        .unwrap();
    let report: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    let diags = report["profile_load_diagnostics"].as_array().unwrap();
    assert_eq!(diags.len(), 1, "{report}");
    assert_eq!(diags[0]["profile_id"], "proj");
    assert!(
        diags[0]["reason"]
            .as_str()
            .unwrap()
            .contains("trusted_projects"),
        "{report}"
    );

    let text = toz(&e)
        .env("VARDE_CONFIG_DIR", varde_dir.path())
        .args(["doctor"])
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&text.stdout);
    assert!(
        stdout.contains("profile diagnostic: proj") && stdout.contains("trusted_projects"),
        "{stdout}"
    );
}

fn write_profiles_file(dir: &std::path::Path, name: &str, toml: &str) -> std::path::PathBuf {
    let path = dir.join(name);
    std::fs::write(&path, toml).unwrap();
    path
}

#[test]
fn profile_test_passes_a_declarative_and_a_scripted_case() {
    let e = env();
    let path = write_profiles_file(
        e.project.path(),
        "profiles.toml",
        r###"
[[profile]]
id = "cargo-test"
match = { command = "cargo test*" }
sections = { heading = "^## (.+)$" }
preview = { kind = "toc", items_per_section = 3 }

[[profile.test]]
name = "toc lists the heading"
input = "## Section One\nline\n"
expect_preview_contains = ["Section One"]

[[profile]]
id = "cargo-test-script"
match = { source = "script-count" }
script = """
let n = 0;
toz.eachLine(l => { n++; toz.record('line', {n}); });
print('lines: ' + n);
"""

[[profile.test]]
name = "records one line per input line"
input = "a\nb\n"
expect_records = { line = [{ n = 1 }, { n = 2 }] }
expect_preview_contains = ["lines: 2"]
"###,
    );

    let out = toz(&e)
        .args(["profile", "test", "--file"])
        .arg(&path)
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(out.status.success(), "{stdout}");
    assert!(
        stdout.contains("pass: cargo-test / toc lists the heading"),
        "{stdout}"
    );
    assert!(
        stdout.contains("pass: cargo-test-script / records one line per input line"),
        "{stdout}"
    );
}

#[test]
fn profile_test_fails_and_names_the_case() {
    let e = env();
    let path = write_profiles_file(
        e.project.path(),
        "profiles.toml",
        r#"
[[profile]]
id = "cargo-test"
match = { command = "cargo test*" }

[[profile.test]]
name = "wrong expectation"
input = "line one\n"
expect_preview_contains = ["this text never appears"]
"#,
    );

    let out = toz(&e)
        .args(["profile", "test", "--file"])
        .arg(&path)
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(!out.status.success());
    assert!(
        stdout.contains("FAIL: cargo-test / wrong expectation"),
        "{stdout}"
    );
}

#[test]
fn builtin_nav_map_profile_toc_previews_a_real_capture() {
    // Real `varde-code nav_map --format text` output, captured once against this repo's
    // code-cli crate. The built-in `varde-code-nav-map` profile (crates/toz-core/src/
    // builtin_profiles.toml) needs no user or project profiles file to match it.
    let fixture = include_str!("fixtures/varde-code-nav-map.txt");
    let e = env();

    let out = toz(&e)
        .args([
            "capture",
            "--label",
            "nav-map",
            "--source",
            "varde-code nav_map /r",
            "--force",
        ])
        .write_stdin(fixture)
        .output()
        .unwrap();
    assert!(out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);

    assert!(
        stdout.len() <= 4096,
        "preview should be capped at 4 KB, was {} bytes: {stdout}",
        stdout.len()
    );
    for section in [
        "entrypoints",
        "foundational_files",
        "module_layers",
        "subsystems",
        "symbols",
        "flows",
        "hotspots",
    ] {
        assert!(
            stdout.contains(section),
            "missing section {section:?}: {stdout}"
        );
    }
}

/// The `toz` key in the varde user config sets the store
/// directory outright: it wins over an already-existing `--fallback-dir` store, and `doctor`
/// reports it as the source.
#[test]
fn varde_config_toz_key_wins_over_an_existing_fallback_store() {
    let e = env();
    let project_root = e.project.path().canonicalize().unwrap();
    let key = toz_core::project::key_for(&project_root);

    // An existing fallback store — today's behavior would otherwise prefer this.
    let fallback = TempDir::new().unwrap();
    std::fs::create_dir_all(fallback.path().join(&key)).unwrap();
    std::fs::write(fallback.path().join(&key).join("toz.db"), b"").unwrap();

    let varde_store = TempDir::new().unwrap();
    std::fs::write(
        e.varde_cfg_path.join("paths.toml"),
        format!("[default]\ntoz = \"{}\"\n", varde_store.path().display()),
    )
    .unwrap();

    let out = toz(&e)
        .env_remove("TOZ_CONFIG_DIR")
        .args([
            "capture",
            "--label",
            "varde-store",
            "--source",
            "varde-store",
            "--force",
        ])
        .write_stdin("hello from varde config\n")
        .output()
        .unwrap();
    assert!(out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);
    let handle = stdout
        .split("handle ")
        .nth(1)
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap()
        .to_string();
    assert!(
        varde_store.path().join(&key).join("toz.db").is_file(),
        "expected the store under the varde config dir, not the fallback dir"
    );

    // `--fallback-dir` is ignored while the varde `toz` key is set.
    let out = toz(&e)
        .env_remove("TOZ_CONFIG_DIR")
        .args(["--fallback-dir", fallback.path().to_str().unwrap()])
        .args(["query", "--handle", &handle])
        .output()
        .unwrap();
    assert!(out.status.success());
    assert!(
        String::from_utf8_lossy(&out.stdout).contains("hello from varde config"),
        "{}",
        String::from_utf8_lossy(&out.stdout)
    );

    let doctor = toz(&e)
        .env_remove("TOZ_CONFIG_DIR")
        .args(["doctor"])
        .output()
        .unwrap();
    assert!(
        String::from_utf8_lossy(&doctor.stdout).contains("source: varde config"),
        "{}",
        String::from_utf8_lossy(&doctor.stdout)
    );
}

#[test]
fn varde_config_toml_sets_store_after_paths_migration() {
    let e = env();
    let project_root = e.project.path().canonicalize().unwrap();
    let key = toz_core::project::key_for(&project_root);
    let store = TempDir::new().unwrap();
    std::fs::write(
        e.varde_cfg_path.join("config.toml"),
        format!(
            "[default]\ntoz = \"{}\"\n[settings]\nusage_limit = \"80%\"\n",
            store.path().display()
        ),
    )
    .unwrap();

    toz(&e)
        .env_remove("TOZ_CONFIG_DIR")
        .args(["capture", "--label", "migrated-config", "--force"])
        .write_stdin("hello\n")
        .assert()
        .success();
    assert!(store.path().join(key).join("toz.db").is_file());
}

/// A `[project."<root>"]` entry overrides `[default]` for that project.
#[test]
fn varde_config_project_table_overrides_default() {
    let e = env();
    let project_root = e.project.path().canonicalize().unwrap();
    let key = toz_core::project::key_for(&project_root);

    let default_store = TempDir::new().unwrap();
    let project_store = TempDir::new().unwrap();
    std::fs::write(
        e.varde_cfg_path.join("paths.toml"),
        format!(
            "[default]\ntoz = \"{}\"\n\n[project.\"{}\"]\ntoz = \"{}\"\n",
            default_store.path().display(),
            project_root.display(),
            project_store.path().display(),
        ),
    )
    .unwrap();

    toz(&e)
        .env_remove("TOZ_CONFIG_DIR")
        .args(["capture", "--label", "project-store", "--force"])
        .write_stdin("hello\n")
        .assert()
        .success();

    assert!(project_store.path().join(&key).join("toz.db").is_file());
    assert!(!default_store.path().join(&key).join("toz.db").is_file());
}

/// `TOZ_CONFIG_DIR` still wins over the varde `toz` key.
#[test]
fn toz_config_dir_env_still_wins_over_varde_config() {
    let e = env();
    let project_root = e.project.path().canonicalize().unwrap();
    let key = toz_core::project::key_for(&project_root);

    let varde_store = TempDir::new().unwrap();
    std::fs::write(
        e.varde_cfg_path.join("paths.toml"),
        format!("[default]\ntoz = \"{}\"\n", varde_store.path().display()),
    )
    .unwrap();

    // `toz(&e)` already sets `TOZ_CONFIG_DIR` to `e.cfg_path`.
    toz(&e)
        .args(["capture", "--label", "env-wins", "--force"])
        .write_stdin("hello\n")
        .assert()
        .success();

    assert!(e.cfg_path.join(&key).join("toz.db").is_file());
    assert!(!varde_store.path().join(&key).join("toz.db").is_file());
}

#[test]
fn legacy_alias_reads_canonical_captures() {
    let e = env();
    let handle = capture_text(&e, "alias", "compatibility content\n".to_owned());
    Command::cargo_bin("toz")
        .unwrap()
        .env("TOZ_CONFIG_DIR", &e.cfg_path)
        .env("VARDE_CONFIG_DIR", &e.varde_cfg_path)
        .current_dir(e.project.path())
        .args(["query", "--handle", &handle])
        .assert()
        .success()
        .stdout(predicate::str::contains("compatibility content"));
    for binary in ["varde-toz", "toz"] {
        Command::cargo_bin(binary)
            .unwrap()
            .arg("--help")
            .assert()
            .success()
            .stdout(predicate::str::contains(format!("Usage: {binary} ")));
        Command::cargo_bin(binary)
            .unwrap()
            .arg("--version")
            .assert()
            .success()
            .stdout(predicate::str::starts_with("varde-toz "));
    }
}
