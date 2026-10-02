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
        if let Ok(result) = serde_json::from_slice::<serde_json::Value>(&output.stdout) {
            if let Some(handle) = result["handle"]
                .as_str()
                .filter(|_| result["preview"].is_string())
            {
                return query_text(&self.config, &self.project, handle);
            }
        }
        String::from_utf8(output.stdout).unwrap()
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

fn command_result(e: &Env, request: &str) -> serde_json::Value {
    let code = format!("const r=toz.exec({request}); print(JSON.stringify(r))");
    serde_json::from_str(e.script_text(&code, &[]).trim()).unwrap()
}

#[test]
fn script_command_short_output_is_inline_without_handle() {
    let e = Env::new();
    let result = command_result(&e, "{shell:'printf short'}");
    assert_eq!(result["stdout"], "short");
    assert_eq!(result["capture"]["state"], "inline");
    assert!(result["capture"].get("handle").is_none());
    assert_eq!(result["raw"]["state"], "not_requested");
    assert_eq!(result["truncated"], false);
}

#[test]
fn script_command_threshold_uses_combined_output_bytes() {
    let e = Env::new();
    std::fs::write(e.config.join("config.toml"), "threshold = 4\n").unwrap();
    let inline = command_result(&e, "{shell:'printf ab; printf cd >&2'}");
    assert_eq!(inline["capture"]["state"], "inline");
    assert_eq!(inline["stdout"], "ab");
    assert_eq!(inline["stderr"], "cd");
    let captured = command_result(&e, "{shell:'printf abc; printf cd >&2'}");
    assert_eq!(captured["capture"]["state"], "captured");
    let handle = captured["capture"]["handle"].as_str().unwrap();
    assert!(query_text(&e.config, &e.project, handle).contains("abc"));
}

#[test]
fn script_command_capture_option_forces_searchable_handle() {
    let e = Env::new();
    let result = command_result(&e, "{shell:'printf short',capture:true}");
    assert_eq!(result["capture"]["state"], "captured");
    let handle = result["capture"]["handle"].as_str().unwrap();
    assert_eq!(query_text(&e.config, &e.project, handle), "short\n");
}

#[test]
fn script_command_raw_option_forces_searchable_handle() {
    let e = Env::new();
    std::fs::write(e.config.join("config.toml"), "[raw]\nenabled = true\n").unwrap();
    let result = command_result(&e, "{shell:'printf raw-bytes',raw:true}");
    assert_eq!(result["capture"]["state"], "captured");
    assert_eq!(result["raw"]["state"], "stored");
    let handle = result["capture"]["handle"].as_str().unwrap();
    assert_eq!(query_text(&e.config, &e.project, handle), "raw-bytes\n");
    let raw_handle = result["raw"]["handle"].as_str().unwrap();
    let output = e
        .command()
        .args(["query", "--raw", raw_handle])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout, b"raw-bytes");
}

#[test]
fn script_command_never_capture_overrides_both_force_options() {
    let e = Env::new();
    std::fs::write(
        e.config.join("config.toml"),
        "[capture]\nnever = ['*blocked-source*']\n[raw]\nenabled = true\n",
    )
    .unwrap();
    let result = command_result(&e, "{shell:'printf blocked-source',capture:true,raw:true}");
    assert_eq!(result["stdout"], "blocked-source");
    assert_eq!(result["capture"]["state"], "excluded");
    assert_eq!(result["capture"]["rule"], "never-capture");
    assert_eq!(result["raw"]["state"], "excluded");
    assert!(result["capture"].get("handle").is_none());
    assert!(result["raw"].get("handle").is_none());
}

#[test]
fn script_command_preview_cap_forces_capture_with_high_threshold() {
    let e = Env::new();
    std::fs::write(e.config.join("config.toml"), "threshold = 1000000\n").unwrap();
    let result = command_result(&e, "{shell:'yes x | head -c 70000'}");
    assert_eq!(result["capture"]["state"], "captured");
    assert_eq!(result["truncated"], true);
    let handle = result["capture"]["handle"].as_str().unwrap();
    assert!(query_text(&e.config, &e.project, handle).len() >= 69_000);
}

#[test]
fn run_tiny_final_output_passes_through_without_readback() {
    let e = Env::new();
    for flags in [vec![], vec!["--json"], vec!["--quiet"]] {
        let output = e
            .command()
            .args(flags)
            .args(["run", "--code", "print('tiny result')"])
            .output()
            .unwrap();
        assert!(output.status.success());
        assert_eq!(output.stdout, b"tiny result\n");
    }
}

fn configured_profiles(e: &Env, text: &str) -> PathBuf {
    let root = e.config.join("varde");
    std::fs::create_dir_all(root.join("toz")).unwrap();
    std::fs::write(root.join("toz/profiles.toml"), text).unwrap();
    root
}

#[test]
fn run_final_output_matches_command_profile() {
    let e = Env::new();
    std::fs::write(e.config.join("config.toml"), "threshold = 10\n").unwrap();
    let profiles = configured_profiles(&e, "[[profile]]\nid='final'\nmatch={command='varde-toz run *'}\nscript=\"print('FINAL PROFILE')\"\n");
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", profiles)
        .args(["--json", "run", "--code", "print('overflow content')"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(
        value["preview"]
            .as_str()
            .is_some_and(|preview| preview.contains("FINAL PROFILE")),
        "{value}"
    );
}

#[test]
fn run_child_output_matches_actual_command_profile() {
    let e = Env::new();
    let profiles = configured_profiles(&e,"[[profile]]\nid='child'\nmatch={command='printf child-profile'}\nscript=\"print('CHILD PROFILE')\"\n");
    let output=e.command().env("VARDE_CONFIG_DIR", profiles).args(["run","--code","const r=toz.exec({shell:'printf child-profile',capture:true}); print(r.capture.preview)"]).output().unwrap();
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stdout).contains("CHILD PROFILE"));
}

#[test]
fn run_overflow_uses_normal_plain_json_and_quiet_previews() {
    let e = Env::new();
    std::fs::write(e.config.join("config.toml"), "threshold = 100\n").unwrap();
    for flags in [vec![], vec!["--json"], vec!["--quiet"]] {
        let output = e
            .command()
            .args(&flags)
            .args(["run", "--code", "print('overflow-marker '.repeat(500))"])
            .output()
            .unwrap();
        assert!(output.status.success());
        let text = String::from_utf8(output.stdout).unwrap();
        let handle = if flags == ["--json"] {
            let value: serde_json::Value = serde_json::from_str(&text).unwrap();
            assert!(value["preview"].as_str().unwrap().contains("handle "));
            value["handle"].as_str().unwrap().to_owned()
        } else {
            text.split("handle ")
                .nth(1)
                .unwrap()
                .split_whitespace()
                .next()
                .unwrap()
                .to_owned()
        };
        assert!(text.len() < 4000);
        assert_eq!(
            query_text(&e.config, &e.project, &handle),
            format!("{}\n", "overflow-marker ".repeat(500))
        );
    }
}

#[test]
fn run_excluded_and_binary_final_results_pass_through() {
    let e = Env::new();
    std::fs::write(
        e.config.join("config.toml"),
        "threshold = 5\n[capture]\nnever = ['varde-toz run*']\n",
    )
    .unwrap();
    let output = e
        .command()
        .args(["run", "--code", "print('excluded result')"])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout, b"excluded result\n");
    std::fs::write(e.config.join("config.toml"), "threshold = 5\n").unwrap();
    let output = e
        .command()
        .args(["run", "--code", "print('binary\\0result')"])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout, b"binary\0result\n");
}

#[test]
fn run_final_scripted_profile_records_and_failure_fallback_are_normal() {
    let e = Env::new();
    std::fs::write(e.config.join("config.toml"), "threshold = 5\n").unwrap();
    let profiles=configured_profiles(&e,"[[profile]]\nid='final-records'\nmatch={command='varde-toz run *'}\nscript=\"toz.eachLine(line=>toz.record('line',{line})); print('PROFILE RECORDS')\"\n");
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args(["--json", "run", "--code", "print('first'); print('second')"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(value["preview"]
        .as_str()
        .unwrap()
        .contains("PROFILE RECORDS"));
    let records = e
        .command()
        .args([
            "query",
            "--handle",
            value["handle"].as_str().unwrap(),
            "--records",
            "line",
        ])
        .output()
        .unwrap();
    assert!(records.status.success());
    let rows: Vec<serde_json::Value> = String::from_utf8(records.stdout)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(
        rows,
        serde_json::json!([{"line":"first"},{"line":"second"}])
            .as_array()
            .unwrap()
            .clone()
    );
    configured_profiles(&e,"[[profile]]\nid='boom'\nmatch={command='varde-toz run *'}\nscript=\"throw new Error('profile exploded')\"\n");
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args(["--json", "run", "--code", "print('fallback input')"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(value["preview"].as_str().unwrap().contains("── sections"));
    let doctor = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args(["--json", "doctor"])
        .output()
        .unwrap();
    let doctor: serde_json::Value = serde_json::from_slice(&doctor.stdout).unwrap();
    assert!(doctor["profile_diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .any(|row| row["profile_id"] == "boom"));
}

#[test]
fn run_final_declarative_profile_matches_without_changing_stored_kind() {
    let e = Env::new();
    std::fs::write(e.config.join("config.toml"), "threshold = 5\n").unwrap();
    let profiles=configured_profiles(&e,"[[profile]]\nid='toc'\nmatch={command='varde-toz run *'}\nmerge_small=false\nsections={heading='^## (.+)$'}\npreview={kind='toc',items_per_section=1}\n");
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", profiles)
        .args([
            "--json",
            "run",
            "--code",
            "print('## First\\nalpha\\n## Second\\nbeta')",
        ])
        .output()
        .unwrap();
    assert!(output.status.success());
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let preview = value["preview"].as_str().unwrap();
    assert!(
        preview.contains("First (2 items) L1-L2") && preview.contains("Second (2 items) L3-L4")
    );
    assert_eq!(value["toc"].as_array().unwrap().len(), 2);
    assert_eq!(value["toc"][0]["lines"].as_array().unwrap().len(), 1);
    let list = e
        .command()
        .args(["--json", "query", "--list"])
        .output()
        .unwrap();
    let rows: serde_json::Value = serde_json::from_slice(&list.stdout).unwrap();
    assert_eq!(rows[0]["kind"], "script");
}

#[test]
fn run_child_profiles_buffer_complete_input_with_limit_and_exclusion_precedence() {
    let e = Env::new();
    let profiles=configured_profiles(&e,"[[profile]]\nid='large-child'\nmatch={command='yes *'}\nscript=\"let seen=false; toz.eachLine(line=>{if(line.endsWith('tail-sentinel'))seen=true}); print('COMPLETE '+seen)\"\n");
    let shell = format!(
        "yes {} | head -c 1100000; printf tail-sentinel",
        "x".repeat(255)
    );
    let code = format!("const r=toz.exec({{shell:{}}}); print(r.capture.preview.includes('COMPLETE true'),r.stdout.length,r.truncated)", serde_json::to_string(&shell).unwrap());
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args(["run", "--code", &code])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout, b"true 65536 true\n");
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args([
            "run",
            "--code",
            "toz.exec({shell:'yes x | head -c 8400000'})",
        ])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&output.stderr).contains("8388608-byte limit"));
    std::fs::write(
        e.config.join("config.toml"),
        "[capture]\nnever = ['yes *']\n",
    )
    .unwrap();
    let output=e.command().env("VARDE_CONFIG_DIR",&profiles).args(["run","--code","const r=toz.exec({shell:'yes x | head -c 8400000',capture:true}); print(r.capture.state)"]).output().unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout, b"excluded\n");
}

#[test]
fn run_child_declarative_preview_and_profile_records_use_actual_source() {
    let e = Env::new();
    let profiles=configured_profiles(&e,"[[profile]]\nid='child-sections'\nmatch={command='printf *'}\nsections={heading='^## (.+)$'}\npreview={kind='toc',items_per_section=1,item='^body$'}\n");
    let code = format!("const r=toz.exec({{shell:{},capture:true}}); print(JSON.stringify({{preview:r.capture.preview,state:r.capture.state}}))", serde_json::to_string("printf '%s\\n' '## Child' body").unwrap());
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args(["run", "--code", &code])
        .output()
        .unwrap();
    assert!(output.status.success());
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let preview = value["preview"].as_str().unwrap();
    assert!(preview.contains("Child (1 items)"), "{preview}");
    assert_eq!(value["state"], "captured");
    configured_profiles(&e,"[[profile]]\nid='child-records'\nmatch={command='printf *'}\nscript=\"toz.eachLine(line=>toz.record('line',{line})); print('CHILD RECORDS')\"\n");
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args([
            "run",
            "--code",
            "const r=toz.exec({shell:'printf child',capture:true}); print(r.capture.handle)",
        ])
        .output()
        .unwrap();
    assert!(output.status.success());
    let handle = String::from_utf8(output.stdout).unwrap();
    let records = e
        .command()
        .args(["query", "--handle", handle.trim(), "--records", "line"])
        .output()
        .unwrap();
    assert!(records.status.success());
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&records.stdout).unwrap(),
        serde_json::json!({"line":"child"})
    );
}

#[test]
fn run_final_profile_input_cap_honors_exclusions_and_unprofiled_output() {
    let e = Env::new();
    let config = "threshold = 10\n[script]\nmax_output_bytes = 10485760\n";
    std::fs::write(e.config.join("config.toml"), config).unwrap();
    let profiles=configured_profiles(&e,"[[profile]]\nid='bounded-final'\nmatch={command='varde-toz run *'}\nscript=\"print('PROFILE RAN')\"\n");
    let large = "print('x'.repeat(9*1024*1024))";
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args(["run", "--code", large])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&output.stderr).contains("8388608-byte limit"));
    std::fs::write(
        e.config.join("config.toml"),
        format!("{config}[capture]\nnever=['varde-toz run *']\n"),
    )
    .unwrap();
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args(["run", "--code", large])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout.len(), 9 * 1024 * 1024 + 1);
    std::fs::write(e.config.join("config.toml"), config).unwrap();
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args(["run", "--code", "print('\\0'+'x'.repeat(9*1024*1024))"])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout[0], 0);
    std::fs::remove_file(profiles.join("toz/profiles.toml")).unwrap();
    let output = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args(["--json", "run", "--code", large])
        .output()
        .unwrap();
    assert!(output.status.success());
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(value["handle"].is_string());
    assert!(value["preview"].is_string());
}

#[test]
fn run_child_scripted_profile_failure_falls_back_and_records_diagnostic() {
    let e = Env::new();
    let profiles=configured_profiles(&e,"[[profile]]\nid='child-boom'\nmatch={command='printf *'}\nscript=\"throw new Error('child exploded')\"\n");
    let output=e.command().env("VARDE_CONFIG_DIR",&profiles).args(["run","--code","const r=toz.exec({shell:'printf child',capture:true}); print(r.capture.preview.includes('── sections'),r.stdout)"]).output().unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout, b"true child\n");
    let doctor = e
        .command()
        .env("VARDE_CONFIG_DIR", &profiles)
        .args(["--json", "doctor"])
        .output()
        .unwrap();
    let doctor: serde_json::Value = serde_json::from_slice(&doctor.stdout).unwrap();
    assert!(doctor["profile_diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .any(|row| row["profile_id"] == "child-boom"));
}

#[test]
fn captured_analysis_supersedes_itself_but_external_runs_keep_fresh_handles() {
    let e = Env::new();
    std::fs::write(e.config.join("config.toml"), "threshold = 5\n").unwrap();
    let capture = e
        .command()
        .args(["--json", "capture", "--source", "analysis-input", "--force"])
        .write_stdin("input lines\n")
        .output()
        .unwrap();
    assert!(capture.status.success());
    let value: serde_json::Value = serde_json::from_slice(&capture.stdout).unwrap();
    let handle = value["handle"].as_str().unwrap();
    let code = "print('stable aggregate')";
    for _ in 0..2 {
        assert!(e
            .command()
            .args(["run", "--handle", handle, "--code", code])
            .output()
            .unwrap()
            .status
            .success());
    }
    let list = e
        .command()
        .args(["--json", "query", "--list"])
        .output()
        .unwrap();
    let rows: serde_json::Value = serde_json::from_slice(&list.stdout).unwrap();
    assert_eq!(
        rows.as_array()
            .unwrap()
            .iter()
            .filter(|row| row["kind"] == "script")
            .count(),
        1
    );
    for _ in 0..2 {
        assert!(e
            .command()
            .args([
                "run",
                "--code",
                "const r=toz.exec({shell:'printf short'}); print('fresh aggregate')"
            ])
            .output()
            .unwrap()
            .status
            .success());
    }
    let list = e
        .command()
        .args(["--json", "query", "--list"])
        .output()
        .unwrap();
    let rows: serde_json::Value = serde_json::from_slice(&list.stdout).unwrap();
    assert_eq!(
        rows.as_array()
            .unwrap()
            .iter()
            .filter(|row| row["kind"] == "script")
            .count(),
        3
    );
    for _ in 0..2 {
        assert!(e
            .command()
            .args([
                "run",
                "--label",
                "explicit",
                "--code",
                "toz.exec({shell:'printf short'}); print('explicit aggregate')"
            ])
            .output()
            .unwrap()
            .status
            .success());
    }
    let list = e
        .command()
        .args(["--json", "query", "--list"])
        .output()
        .unwrap();
    let rows: serde_json::Value = serde_json::from_slice(&list.stdout).unwrap();
    assert_eq!(
        rows.as_array()
            .unwrap()
            .iter()
            .filter(|row| row["label"] == "explicit")
            .count(),
        1
    );
}
