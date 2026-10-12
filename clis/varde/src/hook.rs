//! `varde hook session-start|post-tool-use`: the harness hook dispatchers.
//! Each runs its configured providers in process and never fails the harness:
//! problems become notices and the exit code is 0 (2 only for bad arguments).

use serde_json::json;
use std::ffi::OsString;
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Duration;
use varde_contracts::{ContractError, Io, RepoMap};
use varde_workflow::{SETUP_WARNING, WithinError, has_managed_block, within};
use varde_workflow_core::memory::{MemoryPaths, load_config};

const PROVIDER_TIMEOUT: Duration = Duration::from_secs(5);
/// Mirrors toz's hook payload limit; one more byte is read so toz sees an
/// oversized payload without it being buffered whole.
const MAX_PAYLOAD_BYTES: u64 = 8 * 1024 * 1024;
const HARNESSES: [&str; 4] = ["claude", "codex", "opencode", "pi"];

/// `args[0]` is `session-start`, `post-tool-use` or `user-prompt-submit`; the
/// rest are its options.
pub fn run(args: Vec<OsString>, io: &Io<'static>) -> ExitCode {
    if args[1..].iter().any(|arg| arg == "-h" || arg == "--help") {
        println!("{}", usage(&args[0].to_string_lossy()));
        return ExitCode::SUCCESS;
    }
    let Some(harness) = harness_option(&args[1..]) else {
        eprintln!("varde hook: --harness <claude|codex|opencode|pi> is required");
        return ExitCode::from(2);
    };
    match args[0].to_string_lossy().as_ref() {
        "post-tool-use" => post_tool_use(&harness),
        "user-prompt-submit" => user_prompt_submit(&harness),
        _ => session_start(&harness, io),
    }
    ExitCode::SUCCESS
}

fn usage(event: &str) -> String {
    format!(
        "Usage: varde hook {event} --harness <claude|codex|opencode|pi>\n\n\
         Options:\n  --harness <HARNESS>  Harness the hook runs for (required)\n  -h, --help           Print help"
    )
}

fn harness_option(args: &[OsString]) -> Option<String> {
    let mut args = args.iter().filter_map(|arg| arg.to_str());
    while let Some(arg) = args.next() {
        let value = match arg.strip_prefix("--harness=") {
            Some(value) => Some(value),
            None if arg == "--harness" => args.next(),
            None => None,
        };
        if let Some(value) = value {
            return HARNESSES.contains(&value).then(|| value.to_string());
        }
    }
    None
}

fn notice(message: &str) -> String {
    format!("varde hook: {message}")
}

// ---- post-tool-use ----

/// Run the configured providers over the PostToolUse payload on stdin. An
/// unreadable config falls back to the defaults so capture keeps working.
fn post_tool_use(harness: &str) {
    let config = load_config().unwrap_or_default();
    let providers = config.post_tool_use_providers();
    let mut payload = Vec::new();
    let _ = std::io::stdin()
        .lock()
        .take(MAX_PAYLOAD_BYTES + 1)
        .read_to_end(&mut payload);
    if payload.len() as u64 > MAX_PAYLOAD_BYTES {
        return;
    }
    let mut capture_output = Vec::new();
    let mut additional_context = Vec::new();
    for name in providers {
        match name.as_str() {
            "capture" => {
                capture_output = varde_toz::hook_capture(&payload, harness);
            }
            "session_notes" => {
                // Claude subagent payloads carry the parent session_id and transcript; only
                // the main agent may consume the crossing. `agent_id` is present only in subagents.
                if let Ok(value) = serde_json::from_slice::<serde_json::Value>(&payload) {
                    let subagent = value.get("agent_id").is_some();
                    if let Some(session_id) = value
                        .get("session_id")
                        .and_then(|id| id.as_str())
                        .filter(|_| !subagent)
                    {
                        if let Some(context) =
                            crate::session_notes::nudge(harness, session_id, &payload, &config)
                        {
                            additional_context.push(context);
                        }
                    }
                }
            }
            _ => eprintln!("{}", notice(&format!("unknown provider `{name}` skipped"))),
        }
    }
    if additional_context.is_empty() {
        let _ = std::io::stdout().write_all(&capture_output);
        return;
    }
    let context = additional_context.join("\n\n");
    let mut output: serde_json::Value =
        serde_json::from_slice(&capture_output).unwrap_or_else(|_| serde_json::json!({}));
    if matches!(harness, "claude" | "codex") {
        if !output
            .get("hookSpecificOutput")
            .is_some_and(serde_json::Value::is_object)
        {
            output["hookSpecificOutput"] = serde_json::json!({"hookEventName":"PostToolUse"});
        }
        append_context(
            &mut output["hookSpecificOutput"]["additionalContext"],
            &context,
        );
    } else {
        if !output.is_object() {
            output = serde_json::json!({});
        }
        append_context(&mut output["additionalContext"], &context);
    }
    println!("{}", output);
}

fn append_context(target: &mut serde_json::Value, addition: &str) {
    let combined = target
        .as_str()
        .filter(|previous| !previous.is_empty())
        .map(|previous| format!("{previous}\n\n{addition}"))
        .unwrap_or_else(|| addition.to_owned());
    *target = serde_json::Value::String(combined);
}

// ---- user-prompt-submit ----

/// Run the configured providers and print the unread inbox one-liners for
/// `main`. Problems become notices and the exit code stays 0; no output when
/// nothing is unread. The cursor advances only after the output is written.
fn user_prompt_submit(harness: &str) {
    let config = load_config().unwrap_or_default();
    let providers = config.user_prompt_submit_providers();
    let mut notices = Vec::new();
    let mut sections = Vec::new();
    let mut pending_cursor = None;
    for name in providers {
        match name.as_str() {
            "inbox" => match inbox_lines(harness) {
                Ok((lines, commit)) => {
                    sections.extend(lines);
                    if commit.is_some() {
                        pending_cursor = commit;
                    }
                }
                Err(reason) => {
                    notices.push(notice(&format!("provider `{name}` skipped: {reason}")))
                }
            },
            _ => notices.push(notice(&format!("unknown provider `{name}` skipped"))),
        }
    }
    for line in &notices {
        eprintln!("{line}");
    }
    if sections.is_empty() {
        commit_pending(pending_cursor);
        return;
    }
    let joined = sections.join("\n");
    let output = if matches!(harness, "claude" | "codex") {
        json!({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": joined,
        }})
        .to_string()
    } else {
        joined
    };
    // Deliver before advancing: a closed stdout must leave the messages unread.
    if writeln!(std::io::stdout().lock(), "{output}").is_err() {
        return;
    }
    commit_pending(pending_cursor);
}

/// Commit the inbox cursor after its one-liners reached the harness.
fn commit_pending(pending: Option<(PathBuf, String, u64)>) {
    if let Some((working, reader, next)) = pending {
        // A failed commit only redelivers; the hook never fails the harness.
        let _ = varde_workflow::commit_cursor(&working, &reader, next);
    }
}

/// The `inbox: `-prefixed unread one-liners for `main`, with the cursor commit
/// to apply once they are delivered, or why they were skipped.
fn inbox_lines(harness: &str) -> Result<(Vec<String>, Option<(PathBuf, String, u64)>), String> {
    let cwd = std::env::current_dir().map_err(|error| format!("cwd unavailable: {error}"))?;
    let root = varde_workflow_core::memory::find_root(&cwd).unwrap_or(cwd);
    let working = MemoryPaths::resolve(&root)
        .map_err(|error| error.to_string())?
        .working
        .path;
    let reader = read_session_id()
        .and_then(|id| find_owned_plan(&working.join("plans"), &format!("{harness}:{id}")))
        .unwrap_or_else(|| "main".to_owned());
    let (messages, commit) =
        varde_workflow::read_unread(&working, &reader).map_err(|error| error.to_string())?;
    let lines = messages
        .iter()
        .map(|message| format!("inbox: {}", message.line()))
        .collect();
    Ok((lines, commit.map(|next| (working, reader, next))))
}

fn find_owned_plan(plans: &Path, owner: &str) -> Option<String> {
    fn visit(directory: &Path, owner: &str) -> Option<String> {
        let entries = fs::read_dir(directory).ok()?;
        for entry in entries.flatten() {
            let path = entry.path();
            let Ok(kind) = entry.file_type() else {
                continue;
            };
            if kind.is_dir() {
                if let Some(id) = visit(&path, owner) {
                    return Some(id);
                }
            } else if kind.is_file() && path.file_name().is_some_and(|name| name == "plan.md") {
                if let Some(id) = varde_workflow::owned_plan_id(&path, owner) {
                    return Some(id);
                }
            }
        }
        None
    }
    visit(plans, owner)
}

fn read_session_id() -> Option<String> {
    let stdin = std::io::stdin();
    let input = read_available_stdin(&stdin)?;
    if input.len() as u64 > MAX_PAYLOAD_BYTES {
        return None;
    }
    let payload: serde_json::Value = serde_json::from_slice(&input).ok()?;
    let session_id = payload.get("session_id")?.as_str()?;
    crate::session_notes::validate_session_id(session_id).map(str::to_owned)
}

#[cfg(unix)]
fn read_available_stdin(stdin: &std::io::Stdin) -> Option<Vec<u8>> {
    use std::io::IsTerminal;
    use std::os::fd::AsRawFd;
    const POLLIN: i16 = 0x001;
    const POLLHUP: i16 = 0x010;
    #[repr(C)]
    struct PollFd {
        fd: i32,
        events: i16,
        revents: i16,
    }
    unsafe extern "C" {
        fn poll(fds: *mut PollFd, count: usize, timeout: i32) -> i32;
    }
    if stdin.is_terminal() {
        return None;
    }
    let mut descriptor = PollFd {
        fd: stdin.as_raw_fd(),
        events: POLLIN,
        revents: 0,
    };
    // A prompt hook must never wait for stdin; only consume an already-ready
    // payload (including EOF) supplied by the harness.
    if unsafe { poll(&mut descriptor, 1, 0) } <= 0 || descriptor.revents & (POLLIN | POLLHUP) == 0 {
        return None;
    }
    let mut input = vec![0; MAX_PAYLOAD_BYTES as usize + 1];
    let length = std::io::Read::read(&mut stdin.lock(), &mut input).ok()?;
    input.truncate(length);
    Some(input)
}

#[cfg(not(unix))]
fn read_available_stdin(_stdin: &std::io::Stdin) -> Option<Vec<u8>> {
    None
}

// ---- session-start ----

fn session_identity() -> Option<String> {
    let mut input = Vec::new();
    std::io::stdin()
        .lock()
        .take(MAX_PAYLOAD_BYTES + 1)
        .read_to_end(&mut input)
        .ok()?;
    if input.len() as u64 > MAX_PAYLOAD_BYTES {
        return None;
    }
    let payload: serde_json::Value = serde_json::from_slice(&input).ok()?;
    let session_id = payload.get("session_id")?.as_str()?;
    crate::session_notes::validate_session_id(session_id).map(str::to_owned)
}

fn session_start(harness: &str, io: &Io<'static>) {
    let session_id = session_identity();
    let notes_path = session_id
        .as_deref()
        .and_then(|id| crate::session_notes::reserve_session(harness, id));
    let mut notices = Vec::new();
    let (providers, targets) = match load_config() {
        Ok(config) => {
            if config.instructions.targets.is_empty() {
                notices.push(notice(SETUP_WARNING));
            }
            (
                config.session_start_providers(),
                config.instructions.targets,
            )
        }
        Err(error) => {
            notices.push(notice(&format!(
                "config unreadable ({error}); no providers run"
            )));
            (Vec::new(), Vec::new())
        }
    };
    let cwd = std::env::current_dir().unwrap_or_default();
    let mut sections = Vec::new();
    if let Some(session_id) = session_id {
        sections.push(format!("varde session: {session_id}"));
        if let Some(path) = notes_path {
            sections.push(format!("varde session notes: {}", path.display()));
        }
    }
    sections.extend(
        providers
            .iter()
            .filter_map(|name| run_provider(name, &cwd, io.repo_map, &targets, &mut notices)),
    );
    // Notices ride in the context so the agent sees what was skipped.
    for line in &notices {
        eprintln!("{line}");
    }
    sections.extend(notices);
    let joined = sections.join("\n\n");
    if matches!(harness, "claude" | "codex") {
        println!(
            "{}",
            json!({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": joined,
            }})
        );
    } else if !joined.is_empty() {
        println!("{joined}");
    }
}

/// Output of one provider, or `None` when it has nothing to add.
fn run_provider(
    name: &str,
    cwd: &Path,
    repo_map: Option<&'static dyn RepoMap>,
    targets: &[String],
    notices: &mut Vec<String>,
) -> Option<String> {
    match name {
        "orchestration" => None,
        "toz_note" => (!targets.iter().any(|t| has_managed_block(Path::new(t))))
            .then(|| varde_toz::note(None)),
        "nav_map" => match nav_map(cwd, repo_map) {
            Ok(text) => Some(text).filter(|text| !text.is_empty()),
            Err(reason) => {
                notices.push(notice(&format!("provider `{name}` skipped: {reason}")));
                None
            }
        },
        _ => {
            notices.push(notice(&format!("unknown provider `{name}` skipped")));
            None
        }
    }
}

/// The repo map text, or why it was skipped. The call runs on a worker thread
/// so a stalled implementation cannot block session start past the timeout.
fn nav_map(cwd: &Path, repo_map: Option<&'static dyn RepoMap>) -> Result<String, String> {
    let map = repo_map.ok_or("repo map unavailable")?;
    let cwd = cwd.to_path_buf();
    let result =
        within(PROVIDER_TIMEOUT, move || map.repo_map_text(&cwd)).map_err(|e| match e {
            WithinError::TimedOut => {
                format!("varde map timed out after {}s", PROVIDER_TIMEOUT.as_secs())
            }
            WithinError::Panicked => "varde map failed: provider panicked".to_string(),
        })?;
    match result {
        Ok(text) => Ok(text.trim().to_string()),
        Err(ContractError { code, message }) => Err(code.unwrap_or(message)),
    }
}
