//! `varde-workflow hook`: harness hook entry points.
//!
//! `session-start` runs the configured context providers in order and prints
//! their combined output in the shape the harness expects. It never fails the
//! session: problems become one-line notices on stderr and the exit code is 0.

use super::hook_install;
use super::instructions::SETUP_WARNING;
use crate::cli::{Harness, HookArgs, HookCommand, SessionStartArgs};
use anyhow::Result;
use serde_json::json;
use std::io::Read;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};
use varde_workflow_core::memory::load_config;

const PROVIDER_TIMEOUT: Duration = Duration::from_secs(5);
const POLL_INTERVAL: Duration = Duration::from_millis(20);
pub(super) const SPAWN_ERROR_PREFIX: &str = "cannot run ";
/// Extra time to collect pipe output after the child exits or is killed.
const PIPE_GRACE: Duration = Duration::from_millis(250);

pub fn run(args: HookArgs) -> Result<()> {
    match args.command {
        HookCommand::SessionStart(args) => session_start(args),
        HookCommand::Install(args) => hook_install::run(args, false),
        HookCommand::Remove(args) => hook_install::run(args, true),
    }
}

fn session_start(args: SessionStartArgs) -> Result<()> {
    let mut notices = Vec::new();
    let providers = match load_config() {
        Ok(config) => {
            if config.instructions.targets.is_empty() {
                notices.push(notice(SETUP_WARNING));
            }
            config.session_start_providers()
        }
        Err(error) => {
            notices.push(notice(&format!(
                "config unreadable ({error}); no providers run"
            )));
            Vec::new()
        }
    };
    let cwd = std::env::current_dir().unwrap_or_default();
    let mut sections: Vec<String> = providers
        .iter()
        .filter_map(|name| run_provider(name, &cwd, &mut notices))
        .collect();
    // Notices ride in the context so the agent sees what was skipped.
    for line in &notices {
        eprintln!("{line}");
    }
    sections.extend(notices);
    let joined = sections.join("\n\n");
    match args.harness {
        Harness::Opencode | Harness::Pi => {
            if !joined.is_empty() {
                println!("{joined}");
            }
        }
        Harness::Claude | Harness::Codex => println!(
            "{}",
            json!({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": joined,
            }})
        ),
    }
    Ok(())
}

/// Output of one provider, or `None` when it has nothing to add.
fn run_provider(name: &str, cwd: &Path, notices: &mut Vec<String>) -> Option<String> {
    if matches!(name, "orchestration" | "toz_note") {
        return None;
    }
    let (program, argv): (&str, Vec<String>) = match name {
        "nav_map" => {
            let input = json!({"repoRoot": cwd}).to_string();
            let argv = [
                "nav_map",
                "--json",
                &input,
                "--format",
                "text",
                "--with-project-knowledge",
            ]
            .map(String::from)
            .to_vec();
            ("varde-code", argv)
        }
        _ => {
            notices.push(notice(&format!("unknown provider `{name}` skipped")));
            return None;
        }
    };
    match capture(program, &argv, cwd) {
        Ok(text) => match error_envelope(&text) {
            Some(code) => {
                notices.push(notice(&format!("provider `{name}` skipped: {code}")));
                None
            }
            None => Some(text).filter(|text| !text.is_empty()),
        },
        Err(reason) => {
            notices.push(notice(&format!("provider `{name}` skipped: {reason}")));
            None
        }
    }
}

/// The error code (or "error") when `text` is a JSON object with `"ok": false`.
fn error_envelope(text: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(text).ok()?;
    if value.get("ok") != Some(&json!(false)) {
        return None;
    }
    let code = value["data"]["error"]["code"].as_str();
    Some(code.unwrap_or("error").to_string())
}

/// Run `program` for at most `PROVIDER_TIMEOUT`; return trimmed stdout.
///
/// The provider runs in its own process group so a timeout kills wrapper
/// children too, and output is collected with a deadline so a process that
/// still holds the pipes can never block session start.
pub(super) fn capture(program: &str, argv: &[String], cwd: &Path) -> Result<String, String> {
    let mut child = Command::new(program)
        .args(argv)
        .current_dir(cwd)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0)
        .spawn()
        .map_err(|error| format!("{SPAWN_ERROR_PREFIX}{program}: {error}"))?;
    let stdout = drain(child.stdout.take());
    let stderr = drain(child.stderr.take());
    let deadline = Instant::now() + PROVIDER_TIMEOUT;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) if Instant::now() >= deadline => {
                kill_group(child.id());
                let _ = child.wait();
                break Err(format!(
                    "{program} timed out after {}s",
                    PROVIDER_TIMEOUT.as_secs()
                ));
            }
            Ok(None) => thread::sleep(POLL_INTERVAL),
            Err(error) => break Err(format!("{program} wait failed: {error}")),
        }
    };
    let wait = deadline.saturating_duration_since(Instant::now()) + PIPE_GRACE;
    let stdout = stdout.recv_timeout(wait).unwrap_or_else(|_| {
        kill_group(child.id());
        String::new()
    });
    let stderr = stderr.recv_timeout(PIPE_GRACE).unwrap_or_default();
    let status = status?;
    if !status.success() {
        let detail = stderr.lines().next().unwrap_or("").trim();
        return Err(format!("{program} exited with {status} {detail}")
            .trim()
            .to_string());
    }
    Ok(stdout.trim().to_string())
}

/// SIGKILL the provider's process group (its pid is the group id).
fn kill_group(pid: u32) {
    let _ = Command::new("kill")
        .args(["-KILL", "--", &format!("-{pid}")])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

fn drain(pipe: Option<impl Read + Send + 'static>) -> mpsc::Receiver<String> {
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let mut bytes = Vec::new();
        if let Some(mut pipe) = pipe {
            let _ = pipe.read_to_end(&mut bytes);
        }
        let _ = sender.send(String::from_utf8_lossy(&bytes).into_owned());
    });
    receiver
}

fn notice(message: &str) -> String {
    format!("varde-workflow hook: {message}")
}
