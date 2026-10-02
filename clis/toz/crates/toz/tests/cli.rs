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

fn handle_from_preview(text: &str) -> String {
    text.split("handle ")
        .nth(1)
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap()
        .to_string()
}

#[test]
fn capture_metadata_redacts_source_and_label_without_losing_identity() {
    let e = env();
    std::fs::write(
        e.cfg_path.join("config.toml"),
        "[redact]\npatterns = ['vault-[0-9]+']\n",
    )
    .unwrap();
    let source = "task vault-123";
    let first = toz(&e)
        .args(["capture", "--source", source, "--force"])
        .write_stdin("first distinct body\n")
        .output()
        .unwrap();
    assert!(first.status.success());
    assert!(!String::from_utf8_lossy(&first.stdout).contains("vault-123"));

    let second = toz(&e)
        .args(["capture", "--source", "task vault-456", "--force"])
        .write_stdin("second distinct body\n")
        .output()
        .unwrap();
    assert!(second.status.success());
    let listed = toz(&e)
        .args(["query", "--list", "--json"])
        .output()
        .unwrap();
    assert!(listed.status.success());
    let rows: serde_json::Value = serde_json::from_slice(&listed.stdout).unwrap();
    assert_eq!(rows.as_array().unwrap().len(), 2);
    assert!(!String::from_utf8_lossy(&listed.stdout).contains("vault-123"));
    assert!(!String::from_utf8_lossy(&listed.stdout).contains("vault-456"));
    let project = toz_core::project::Project::resolve(Some(e.project.path())).unwrap();
    let store = toz_core::store::Store::open_readonly(&e.cfg_path.join(project.key).join("toz.db"))
        .unwrap();
    let stored = store.list(10, false).unwrap();
    assert_eq!(stored.len(), 2);
    assert!(stored.iter().all(|row| !row.source.contains("vault-")));
}

#[test]
fn redacted_capture_supersedes_legacy_source_and_hides_legacy_metadata() {
    let e = env();
    let source = "task vault-123";
    let legacy = toz(&e)
        .args(["capture", "--source", source, "--force"])
        .write_stdin("legacy body\n")
        .output()
        .unwrap();
    assert!(legacy.status.success());
    std::fs::write(
        e.cfg_path.join("config.toml"),
        "[redact]\npatterns = ['vault-[0-9]+']\n",
    )
    .unwrap();
    let current = toz(&e)
        .args(["capture", "--source", source, "--force"])
        .write_stdin("current body\n")
        .output()
        .unwrap();
    assert!(current.status.success());
    let listed = toz(&e)
        .args(["query", "--list", "--json"])
        .output()
        .unwrap();
    assert!(listed.status.success());
    let rows: serde_json::Value = serde_json::from_slice(&listed.stdout).unwrap();
    assert_eq!(rows.as_array().unwrap().len(), 1);
    let all = toz(&e)
        .args(["query", "--list", "--all", "--json"])
        .output()
        .unwrap();
    assert!(all.status.success());
    assert!(!String::from_utf8_lossy(&all.stdout).contains("vault-123"));
    let searched = toz(&e).args(["query", "--all", "legacy"]).output().unwrap();
    assert!(searched.status.success());
    assert!(!String::from_utf8_lossy(&searched.stdout).contains("vault-123"));
    let legacy_handle = String::from_utf8_lossy(&legacy.stdout)
        .split("handle ")
        .nth(1)
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap()
        .to_string();
    let (_, script_label) = script_result(
        &e,
        &[
            "--handle",
            &legacy_handle,
            "--code",
            "print(vardeToz.handle.label)",
        ],
        None,
    );
    assert!(!script_label.contains("vault-123"));
}

#[test]
fn migrate_metadata_rewrites_legacy_capture_without_changing_handle_or_supersession() {
    let e = env();
    std::fs::write(
        e.cfg_path.join("config.toml"),
        "[redact]\npatterns = ['vault-[0-9]+']\n",
    )
    .unwrap();
    let label = "task vault-123";
    let handle = capture_text(&e, label, "original body\n".into());
    let project = toz_core::project::Project::resolve(Some(e.project.path())).unwrap();
    let path = e.cfg_path.join(&project.key).join("toz.db");
    let store = toz_core::store::Store::open(&path).unwrap();
    store
        .conn()
        .execute(
            "UPDATE captures SET label = ?1, source = ?1, source_key = ?1 WHERE handle = ?2",
            [label, handle.as_str()],
        )
        .unwrap();
    drop(store);

    toz(&e).arg("migrate-metadata").assert().success();
    let store = toz_core::store::Store::open_readonly(&path).unwrap();
    let row = store.get_by_handle(&handle).unwrap().unwrap();
    assert!(!row.label.contains("vault-123"));
    assert!(!row.source.contains("vault-123"));
    let key: String = store
        .conn()
        .query_row(
            "SELECT source_key FROM captures WHERE handle = ?1",
            [&handle],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(key.len(), 64);
    drop(store);
    toz(&e)
        .args(["query", "--handle", &handle])
        .assert()
        .success()
        .stdout(predicate::str::contains("original body"));
    toz(&e).arg("migrate-metadata").assert().success();

    let newer = capture_text(&e, label, "new body\n".into());
    let store = toz_core::store::Store::open_readonly(&path).unwrap();
    let original = store.get_by_handle(&handle).unwrap().unwrap();
    let current = store.get_by_handle(&newer).unwrap().unwrap();
    assert_eq!(original.superseded_by, Some(current.id));
}

#[test]
fn fetch_messages_hide_url_credentials_and_query_values() {
    let e = env();
    let output = toz(&e)
        .args([
            "fetch",
            "https://alice:pass@bad host/a?token=secret-one",
            "https://bob:pass@bad host/b?token=secret-two",
        ])
        .output()
        .unwrap();
    assert!(!output.status.success());
    let text = String::from_utf8_lossy(&output.stdout);
    for secret in ["alice", "bob", "pass", "secret-one", "secret-two"] {
        assert!(!text.contains(secret), "{text}");
    }
}

#[test]
fn fetch_persists_completed_pages_while_preserving_input_order() {
    use std::io::{Read, Write};
    use std::process::Stdio;
    use std::sync::mpsc;

    fn respond(mut stream: std::net::TcpStream, status: &str, body: &str) {
        write!(
            stream,
            "HTTP/1.1 {status}\r\nContent-Type: text/plain\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
        .unwrap();
    }

    let e = env();
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let (slow_started_tx, slow_started_rx) = mpsc::channel();
    let (release_slow_tx, release_slow_rx) = mpsc::channel();
    let server = std::thread::spawn(move || {
        let mut slow_release = Some(release_slow_rx);
        let mut handlers = Vec::new();
        for _ in 0..3 {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0u8; 2048];
            let count = stream.read(&mut request).unwrap();
            let request = String::from_utf8_lossy(&request[..count]);
            if request.contains("GET /slow ") {
                slow_started_tx.send(()).unwrap();
                let release = slow_release.take().unwrap();
                handlers.push(std::thread::spawn(move || {
                    release
                        .recv_timeout(std::time::Duration::from_secs(5))
                        .expect("test releases slow fetch");
                    respond(stream, "200 OK", "slow page");
                }));
            } else if request.contains("GET /fast ") {
                respond(stream, "200 OK", "fast page");
            } else if request.contains("GET /fail ") {
                respond(stream, "503 Service Unavailable", "unavailable");
            } else {
                panic!("unexpected fetch request: {request}");
            }
        }
        for handler in handlers {
            handler.join().unwrap();
        }
    });

    let slow = format!("http://127.0.0.1:{port}/slow");
    let fast = format!("http://127.0.0.1:{port}/fast");
    let fail = format!("http://127.0.0.1:{port}/fail");
    let child = std::process::Command::new(env!("CARGO_BIN_EXE_varde-toz"))
        .env("TOZ_CONFIG_DIR", &e.cfg_path)
        .env("VARDE_CONFIG_DIR", &e.varde_cfg_path)
        .env_remove("TOZ_THRESHOLD")
        .env_remove("TOZ_SESSION")
        .env_remove("TOZ_FALLBACK_DIR")
        .current_dir(e.project.path())
        .args(["fetch", "--concurrency", "2", &slow, &fast, &fail])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();

    assert!(slow_started_rx
        .recv_timeout(std::time::Duration::from_secs(5))
        .is_ok());
    let project = toz_core::Project::resolve(Some(e.project.path())).unwrap();
    let database = e.cfg_path.join(project.key).join("toz.db");
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
    let mut fast_persisted_while_slow = false;
    while std::time::Instant::now() < deadline {
        if let Ok(store) = toz_core::Store::open_readonly(&database) {
            fast_persisted_while_slow = store
                .list(10, false)
                .is_ok_and(|rows| rows.iter().any(|row| row.source == fast));
            if fast_persisted_while_slow {
                break;
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    release_slow_tx.send(()).unwrap();
    let output = child.wait_with_output().unwrap();
    server.join().unwrap();

    assert!(
        fast_persisted_while_slow,
        "fast response waited for slow URL"
    );
    assert_eq!(output.status.code(), Some(1));
    let stdout = String::from_utf8_lossy(&output.stdout);
    let slow_position = stdout.find(&slow).unwrap();
    let fast_position = stdout.find(&fast).unwrap();
    let fail_position = stdout.find(&fail).unwrap();
    assert!(slow_position < fast_position && fast_position < fail_position);
    assert!(stdout.contains(&format!("fetch failed for {fail}")));
}

#[test]
fn fetch_cache_reuses_capture_with_private_project_identity() {
    use std::io::{Read, Write};

    let e = env();
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = std::thread::spawn(move || {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        let mut stream = loop {
            match listener.accept() {
                Ok((stream, _)) => break stream,
                Err(error)
                    if error.kind() == std::io::ErrorKind::WouldBlock
                        && std::time::Instant::now() < deadline =>
                {
                    std::thread::sleep(std::time::Duration::from_millis(10));
                }
                Err(error) => panic!("fetch server did not receive request: {error}"),
            }
        };
        let mut request = [0u8; 2048];
        stream.read(&mut request).unwrap();
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 11\r\nConnection: close\r\n\r\nhello world")
            .unwrap();
    });
    let url = format!("http://127.0.0.1:{port}/docs?token=opaque-value");
    let first = toz(&e).args(["fetch", &url]).output().unwrap();
    server.join().unwrap();
    assert!(
        first.status.success(),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&first.stdout),
        String::from_utf8_lossy(&first.stderr)
    );
    let second = toz(&e).args(["fetch", &url]).output().unwrap();
    assert!(
        second.status.success(),
        "{}",
        String::from_utf8_lossy(&second.stderr)
    );
    let output = String::from_utf8_lossy(&second.stdout);
    assert!(output.contains("cached"), "{output}");
    assert!(!output.contains("opaque-value"));
    let cache = std::fs::read_dir(e.cfg_path.join("cache")).unwrap();
    for entry in cache {
        let bytes = std::fs::read(entry.unwrap().path()).unwrap();
        assert!(!String::from_utf8_lossy(&bytes).contains("opaque-value"));
        assert!(!String::from_utf8_lossy(&bytes).contains(
            &toz_core::project::Project::resolve(Some(e.project.path()))
                .unwrap()
                .key
        ));
    }
}

#[test]
fn index_path_errors_hide_configured_secrets() {
    let e = env();
    std::fs::write(
        e.cfg_path.join("config.toml"),
        "[redact]\npatterns = ['vault-[0-9]+']\n",
    )
    .unwrap();
    let path = e.project.path().join("vault-123.txt");
    let output = toz(&e).arg("index").arg(&path).output().unwrap();
    assert!(!output.status.success());
    assert!(!String::from_utf8_lossy(&output.stderr).contains("vault-123"));
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
    let value = serde_json::from_slice::<serde_json::Value>(&output.stdout).ok();
    let Some(handle) = value
        .as_ref()
        .and_then(|value| {
            value["handle"]
                .as_str()
                .filter(|_| value["preview"].is_string())
        })
        .map(str::to_owned)
    else {
        return (String::new(), String::from_utf8(output.stdout).unwrap());
    };
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
fn query_readback_reduces_net_stats_savings() {
    let e = env();
    let handle = capture_text(&e, "readback", "one\ntwo\nthree\n".repeat(200));
    let before: serde_json::Value =
        serde_json::from_slice(&toz(&e).args(["stats", "--json"]).output().unwrap().stdout)
            .unwrap();
    let before = &before[0];

    let first = toz(&e)
        .args(["query", "--handle", &handle, "--lines", "2:2"])
        .output()
        .unwrap();
    assert!(first.status.success());
    let second = toz(&e)
        .args(["query", "--handle", &handle, "--lines", "2:2"])
        .output()
        .unwrap();
    assert!(second.status.success());

    let after: serde_json::Value =
        serde_json::from_slice(&toz(&e).args(["stats", "--json"]).output().unwrap().stdout)
            .unwrap();
    let after = &after[0];
    let readback = (first.stdout.len() + second.stdout.len()) as i64;
    assert_eq!(after["captures"], before["captures"]);
    assert_eq!(after["bytes_in"], before["bytes_in"]);
    assert_eq!(after["bytes_out"], before["bytes_out"]);
    assert_eq!(after["queries"], 2);
    assert_eq!(after["query_bytes"], readback);
    assert_eq!(
        after["net_saved_bytes"],
        before["bytes_in"].as_i64().unwrap() - before["bytes_out"].as_i64().unwrap() - readback
    );
}

#[test]
fn capture_kind_named_query_is_still_counted_as_capture() {
    let e = env();
    toz(&e)
        .args(["capture", "--force", "--kind", "query:custom"])
        .write_stdin("capture data\n".repeat(100))
        .assert()
        .success();
    let stats: serde_json::Value =
        serde_json::from_slice(&toz(&e).args(["stats", "--json"]).output().unwrap().stdout)
            .unwrap();
    let stats = &stats[0];
    assert_eq!(stats["captures"], 1);
    assert_eq!(stats["queries"], 0);
    assert_eq!(stats["by_kind"][0]["kind"], "query:custom");
}

#[test]
fn query_events_record_filters_results_and_retrieval_without_search_text() {
    let e = env();
    let handle = capture_text(&e, "telemetry", "alpha beta\n".repeat(100));
    toz(&e)
        .args([
            "query",
            "alpha beta",
            "--handle",
            &handle,
            "--source",
            "telemetry",
            "--type",
            "prose",
            "--limit",
            "2",
            "--all",
        ])
        .assert()
        .success();
    toz(&e)
        .args(["query", "--handle", &handle, "--chunk", "0"])
        .assert()
        .success();
    let output = toz(&e)
        .args(["stats", "--events", "10", "--json"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let stats: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let events = stats[0]["events"].as_array().unwrap();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0]["kind"], "chunk");
    assert_eq!(events[0]["details"]["chunk"], 0);
    assert_eq!(events[1]["kind"], "search");
    assert_eq!(events[1]["details"]["source_filter"], true);
    assert_eq!(events[1]["details"]["content_type"], "prose");
    assert_eq!(events[1]["details"]["limit"], 2);
    assert_eq!(events[1]["details"]["all"], true);
    assert_eq!(events[1]["details"]["query_count"], 1);
    assert!(events[1]["details"]["hit_count"].as_u64().unwrap() > 0);
    assert_eq!(events[1]["details"]["handle"], handle);
    assert!(events[1]["details"]["result_ids"]
        .as_array()
        .unwrap()
        .iter()
        .any(|id| id["handle"] == handle && id["project"].as_str().is_some()));
    let stored = serde_json::to_string(events).unwrap();
    assert!(!stored.contains("alpha beta"));
    assert!(!stored.contains("telemetry"));
}

#[test]
fn query_events_link_repeated_attempts_to_one_handle_without_inflating_savings() {
    let e = env();
    let handle = capture_text(&e, "attempts", "one\ntwo\n".repeat(100));
    toz(&e)
        .env("TOZ_SESSION", "attempt-session")
        .args(["query", "--handle", &handle, "--chunk", "999"])
        .assert()
        .failure();
    let first = toz(&e)
        .env("TOZ_SESSION", "attempt-session")
        .args(["query", "--handle", &handle, "--chunk", "0"])
        .output()
        .unwrap();
    let second = toz(&e)
        .env("TOZ_SESSION", "attempt-session")
        .args(["query", "--handle", &handle, "--chunk", "0"])
        .output()
        .unwrap();
    assert!(first.status.success() && second.status.success());
    toz(&e)
        .env("TOZ_SESSION", "another-session")
        .args(["query", "--handle", &handle, "--lines", "1:1"])
        .assert()
        .success();

    let output = toz(&e)
        .env("TOZ_SESSION", "attempt-session")
        .args(["stats", "--session", "--events", "3", "--json"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let stats: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let stats = &stats[0];
    let events = stats["events"].as_array().unwrap();
    assert_eq!(events.len(), 3);
    assert!(events
        .iter()
        .all(|event| event["details"]["handle"] == handle));
    assert_eq!(events[0]["outcome"], "ok");
    assert_eq!(events[1]["outcome"], "ok");
    assert_eq!(events[2]["outcome"], "invalid_selection");
    assert_eq!(stats["queries"], 2);
    assert_eq!(
        stats["query_bytes"],
        (first.stdout.len() + second.stdout.len()) as i64
    );
    let bounded: serde_json::Value = serde_json::from_slice(
        &toz(&e)
            .args(["stats", "--events", "1", "--json"])
            .output()
            .unwrap()
            .stdout,
    )
    .unwrap();
    assert_eq!(bounded[0]["events"].as_array().unwrap().len(), 1);
    toz(&e)
        .args(["stats", "--events", "10001"])
        .assert()
        .failure()
        .stderr(predicate::str::contains("between 1 and 10000"));
}

#[test]
fn empty_store_queries_keep_their_output_and_outcome() {
    let e = env();
    for _ in 0..2 {
        toz(&e)
            .args(["query", "missing term"])
            .assert()
            .success()
            .stdout("varde-toz: no captures yet for this project\n");
        toz(&e)
            .args(["query", "--list", "--json"])
            .assert()
            .success()
            .stdout("[]\n");
    }
    let stats: serde_json::Value = serde_json::from_slice(
        &toz(&e)
            .args(["stats", "--events", "10", "--json"])
            .output()
            .unwrap()
            .stdout,
    )
    .unwrap();
    assert_eq!(stats[0]["events"].as_array().unwrap().len(), 4);
    assert!(stats[0]["events"]
        .as_array()
        .unwrap()
        .iter()
        .all(|event| event["outcome"] == "no_store"));
}

#[test]
fn global_search_events_qualify_result_handles_with_project() {
    let e = env();
    let other = TempDir::new().unwrap();
    capture_text(&e, "one", "global marker\n".repeat(100));
    toz(&e)
        .current_dir(other.path())
        .args(["capture", "--force", "--label", "two"])
        .write_stdin("global marker\n".repeat(100))
        .assert()
        .success();
    toz(&e)
        .args(["query", "global marker", "--global"])
        .assert()
        .success();
    let stats: serde_json::Value = serde_json::from_slice(
        &toz(&e)
            .args(["stats", "--events", "1", "--json"])
            .output()
            .unwrap()
            .stdout,
    )
    .unwrap();
    let ids = stats[0]["events"][0]["details"]["result_ids"]
        .as_array()
        .unwrap();
    assert_eq!(ids.len(), 2);
    assert_ne!(ids[0]["project"], ids[1]["project"]);
    assert!(ids.iter().all(|id| id["handle"].as_str().is_some()));
}

#[test]
fn query_stats_count_each_output_mode_and_keep_capture_totals_separate() {
    let e = env();
    let handle = capture_text(&e, "query-modes", "alpha\nbeta\n".repeat(100));
    let cases = [
        (vec!["query", "--handle", &handle, "--chunk", "0"], "chunk"),
        (
            vec!["query", "--handle", &handle, "--lines", "1:1"],
            "lines",
        ),
        (vec!["query", "--handle", &handle, "alpha"], "search"),
        (vec!["query", "--list", "--json"], "list"),
        (
            vec!["query", "--handle", &handle, "--records", "missing"],
            "records",
        ),
    ];
    let mut expected = 0;
    for (args, _) in &cases {
        let output = toz(&e).args(args).output().unwrap();
        assert!(output.status.success());
        expected += output.stdout.len() as i64;
    }
    toz(&e)
        .args(["query", "--handle", &handle, "--chunk", "999"])
        .assert()
        .failure();

    let stats: serde_json::Value =
        serde_json::from_slice(&toz(&e).args(["stats", "--json"]).output().unwrap().stdout)
            .unwrap();
    let stats = &stats[0];
    assert_eq!(stats["captures"], 1);
    assert_eq!(stats["queries"], cases.len());
    assert_eq!(stats["query_bytes"], expected);
    assert_eq!(stats["by_kind"].as_array().unwrap().len(), 1);
    let kinds: Vec<&str> = stats["by_query_kind"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row["kind"].as_str().unwrap())
        .collect();
    for (_, kind) in &cases {
        assert!(kinds.contains(kind));
    }
}

#[test]
fn query_stats_session_filter_and_negative_net_savings() {
    let e = env();
    let handle = capture_text(&e, "session-query", "short\n".repeat(80));
    for _ in 0..3 {
        toz(&e)
            .env("TOZ_SESSION", "query-session")
            .args(["query", "--handle", &handle])
            .assert()
            .success();
    }
    let stats: serde_json::Value = serde_json::from_slice(
        &toz(&e)
            .env("TOZ_SESSION", "query-session")
            .args(["stats", "--session", "--json"])
            .output()
            .unwrap()
            .stdout,
    )
    .unwrap();
    let stats = &stats[0];
    assert_eq!(stats["captures"], 0);
    assert_eq!(stats["queries"], 3);
    assert!(stats["net_saved_bytes"].as_i64().unwrap() < 0);
    assert!(stats["tokens_saved_estimate"].as_i64().unwrap() < 0);
}

#[test]
fn query_handle_readback_is_charged_to_capture_project() {
    let e = env();
    let source_project = TempDir::new().unwrap();
    let captured = toz(&e)
        .current_dir(source_project.path())
        .args(["capture", "--force", "--label", "other-project"])
        .write_stdin("cross-project data\n".repeat(100))
        .output()
        .unwrap();
    assert!(captured.status.success());
    let preview = String::from_utf8(captured.stdout).unwrap();
    let handle = preview
        .split("handle ")
        .nth(1)
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap();

    let readback = toz(&e)
        .args(["query", "--handle", handle, "--lines", "1:1"])
        .output()
        .unwrap();
    assert!(readback.status.success());
    let source_stats: serde_json::Value = serde_json::from_slice(
        &toz(&e)
            .current_dir(source_project.path())
            .args(["stats", "--json"])
            .output()
            .unwrap()
            .stdout,
    )
    .unwrap();
    assert_eq!(source_stats[0]["queries"], 1);
    assert_eq!(source_stats[0]["query_bytes"], readback.stdout.len());
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
fn large_capture_stdin_below_threshold_passes_through_byte_for_byte() {
    let e = env();
    let body = "p".repeat(8 * 1024 * 1024);
    toz(&e)
        .args(["capture", "--threshold", "16777216"])
        .write_stdin(body.clone())
        .assert()
        .success()
        .stdout(body);
}

#[test]
fn large_accepted_capture_preserves_stored_bytes() {
    let e = env();
    let mut expected: String = (0..200_000)
        .map(|i| format!("capture-row-{i:06}\n"))
        .collect();
    expected.pop();
    let handle = capture_text(&e, "streamed", expected.clone());
    let project = toz_core::Project::resolve(Some(e.project.path())).unwrap();
    let store =
        toz_core::Store::open_readonly(&e.cfg_path.join(project.key).join("toz.db")).unwrap();
    let capture = store.get_by_handle(&handle).unwrap().unwrap();
    let stored = store.full_text(capture.id, "stdout").unwrap();
    assert_eq!(stored.as_bytes(), expected.as_bytes());
}

#[test]
fn oversized_profile_matched_capture_reports_its_input_limit() {
    const MAX_PROFILE_CAPTURE_BYTES: usize = 8 * 1024 * 1024;

    let e = env();
    write_user_profile(
        &e.varde_cfg_path,
        r#"
[[profile]]
id = "bounded-profile"
match = { source = "large-profiled-capture" }
script = "print('profile ran')"
"#,
    );
    let body = vec![b'x'; MAX_PROFILE_CAPTURE_BYTES + 1];
    toz(&e)
        .args(["capture", "--source", "large-profiled-capture", "--force"])
        .write_stdin(body)
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "profile-matched capture exceeds the 8388608-byte limit",
        ));
}

#[test]
fn oversized_hook_payload_is_skipped_with_full_byte_count() {
    const MAX_HOOK_PAYLOAD_BYTES: usize = 8 * 1024 * 1024;

    let e = env();
    let bytes = MAX_HOOK_PAYLOAD_BYTES + 1;
    toz(&e)
        .args(["capture", "--hook"])
        .write_stdin(vec![b'x'; bytes])
        .assert()
        .success()
        .stdout("")
        .stderr("");

    let line = std::fs::read_to_string(e.cfg_path.join("diagnostics.jsonl")).unwrap();
    let event: serde_json::Value = serde_json::from_str(line.trim()).unwrap();
    assert_eq!(event["outcome"], "failed");
    assert_eq!(event["reason"], "invalid-payload");
    assert_eq!(event["bytes"], bytes);
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

    let block = toz(&e).args(["note", "--block"]).output().unwrap();
    assert!(block.status.success());
    let block = String::from_utf8(block.stdout).unwrap();
    assert!(!block.contains("hook failure(s)"));
    assert!(!block.contains("diagnostics are unavailable"));
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
        .env_remove("VARDE_TOZ_CONFIG_DIR")
        .env_remove("TOZ_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
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
        .env_remove("VARDE_TOZ_CONFIG_DIR")
        .env_remove("TOZ_CONFIG_DIR")
        .env_remove("XDG_CONFIG_HOME")
        .env("TOZ_FALLBACK_DIR", fallback.path())
        .args(["note", "--harness", "codex"])
        .assert()
        .success()
        .stdout(predicate::str::contains("1 hook failure(s)"));
}

#[test]
fn note_never_instructs_agents_to_use_fallback_by_default() {
    let fallback = TempDir::new().unwrap();
    let output = Command::cargo_bin("varde-toz")
        .unwrap()
        .env("VARDE_TOZ_FALLBACK_DIR", fallback.path())
        .env_remove("TOZ_FALLBACK_DIR")
        .args([
            "--fallback-dir",
            fallback.path().to_str().unwrap(),
            "note",
            "--harness",
            "claude-code",
        ])
        .output()
        .unwrap();
    assert!(output.status.success());
    let note: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let note = note["hookSpecificOutput"]["additionalContext"]
        .as_str()
        .unwrap();
    assert!(note.contains("varde-toz query --handle"));
    assert!(!note.contains("VARDE_TOZ_FALLBACK_DIR="));
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
    toz(&e)
        .args(["capture", "--hook", "--harness", "codex"])
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
fn hook_structured_mcp_round_trip_and_replacement_contracts() {
    let e = env();
    let structured = serde_json::json!({
        "values": (0..=3000).collect::<Vec<usize>>(),
        "metadata": {"complete": true, "count": 3001}
    });
    let image = serde_json::json!({
        "type": "image", "data": "image-block-secret-base64", "mimeType": "image/png"
    });
    let resource = serde_json::json!({
        "type": "resource_link", "name": "report", "uri": "file:///report.pdf"
    });

    for harness in ["codex", "claude-code"] {
        for short_text in [Some("short notes"), None] {
            let tool_response = if let Some(text) = short_text {
                serde_json::json!({
                    "content": [
                        image.clone(),
                        {"type": "text", "text": text},
                        resource.clone(),
                        {"type": "text", "text": "more"}
                    ],
                    "structuredContent": structured.clone()
                })
            } else {
                serde_json::json!({"structuredContent": structured.clone()})
            };
            let payload = serde_json::json!({
                "tool_name": "StructuredTool", "tool_input": {}, "tool_response": tool_response
            });
            let out = toz(&e)
                .args(["capture", "--hook", "--harness", harness])
                .write_stdin(payload.to_string())
                .output()
                .unwrap();
            assert!(out.status.success());
            let feedback: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
            let hook = &feedback["hookSpecificOutput"];
            assert_eq!(hook["hookEventName"], "PostToolUse");
            assert!(feedback.get("decision").is_none());
            assert!(feedback.get("continue").is_none());

            let preview = if harness == "claude-code" && short_text.is_some() {
                let updated = &hook["updatedToolOutput"];
                assert_eq!(updated["structuredContent"], structured);
                let content = updated["content"].as_array().unwrap();
                assert_eq!(content.len(), 3);
                assert_eq!(content[0], image);
                assert_eq!(content[2], resource);
                content[1]["text"].as_str().unwrap()
            } else {
                assert!(hook.get("updatedToolOutput").is_none());
                assert!(hook.get("updatedMCPToolOutput").is_none());
                hook["additionalContext"].as_str().unwrap()
            };
            let handle = handle_from_preview(preview);
            let archived = toz(&e)
                .args(["query", "--handle", &handle])
                .output()
                .unwrap();
            assert!(archived.status.success());
            let envelope: serde_json::Value = serde_json::from_slice(&archived.stdout).unwrap();
            assert_eq!(
                envelope["contentText"],
                short_text.map(|_| "short notes\nmore").unwrap_or("")
            );
            assert_eq!(envelope["structuredContent"], structured);
            assert_eq!(envelope.as_object().unwrap().len(), 2);
            assert!(!envelope.to_string().contains("image-block-secret-base64"));
        }
    }
}

#[test]
fn hook_retained_output_is_recoverable_when_summary_omits_handle() {
    let full = format!(
        "{}middle-recovery-sentinel\n{}tail-recovery-sentinel\n",
        "before\n".repeat(12_000),
        "after\n".repeat(12_000)
    );
    for (harness, persisted) in [
        ("claude-code", true),
        ("codex", true),
        ("pi", false),
        ("opencode", false),
    ] {
        let e = env();
        let source = format!("generate-retained-{harness}");
        let response = if persisted {
            let full_path = e.project.path().join("full-output.txt");
            std::fs::write(&full_path, &full).unwrap();
            serde_json::json!({"stdout": "tiny clipped output", "stderr": "", "exit_code": 0, "persistedOutputPath": full_path})
        } else {
            serde_json::json!(full)
        };
        let payload = serde_json::json!({"tool_name": "Bash", "tool_input": {"command": source}, "tool_response": response});
        // Discard all hook feedback, as a native script may omit it from its final summary.
        toz(&e)
            .args(["capture", "--hook", "--harness", harness])
            .write_stdin(payload.to_string())
            .assert()
            .success();
        let listed = toz(&e)
            .args(["query", "--list", "--limit", "5", "--json"])
            .output()
            .unwrap();
        assert!(
            listed.status.success(),
            "{harness}: {}",
            String::from_utf8_lossy(&listed.stderr)
        );
        let rows: serde_json::Value = serde_json::from_slice(&listed.stdout).unwrap();
        let rows = rows.as_array().unwrap();
        assert_eq!(
            rows.len(),
            1,
            "{harness} retains exactly one result without rerunning"
        );
        assert_eq!(rows[0]["source"], source);
        let handle = rows[0]["handle"].as_str().unwrap();
        let archived = toz(&e)
            .args(["query", "--handle", handle])
            .output()
            .unwrap();
        assert!(archived.status.success());
        assert_eq!(
            String::from_utf8(archived.stdout).unwrap(),
            full,
            "{harness} retains middle/tail and exact length"
        );
        toz(&e)
            .args(["query", "middle-recovery-sentinel", "--source", &source])
            .assert()
            .success()
            .stdout(predicate::str::contains("middle-recovery-sentinel"));
    }
}

#[test]
fn hook_codex_stream_completion_and_unfinished_stream_contract_stays_unchanged() {
    let e = env();
    let big: String = (1..=2000).map(|i| format!("line {i} ")).collect();
    let completed = serde_json::json!({
        "tool_name": "Bash", "tool_input": {"command": "printf output"},
        "tool_response": {"stdout": big, "stderr": "", "exit_code": 0}
    });
    let out = toz(&e)
        .args(["capture", "--hook", "--harness", "codex"])
        .write_stdin(completed.to_string())
        .output()
        .unwrap();
    assert!(out.status.success());
    let feedback: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(feedback["continue"], false);
    assert!(feedback.get("decision").is_none());
    assert!(feedback["hookSpecificOutput"]["additionalContext"].is_string());
    assert!(feedback["hookSpecificOutput"]
        .get("updatedToolOutput")
        .is_none());
    assert!(feedback["hookSpecificOutput"]
        .get("updatedMCPToolOutput")
        .is_none());

    let unfinished = serde_json::json!({
        "tool_name": "Bash", "tool_input": {"command": "printf output"},
        "tool_response": {"stdout": big, "stderr": "", "exit_code": null, "session_id": "live"}
    });
    toz(&e)
        .args(["capture", "--hook", "--harness", "codex"])
        .write_stdin(unfinished.to_string())
        .assert()
        .success()
        .stdout("");
}

#[test]
fn hook_codex_plain_string_feedback_is_bounded_and_round_trips_with_redaction() {
    const OUTPUT_BYTES: usize = 21_567;
    const SECRET: &str = "CODEX_SECRET_12345";
    let mut text = format!("{SECRET}\n{}", "output line\n".repeat(2_000));
    text.truncate(OUTPUT_BYTES - 1);
    text.push('\n');
    assert_eq!(text.len(), OUTPUT_BYTES);

    for redact in [false, true] {
        let e = env();
        if redact {
            std::fs::write(
                e.cfg_path.join("config.toml"),
                "[redact]\npatterns = ['CODEX_SECRET_[0-9]+']\n",
            )
            .unwrap();
        }
        let payload = serde_json::json!({
            "tool_name": "Bash",
            "tool_input": {"command": "printf synthetic-output"},
            "tool_response": text
        });
        let out = toz(&e)
            .args(["capture", "--hook", "--harness", "codex"])
            .write_stdin(payload.to_string())
            .output()
            .unwrap();
        assert!(out.status.success());
        assert!(out.stdout.len() < 4096);
        let feedback: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(feedback["continue"], false);
        assert!(feedback.get("decision").is_none());

        let hook = &feedback["hookSpecificOutput"];
        let stop_reason = feedback["stopReason"].as_str().unwrap();
        let additional_context = hook["additionalContext"].as_str().unwrap();
        let handle = handle_from_preview(stop_reason);
        assert!(stop_reason.starts_with("varde-toz: captured"));
        assert!(additional_context.starts_with("varde-toz: stored this output as handle"));
        assert!(additional_context.contains(&handle));
        assert!(!additional_context.contains("output line"));
        if redact {
            assert!(!stop_reason.contains(SECRET));
            assert!(stop_reason.contains("[redacted:user]"));
        }

        let archived = toz(&e)
            .args(["query", "--handle", &handle])
            .output()
            .unwrap();
        assert!(archived.status.success());
        let expected = if redact {
            text.replace(SECRET, "[redacted:user]")
        } else {
            text.clone()
        };
        assert_eq!(String::from_utf8(archived.stdout).unwrap(), expected);
    }
}

#[test]
fn hook_codex_small_plain_strings_and_toz_commands_stay_untouched() {
    let e = env();
    let small = serde_json::json!({
        "tool_name": "Bash",
        "tool_input": {"command": "printf short"},
        "tool_response": "short output"
    });
    toz(&e)
        .args(["capture", "--hook", "--harness", "codex"])
        .write_stdin(small.to_string())
        .assert()
        .success()
        .stdout("");

    let large = "own Toz command output\n".repeat(500);
    let recursive = serde_json::json!({
        "tool_name": "Bash",
        "tool_input": {"command": "varde-toz query --handle existing"},
        "tool_response": large
    });
    toz(&e)
        .args(["capture", "--hook", "--harness", "codex"])
        .write_stdin(recursive.to_string())
        .assert()
        .success()
        .stdout("");
}

#[test]
fn hook_small_and_null_structured_values_keep_existing_behavior() {
    let e = env();
    let small = serde_json::json!({
        "tool_name": "StructuredTool", "tool_input": {},
        "tool_response": {
            "content": [{"type": "text", "text": "short"}],
            "structuredContent": {"count": 1}
        }
    });
    for harness in ["codex", "claude-code"] {
        toz(&e)
            .args(["capture", "--hook", "--harness", harness])
            .write_stdin(small.to_string())
            .assert()
            .success()
            .stdout("");
    }

    let text = "ordinary content\n".repeat(500);
    let null_structured = serde_json::json!({
        "tool_name": "ExampleTool", "tool_input": {},
        "tool_response": {
            "content": [{"type": "text", "text": text}], "structuredContent": null
        }
    });
    for harness in ["codex", "claude-code"] {
        let out = toz(&e)
            .args(["capture", "--hook", "--harness", harness])
            .write_stdin(null_structured.to_string())
            .output()
            .unwrap();
        assert!(out.status.success());
        let feedback: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        let hook = &feedback["hookSpecificOutput"];
        let preview = if harness == "codex" {
            assert!(feedback.get("decision").is_none());
            assert!(feedback.get("continue").is_none());
            assert!(hook.get("updatedToolOutput").is_none());
            hook["additionalContext"].as_str().unwrap()
        } else {
            let updated = &hook["updatedToolOutput"];
            assert_eq!(updated["structuredContent"], serde_json::Value::Null);
            updated["content"][0]["text"].as_str().unwrap()
        };
        let handle = handle_from_preview(preview);
        let archived = toz(&e)
            .args(["query", "--handle", &handle])
            .output()
            .unwrap();
        assert!(archived.status.success());
        assert_eq!(String::from_utf8(archived.stdout).unwrap(), text);
    }
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
fn hook_skips_toz_only_shell_invocations_across_harnesses() {
    let sources = [
        "toz query --handle abcd",
        "varde-toz query --handle abcd",
        "toz doctor --json",
        "varde-toz run --code 'print(1)'",
        "'/usr/local/bin/toz' query --handle abcd",
        "\"/usr/local/bin/varde-toz\" query --handle abcd",
        "cd /tmp && varde-toz query --handle abcd",
        "cd /tmp; /usr/local/bin/toz query --handle abcd",
        "env FLAG=1 varde-toz query --handle abcd",
        "FLAG='some value' varde-toz query --handle abcd",
        "command varde-toz query --handle abcd",
        "FLAG=1 command varde-toz query --handle abcd",
        "exec /usr/local/bin/varde-toz query --handle abcd",
        "toz query --handle one && varde-toz query --handle two",
        "varde-toz query --handle one\ntoz query --handle two",
        "varde-toz query 'literal && | ;'",
    ];

    for harness in ["codex", "claude-code", "pi", "opencode"] {
        let e = env();
        for source in sources {
            let output = hook_shell_output(&e, harness, source);
            assert!(
                output.is_empty(),
                "{harness} should skip Toz-only source {source:?}, got {output:?}"
            );
        }
        let cmd_payload = serde_json::json!({
            "tool_name": "Bash",
            "tool_input": {"command": "", "cmd": "'/usr/local/bin/varde-toz' query --handle abcd"},
            "tool_response": {"stdout": "x".repeat(40_000), "stderr": "", "exit_code": 0}
        });
        assert!(
            hook_stdout(&e, harness, cmd_payload.to_string()).is_empty(),
            "{harness} should classify the cmd field when command is empty"
        );
        let cmd_only_payload = serde_json::json!({
            "tool_name": "Bash",
            "tool_input": {"cmd": "'/usr/local/bin/varde-toz' query --handle abcd"},
            "tool_response": {"stdout": "x".repeat(40_000), "stderr": "", "exit_code": 0}
        });
        assert!(
            hook_stdout(&e, harness, cmd_only_payload.to_string()).is_empty(),
            "{harness} should classify a cmd-only source"
        );
    }
}

#[test]
fn hook_captures_mixed_and_ambiguous_shell_sources_across_harnesses() {
    let sources = [
        "varde-toz query --handle abcd; echo done",
        "echo before && varde-toz query --handle abcd",
        "echo 'varde-toz query --handle abcd'",
        "varde-toz query --handle abcd | cat",
        "varde-toz query --handle abcd > /tmp/result",
        "echo $(varde-toz query --handle abcd)",
        "varde-toz query --handle \"$(echo abcd)\"",
        "'/usr/local/bin/varde-toz-helper' query --handle abcd",
        "node -e \"toz query --handle abcd\"",
        "varde-toz query 'unterminated",
        "cd - && varde-toz query --handle abcd",
        "cd -P /tmp && varde-toz query --handle abcd",
        "env -- varde-toz query --handle abcd",
        "env -i varde-toz query --handle abcd",
        "'FLAG=value' varde-toz query --handle abcd",
        "varde-toz\\ query --handle abcd",
        "varde-toz \\\nquery --handle abcd",
        "varde-toz\u{00a0}-helper query --handle abcd",
        "varde-toz query --handle abcd\necho after",
    ];

    for harness in ["codex", "claude-code", "pi", "opencode"] {
        let e = env();
        for source in sources {
            let output = hook_shell_output(&e, harness, source);
            assert!(
                output.contains("varde-toz: captured"),
                "{harness} should capture ambiguous or mixed source {source:?}, got {output:?}"
            );
        }
        let wrapper = serde_json::json!({
            "tool_name": "Bash",
            "tool_input": {"code": "toz.exec({shell:'varde-toz query --handle abcd'})"},
            "tool_response": {"stdout": "x".repeat(40_000), "stderr": "", "exit_code": 0}
        });
        let output = hook_stdout(&e, harness, wrapper.to_string());
        assert!(
            output.contains("varde-toz: captured"),
            "{harness} should capture a JavaScript wrapper that mentions Toz"
        );
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

    // Explicit ranges use the same read-class threshold as whole-file reads.
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
    assert!(hooks.contains("/varde-toz capture --hook"));
    assert!(!hooks.contains("--fallback-dir"));
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

fn read_class_payload(tool: &str, input: serde_json::Value, bytes: usize) -> String {
    let text = "x".repeat(bytes);
    let response = if tool == "Read" {
        serde_json::json!({"type": "text", "file": {"filePath": "/x/a.rs", "content": text}})
    } else {
        serde_json::json!({"stdout": text, "stderr": "", "exit_code": 0})
    };
    serde_json::json!({"tool_name": tool, "tool_input": input, "tool_response": response})
        .to_string()
}

fn hook_stdout(e: &Env, harness: &str, payload: String) -> String {
    let out = toz(e)
        .args(["capture", "--hook", "--harness", harness])
        .write_stdin(payload)
        .output()
        .unwrap();
    assert!(out.status.success());
    String::from_utf8(out.stdout).unwrap()
}

fn hook_shell_output(e: &Env, harness: &str, source: &str) -> String {
    let payload = serde_json::json!({
        "tool_name": "Bash",
        "tool_input": {"command": source},
        "tool_response": {"stdout": "x".repeat(40_000), "stderr": "", "exit_code": 0}
    });
    hook_stdout(e, harness, payload.to_string())
}

#[test]
fn read_class_passes_through_up_to_16_kib() {
    let e = env();
    let cases = [
        (
            "claude-code",
            "Read",
            serde_json::json!({"file_path": "/x/a.rs"}),
        ),
        (
            "opencode",
            "read",
            serde_json::json!({"filePath": "/x/a.rs"}),
        ),
        (
            "codex",
            "Bash",
            serde_json::json!({"command": "sed -n 1,400p f"}),
        ),
        ("codex", "Bash", serde_json::json!({"cmd": "cat f"})),
        (
            "claude-code",
            "Bash",
            serde_json::json!({"command": "head -n 50 f"}),
        ),
    ];
    for (harness, tool, input) in cases {
        let payload = read_class_payload(tool, input, 10_000);
        assert_eq!(hook_stdout(&e, harness, payload), "", "{harness} {tool}");
    }
}

#[test]
fn shell_command_outside_read_class_is_captured_at_default_threshold() {
    let e = env();
    for command in [
        "cat f | grep x",
        "cat f > g",
        "sed 1,4p f",
        "ls",
        "cat f; ls",
        "cat f & ls",
    ] {
        let payload = read_class_payload("Bash", serde_json::json!({"command": command}), 10_000);
        assert_ne!(hook_stdout(&e, "codex", payload), "", "{command}");
    }
}

#[test]
fn read_threshold_key_overrides_read_class_default() {
    let e = env();
    std::fs::write(
        e.cfg_path.join("config.toml"),
        "[thresholds]\nread = 2048\n",
    )
    .unwrap();
    let payload = read_class_payload("Read", serde_json::json!({"file_path": "/x/a.rs"}), 3000);
    assert_ne!(hook_stdout(&e, "claude-code", payload), "");
}

#[test]
fn exact_tool_threshold_wins_over_read_key() {
    let e = env();
    std::fs::write(
        e.cfg_path.join("config.toml"),
        "[thresholds]\nread = 100000\nRead = 1024\n",
    )
    .unwrap();
    let payload = read_class_payload("Read", serde_json::json!({"file_path": "/x/a.rs"}), 3000);
    assert_ne!(hook_stdout(&e, "claude-code", payload), "");
}

#[test]
fn higher_global_threshold_applies_to_read_class() {
    let e = env();
    std::fs::write(e.cfg_path.join("config.toml"), "threshold = 32768\n").unwrap();
    let payload = read_class_payload("Read", serde_json::json!({"file_path": "/x/a.rs"}), 20_000);
    assert_eq!(hook_stdout(&e, "claude-code", payload), "");
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
    let mut text = String::from(
        "running 3 tests\ntest alpha ... ok\ntest beta ... FAILED\ntest gamma ... ok\n\nfailures:\n\n---- beta stdout ----\n",
    );
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

    // Codex: merges into hooks.json and leaves AGENTS.md alone, idempotently.
    let cx = root.join("codex-home");
    std::fs::create_dir_all(&cx).unwrap();
    std::fs::write(
        cx.join("hooks.json"),
        r#"{"hooks":{"PostToolUse":[{"hooks":[{"type":"command","command":"/x/other.sh"}]}]}}"#,
    )
    .unwrap();
    let original_agents = "# My rules\n\nBe nice.\n";
    std::fs::write(cx.join("AGENTS.md"), original_agents).unwrap();
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
    assert!(hooks["hooks"].get("SessionStart").is_none());
    assert_eq!(
        std::fs::read_to_string(cx.join("AGENTS.md")).unwrap(),
        original_agents
    );
    assert!(!cx.join("skills/toz").exists());

    let cx_without_agents = root.join("codex-no-agents");
    toz(&e)
        .args([
            "install",
            "codex",
            "--dir",
            cx_without_agents.to_str().unwrap(),
        ])
        .assert()
        .success();
    assert!(!cx_without_agents.join("AGENTS.md").exists());

    // Second install: nothing changes.
    toz(&e)
        .args(["install", "codex", "--dir", cx.to_str().unwrap()])
        .assert()
        .success()
        .stdout(predicate::str::contains("wrote").not());

    let agents_with_legacy_block = format!(
        "{original_agents}\n<!-- varde-toz:start -->\n## varde-toz (tool-output-zone)\nlegacy note\n<!-- varde-toz:end -->\n"
    );
    std::fs::write(cx.join("AGENTS.md"), agents_with_legacy_block).unwrap();

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
        original_agents
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
fn note_block_emits_static_codex_instructions() {
    let e = env();
    let output = toz(&e).args(["note", "--block"]).output().unwrap();
    assert!(output.status.success());
    let block = String::from_utf8(output.stdout).unwrap();
    assert!(block.starts_with("## varde-toz (tool-output-zone)\n"));
    assert!(block.contains("varde-toz (tool-output-zone) is active."));
    assert!(block.contains("read the varde-toz skill"));
    assert!(!block.contains("varde-toz:start"));
    assert!(!block.contains("varde-toz:end"));
    assert!(!block.contains("hook failure(s)"));
    assert!(!block.contains("diagnostics are unavailable"));
}

#[test]
fn install_codex_preserves_empty_and_whitespace_agents_files() {
    let e = env();
    let root = e.project.path();

    for (name, contents) in [("empty", ""), ("whitespace", " \n\t\n")] {
        let cx = root.join(name);
        std::fs::create_dir_all(&cx).unwrap();
        let agents = cx.join("AGENTS.md");
        std::fs::write(&agents, contents).unwrap();

        toz(&e)
            .args(["install", "codex", "--dir", cx.to_str().unwrap()])
            .assert()
            .success();
        assert_eq!(std::fs::read(&agents).unwrap(), contents.as_bytes());

        toz(&e)
            .args(["uninstall", "codex", "--dir", cx.to_str().unwrap()])
            .assert()
            .success();
        assert_eq!(std::fs::read(&agents).unwrap(), contents.as_bytes());
    }
}

#[cfg(unix)]
#[test]
fn install_codex_preserves_whitespace_agents_symlink() {
    let e = env();
    let root = e.project.path();
    let cx = root.join("codex-home");
    let shared = root.join("shared");
    std::fs::create_dir_all(&cx).unwrap();
    std::fs::create_dir_all(&shared).unwrap();

    let target = shared.join("AGENTS.md");
    let link = cx.join("AGENTS.md");
    let contents = " \n\t\n";
    std::fs::write(&target, contents).unwrap();
    std::os::unix::fs::symlink(&target, &link).unwrap();

    toz(&e)
        .args(["install", "codex", "--dir", cx.to_str().unwrap()])
        .assert()
        .success();

    assert!(std::fs::symlink_metadata(&link)
        .unwrap()
        .file_type()
        .is_symlink());
    assert_eq!(std::fs::read(&target).unwrap(), contents.as_bytes());

    toz(&e)
        .args(["uninstall", "codex", "--dir", cx.to_str().unwrap()])
        .assert()
        .success();

    assert!(std::fs::symlink_metadata(&link)
        .unwrap()
        .file_type()
        .is_symlink());
    assert_eq!(std::fs::read(&target).unwrap(), contents.as_bytes());
}

#[cfg(unix)]
#[test]
fn install_codex_strips_legacy_block_through_agents_symlink() {
    let e = env();
    let root = e.project.path();
    let cx = root.join("codex-home");
    let shared = root.join("shared");
    std::fs::create_dir_all(&cx).unwrap();
    std::fs::create_dir_all(&shared).unwrap();

    let target = shared.join("AGENTS.md");
    let link = cx.join("AGENTS.md");
    let prefix = "# User rules  \n\nKeep this sentence.  \n";
    let legacy_block =
        "<!-- varde-toz:start -->\n## old Toz note\nlegacy text\n<!-- varde-toz:end -->";
    let suffix = "\n\nKeep these bytes too.  \n";
    std::fs::write(&target, format!("{prefix}{legacy_block}{suffix}")).unwrap();
    std::os::unix::fs::symlink(&target, &link).unwrap();

    toz(&e)
        .args(["install", "codex", "--dir", cx.to_str().unwrap()])
        .assert()
        .success();

    assert!(std::fs::symlink_metadata(&link)
        .unwrap()
        .file_type()
        .is_symlink());
    assert_eq!(
        std::fs::read_to_string(target).unwrap(),
        "# User rules  \n\nKeep this sentence.  \n\nKeep these bytes too.  \n"
    );
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
fn harness_bundles_use_primary_store_by_default() {
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
            assert!(doc["hooks"].get("SessionStart").is_none());
            let command = doc["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
                .as_str()
                .unwrap();
            assert!(!command.contains("--fallback-dir"));
        } else {
            assert!(!text.contains("TOZ_FALLBACK_DIR: FALLBACK"));
            assert!(!text.contains("{{TOZ_FALLBACK_"));
        }
    }
    assert!(!e.project.path().join(".toz").exists());
}

#[cfg(unix)]
#[test]
fn opted_in_fallback_reads_when_existing_primary_db_is_inaccessible() {
    use std::os::unix::fs::PermissionsExt;

    let e = env();
    let fallback = TempDir::new().unwrap();
    let fallback_capture = toz(&e)
        .env("TOZ_CONFIG_DIR", fallback.path())
        .args(["capture", "--force", "--source", "fallback-test"])
        .write_stdin("fallback only marker\n")
        .output()
        .unwrap();
    assert!(fallback_capture.status.success());
    let text = String::from_utf8_lossy(&fallback_capture.stdout);
    let handle = text
        .split("handle ")
        .nth(1)
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap();

    let primary_capture = toz(&e)
        .args(["capture", "--force", "--source", "primary-test"])
        .write_stdin("primary marker\n")
        .output()
        .unwrap();
    assert!(primary_capture.status.success());
    let project = toz_core::Project::resolve(Some(e.project.path())).unwrap();
    let db = e.cfg_path.join(&project.key).join("toz.db");
    std::fs::set_permissions(&db, std::fs::Permissions::from_mode(0o000)).unwrap();

    toz(&e)
        .args(["query", "--handle", handle])
        .assert()
        .failure();

    let fallback_path = fallback.path().to_str().unwrap();
    for args in [
        vec!["query", "--handle", handle],
        vec!["query", "--list"],
        vec!["query", "fallback only marker"],
    ] {
        let output = toz(&e)
            .args(["--fallback-dir", fallback_path])
            .args(&args)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(
            stdout.contains("fallback only marker") || stdout.contains(handle),
            "args={args:?}, stdout={stdout}"
        );
    }
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

    let (_, text) = script_result(
        &e,
        &[
            "--code",
            "let r=toz.exec({shell:'printf short',capture:true}); print(JSON.stringify({capture:r.capture,stdout:r.stdout}))",
        ],
        None,
    );
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
    let before: serde_json::Value =
        serde_json::from_slice(&toz(&e).args(["stats", "--json"]).output().unwrap().stdout)
            .unwrap();
    toz(&e)
        .args(["query", "--raw", handle.trim()])
        .assert()
        .success()
        .stdout("raw-bytes");

    let stats: serde_json::Value =
        serde_json::from_slice(&toz(&e).args(["stats", "--json"]).output().unwrap().stdout)
            .unwrap();
    assert!(stats[0]["by_query_kind"]
        .as_array()
        .unwrap()
        .iter()
        .any(|kind| kind["kind"] == "raw" && kind["bytes_out"] == "raw-bytes".len()));
    assert_eq!(
        stats[0]["query_bytes"].as_i64().unwrap() - before[0]["query_bytes"].as_i64().unwrap(),
        "raw-bytes".len() as i64
    );
    let missing_handle = format!("r{}", "0".repeat(32));
    toz(&e)
        .args(["query", "--raw", &missing_handle])
        .assert()
        .failure();
    let events: serde_json::Value = serde_json::from_slice(
        &toz(&e)
            .args(["stats", "--events", "2", "--json"])
            .output()
            .unwrap()
            .stdout,
    )
    .unwrap();
    assert_eq!(events[0]["events"][0]["outcome"], "failed_lookup");
    assert_eq!(
        events[0]["events"][0]["details"]["handle_fingerprint"],
        toz_core::content_hash(missing_handle.as_bytes())
    );
    assert_eq!(
        events[0]["events"][1]["details"]["handle_fingerprint"],
        toz_core::content_hash(handle.trim().as_bytes())
    );
    assert!(!serde_json::to_string(&events)
        .unwrap()
        .contains(handle.trim()));
    assert!(!serde_json::to_string(&events)
        .unwrap()
        .contains(&missing_handle));

    let project = toz_core::Project::resolve(Some(e.project.path())).unwrap();
    let db = e.cfg_path.join(&project.key).join("toz.db");
    std::fs::write(db, b"corrupt database").unwrap();
    toz(&e)
        .args(["query", "--raw", handle.trim()])
        .assert()
        .success()
        .stdout("raw-bytes")
        .stderr(predicate::str::contains("query usage not recorded"));
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
    let cases: [(&str, i32); 5] = [
        ("while(true){}", 3),
        ("const a=[];for(;;)a.push(new Array(4096).fill(7))", 4),
        ("for(let i=0;i<1e6;i++)print('xxxxxxxxxxxxxxxxxxxxxxxx')", 5),
        ("for(let i=0;i<=10000;i++)toz.record('row',i)", 6),
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
        assert_eq!(
            out.status.code(),
            Some(want),
            "for `{code}`: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        if code.contains("toz.record") {
            assert!(
                String::from_utf8_lossy(&out.stderr).contains("record limit"),
                "missing actionable record-limit diagnostic: {}",
                String::from_utf8_lossy(&out.stderr)
            );
        }
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
    std::fs::write(e.cfg_path.join("config.toml"), "threshold = 100\n").unwrap();
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
    assert!(
        stdout.len() < 6000,
        "preview should bound the aggregate: {stdout}"
    );
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

    // An explicitly configured fallback does not displace an accessible primary store.
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
