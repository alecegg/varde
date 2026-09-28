use std::io::{IsTerminal, Read};
use std::path::PathBuf;

use serde_json::{Value, json};
use varde_learn_core::diagnose::{
    ClaudeHookContext, CurrentOverlap, DiagnosticHarness, InspectRequest, Intake, capture, inspect,
};

use crate::cli::{DiagnoseCaptureArgs, DiagnoseHarness, DiagnoseInspectArgs};

pub(super) fn run_capture_command(args: DiagnoseCaptureArgs) -> anyhow::Result<()> {
    if !args.json {
        return Err(invalid("diagnose capture requires --json"));
    }
    let output = capture(&args.file)?;
    println!(
        "{}",
        json!({
            "schema_version": 1,
            "envelope_version": 1,
            "ok": true,
            "outcome": "success",
            "data": output,
            "meta": { "truncated": false },
        })
    );
    Ok(())
}

pub(super) fn run_inspect_command(args: DiagnoseInspectArgs) -> anyhow::Result<()> {
    let intake = if let Some(snapshot) = args.snapshot_in {
        if args.snapshot_out.is_some() || args.cutoff_anchor.is_some() {
            return Err(invalid(
                "--snapshot-in cannot be combined with --snapshot-out or --cutoff-anchor",
            ));
        }
        Intake::Snapshot(snapshot)
    } else {
        let selected = usize::from(args.current)
            + usize::from(args.session.is_some())
            + usize::from(args.path.is_some());
        if selected != 1 {
            return Err(invalid(
                "choose exactly one live intake: --current, --session, or --path; use --snapshot-in for frozen evidence",
            ));
        }
        let harness = args
            .harness
            .ok_or_else(|| invalid("--harness is required for a live intake"))?;
        if args.current {
            match harness {
                DiagnoseHarness::Codex => Intake::Current {
                    source_root: codex_home()?,
                    session_id: std::env::var("CODEX_THREAD_ID").ok(),
                    claude_hook: None,
                },
                DiagnoseHarness::Claude => {
                    let (session_id, claude_hook) = claude_hook_context()?;
                    Intake::Current {
                        source_root: claude_projects_root()?,
                        session_id: Some(session_id),
                        claude_hook: Some(claude_hook),
                    }
                }
                DiagnoseHarness::Opencode => Intake::Current {
                    source_root: opencode_data_root()?,
                    session_id: None,
                    claude_hook: None,
                },
            }
        } else if let Some(session_id) = args.session {
            let source_root = match harness {
                DiagnoseHarness::Codex => codex_home()?,
                DiagnoseHarness::Claude => claude_projects_root()?,
                DiagnoseHarness::Opencode => opencode_data_root()?,
            };
            Intake::Session {
                source_root,
                session_id,
            }
        } else {
            let source_root = match harness {
                DiagnoseHarness::Codex => codex_home()?,
                DiagnoseHarness::Claude => claude_projects_root()?,
                DiagnoseHarness::Opencode => opencode_data_root()?,
            };
            Intake::Path {
                source_root,
                path: args.path.expect("one live intake was validated"),
            }
        }
    };

    let request = InspectRequest {
        harness: args.harness.map(|harness| match harness {
            DiagnoseHarness::Codex => DiagnosticHarness::Codex,
            DiagnoseHarness::Claude => DiagnosticHarness::Claude,
            DiagnoseHarness::Opencode => DiagnosticHarness::Opencode,
        }),
        intake,
        offset: args.offset,
        limit: args.limit,
        snapshot_out: args.snapshot_out,
        cutoff_anchor: args.cutoff_anchor,
    };
    let output = inspect(&request)?;
    let total = output.coverage.record_count;
    let start = args.offset.min(total);
    let page_end = start.saturating_add(output.records.len());
    let truncated = output.coverage.truncated || page_end < total;
    if args.json {
        println!(
            "{}",
            json!({
                "schema_version": 1,
                "envelope_version": 1,
                "ok": true,
                "outcome": "success",
                "data": output,
                "meta": {
                    "offset": start,
                    "limit": args.limit,
                    "total": total,
                    "returned": output.records.len(),
                    "truncated": truncated,
                },
            })
        );
    } else {
        let overlap = match output.overlap {
            CurrentOverlap::Current => "current",
            CurrentOverlap::NotCurrent => "not_current",
            CurrentOverlap::Unknown => "unknown",
        };
        println!(
            "{} session {} ({overlap} overlap): {} evidence records",
            output.session.harness,
            output.session.thread_id,
            output.records.len()
        );
    }
    Ok(())
}

fn claude_projects_root() -> anyhow::Result<PathBuf> {
    let config = std::env::var_os("CLAUDE_CONFIG_DIR")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".claude")))
        .ok_or_else(|| {
            invalid("CLAUDE_CONFIG_DIR or HOME is required for Claude session discovery")
        })?;
    Ok(config.join("projects"))
}

fn claude_hook_context() -> anyhow::Result<(String, ClaudeHookContext)> {
    const MAX_HOOK_BYTES: usize = 64 * 1024;
    let stdin = std::io::stdin();
    if stdin.is_terminal() {
        return Err(current_unavailable(
            "Claude --current requires command-hook JSON on stdin",
        ));
    }
    let mut bytes = Vec::new();
    stdin
        .take((MAX_HOOK_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|error| current_unavailable(format!("cannot read Claude hook input: {error}")))?;
    if bytes.is_empty() || bytes.len() > MAX_HOOK_BYTES {
        return Err(current_unavailable(
            "Claude hook input is empty or exceeds the 64 KiB limit",
        ));
    }
    let value: Value = serde_json::from_slice(&bytes).map_err(|error| {
        current_unavailable(format!("Claude hook input is invalid JSON: {error}"))
    })?;
    let session_id = required_hook_string(&value, "session_id")?;
    let transcript_path = required_hook_path(&value, "transcript_path")?;
    let cwd = value
        .get("cwd")
        .and_then(Value::as_str)
        .filter(|path| !path.trim().is_empty())
        .map(PathBuf::from);
    let agent_id = value
        .get("agent_id")
        .and_then(Value::as_str)
        .filter(|id| !id.trim().is_empty())
        .map(str::to_owned);
    let agent_transcript_path = value
        .get("agent_transcript_path")
        .and_then(Value::as_str)
        .filter(|path| !path.trim().is_empty())
        .map(PathBuf::from);
    Ok((
        session_id,
        ClaudeHookContext {
            transcript_path,
            cwd,
            agent_id,
            agent_transcript_path,
        },
    ))
}

fn required_hook_string(value: &Value, field: &str) -> anyhow::Result<String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .map(str::to_owned)
        .ok_or_else(|| current_unavailable(format!("Claude hook input is missing `{field}`")))
}

fn required_hook_path(value: &Value, field: &str) -> anyhow::Result<PathBuf> {
    let path = PathBuf::from(required_hook_string(value, field)?);
    if !path.is_absolute() {
        return Err(current_unavailable(format!(
            "Claude hook `{field}` must be an absolute path"
        )));
    }
    Ok(path)
}

fn current_unavailable(message: impl Into<String>) -> anyhow::Error {
    varde_learn_core::LearnError::Diagnose {
        code: "diagnose_current_unavailable",
        message: message.into(),
    }
    .into()
}

fn codex_home() -> anyhow::Result<PathBuf> {
    if let Some(home) = std::env::var_os("CODEX_HOME") {
        return Ok(PathBuf::from(home));
    }
    let home = std::env::var_os("HOME")
        .ok_or_else(|| invalid("CODEX_HOME or HOME is required for Codex session discovery"))?;
    Ok(PathBuf::from(home).join(".codex"))
}

fn opencode_data_root() -> anyhow::Result<PathBuf> {
    if let Some(database) = std::env::var_os("OPENCODE_DB") {
        let path = PathBuf::from(database);
        if path.is_absolute() {
            return Ok(path
                .parent()
                .unwrap_or_else(|| std::path::Path::new("/"))
                .to_path_buf());
        }
    }
    if let Some(data_home) = std::env::var_os("XDG_DATA_HOME") {
        return Ok(PathBuf::from(data_home).join("opencode"));
    }
    let home = std::env::var_os("HOME").ok_or_else(|| {
        invalid("XDG_DATA_HOME or HOME is required for OpenCode session discovery")
    })?;
    Ok(PathBuf::from(home).join(".local/share/opencode"))
}

fn invalid(message: impl Into<String>) -> anyhow::Error {
    varde_learn_core::LearnError::Diagnose {
        code: "usage_error",
        message: message.into(),
    }
    .into()
}
