use assert_cmd::Command;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

struct DetachedChild(PathBuf);

impl Drop for DetachedChild {
    fn drop(&mut self) {
        if let Ok(pid) = std::fs::read_to_string(&self.0) {
            if let Ok(pid) = pid.parse::<libc::pid_t>() {
                if pid > 0 {
                    unsafe {
                        libc::kill(pid, libc::SIGKILL);
                    }
                }
            }
        }
    }
}

fn detached_command(e: &Env, running_leader: bool, noisy: bool) -> (String, DetachedChild) {
    let pid_file = e.project.join("detached.pid");
    let descendant = if noisy {
        "import os,time; end=time.monotonic()+3\nwhile time.monotonic()<end: os.write(1,b'x'*128); time.sleep(.001)"
    } else {
        "import time; time.sleep(3)"
    };
    let source = format!(
        "import subprocess,sys,time\np=subprocess.Popen([sys.executable,'-c',{}],start_new_session=True)\nopen({},'w').write(str(p.pid))\nprint('early-out',flush=True)\nprint('early-err',file=sys.stderr,flush=True)\n{}",
        serde_json::to_string(descendant).unwrap(),
        serde_json::to_string(&pid_file).unwrap(),
        if running_leader { "time.sleep(3)" } else { "" },
    );
    (
        serde_json::to_string(&["python3", "-c", &source]).unwrap(),
        DetachedChild(pid_file),
    )
}

#[test]
fn script_command_timeout_closes_detached_output_pipes() {
    for noisy in [false, true] {
        let e = Env::new();
        let (argv, _cleanup) = detached_command(&e, true, noisy);
        let start = Instant::now();
        let text = e.script_text(&format!("const r=toz.exec({{argv:{argv},timeoutMs:300}}); print(r.timedOut, r.stdout.includes('early-out'), r.stderr.includes('early-err'))"), &["--timeout-ms", "2000"]);
        assert!(start.elapsed() < Duration::from_secs(2));
        assert_eq!(text, "true true true\n");
    }
}

#[test]
fn script_command_exited_leader_reports_retained_output_pipes() {
    let e = Env::new();
    let (argv, _cleanup) = detached_command(&e, false, false);
    let start = Instant::now();
    let text = e.script_text(&format!("try {{ toz.exec({{argv:{argv}}}); print('unexpected success') }} catch(e) {{ print(String(e)) }}"), &["--timeout-ms", "2000"]);
    assert!(start.elapsed() < Duration::from_secs(2));
    assert!(
        text.contains("output pipes remained open after command termination"),
        "{text}"
    );
}

#[test]
fn script_timeout_closes_detached_output_pipes() {
    let e = Env::new();
    let (argv, _cleanup) = detached_command(&e, true, false);
    let start = Instant::now();
    let output = e
        .command()
        .args([
            "--json",
            "run",
            "--code",
            &format!("toz.exec({{argv:{argv}}})"),
            "--timeout-ms",
            "500",
        ])
        .output()
        .unwrap();
    assert!(start.elapsed() < Duration::from_secs(2));
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("script exceeded 500ms"));
}

#[test]
fn script_command_drains_both_streams_completely() {
    let e = Env::new();
    let text = e.script_text("const r=toz.exec({argv:['python3','-c',\"import os; os.write(1,b'o'*20000); os.write(2,b'e'*20000)\"]}); print(r.exitCode, r.stdout === 'o'.repeat(20000), r.stderr === 'e'.repeat(20000))", &[]);
    assert_eq!(text, "0 true true\n");
}

struct Env {
    _temp: tempfile::TempDir,
    config: PathBuf,
    project: PathBuf,
}

impl Env {
    fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let config = temp.path().join("config");
        let project = temp.path().join("project");
        std::fs::create_dir(&config).unwrap();
        std::fs::create_dir(&project).unwrap();
        Self {
            _temp: temp,
            config,
            project,
        }
    }

    fn command(&self) -> Command {
        let mut command = Command::cargo_bin("toz").unwrap();
        command
            .env("TOZ_CONFIG_DIR", &self.config)
            .arg("--project")
            .arg(&self.project);
        command
    }

    fn script_text(&self, code: &str, extra: &[&str]) -> String {
        let output = self
            .command()
            .args(["--json", "run", "--code", code])
            .args(extra)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let result: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
        let handle = result["handle"].as_str().unwrap();
        query_text(&self.config, &self.project, handle)
    }
}

fn query_text(config: &Path, project: &Path, handle: &str) -> String {
    let output = Command::cargo_bin("toz")
        .unwrap()
        .env("TOZ_CONFIG_DIR", config)
        .arg("--project")
        .arg(project)
        .args(["query", "--handle", handle])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap()
}

#[test]
fn main_help_shows_only_query_and_run_as_agent_operations() {
    let help = Command::cargo_bin("toz")
        .unwrap()
        .arg("--help")
        .output()
        .unwrap();
    let text = String::from_utf8_lossy(&help.stdout);
    for command in ["query", "run"] {
        assert!(text.contains(&format!("  {command}")), "{command}: {text}");
    }
    for command in ["search", "show", "script", "exec", "raw", "list", "capture"] {
        assert!(!text.contains(&format!("  {command}")), "{command}: {text}");
    }
    Command::cargo_bin("toz")
        .unwrap()
        .args(["script", "--help"])
        .assert()
        .failure();
}

#[test]
fn script_has_no_mcp_client_binding() {
    let e = Env::new();
    assert_eq!(e.script_text("print(typeof toz.mcp)", &[]), "undefined\n");
}

#[test]
fn script_command_failure_returns_status_without_throwing() {
    let e = Env::new();
    let text = e.script_text("const r=toz.exec({argv:['sh','-c','printf problem >&2; exit 7']}); print(r.exitCode, r.stderr)", &[]);
    assert_eq!(text, "7 problem\n");
}

#[test]
fn script_command_timeout_returns_status() {
    let e = Env::new();
    let text = e.script_text(
        "const r=toz.exec({argv:['sh','-c','sleep 1'],timeoutMs:50}); print(r.timedOut)",
        &["--timeout-ms", "2000"],
    );
    assert_eq!(text, "true\n");
}

#[test]
fn script_command_large_output_returns_capture_handle() {
    let e = Env::new();
    let text = e.script_text("const r=toz.exec({argv:['sh','-c','yes x | head -c 70000']}); print(r.truncated, r.capture.state, r.capture.handle)", &[]);
    let fields: Vec<_> = text.split_whitespace().collect();
    assert_eq!(fields.len(), 3, "{text}");
    assert_eq!(fields[0], "true");
    assert_eq!(fields[1], "captured");
    let shown = query_text(&e.config, &e.project, fields[2]);
    assert!(shown.len() >= 69_000);
}
