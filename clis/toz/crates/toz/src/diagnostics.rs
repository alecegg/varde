//! Small local log of hook outcomes. Never store tool input, output, or error text here.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

const MAX_LOG_BYTES: u64 = 1024 * 1024;
const WINDOW_SECS: u64 = 7 * 24 * 60 * 60;

#[derive(Debug, Deserialize, Serialize)]
struct Event {
    time: u64,
    harness: String,
    outcome: String,
    reason: String,
    tool: String,
    bytes: usize,
}

#[derive(Debug, Default, Serialize)]
pub struct Summary {
    pub captured: usize,
    pub skipped: usize,
    pub failed: usize,
    pub unreadable_lines: usize,
    pub unavailable_sources: usize,
    pub failures_by_reason: BTreeMap<String, usize>,
    pub last_failure: Option<String>,
    #[serde(skip)]
    last_failure_time: u64,
}

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn paths(dir: &Path) -> (PathBuf, PathBuf, PathBuf) {
    (
        dir.join("diagnostics.jsonl"),
        dir.join("diagnostics.1.jsonl"),
        dir.join("diagnostics.lock"),
    )
}

fn fallback_root() -> Option<PathBuf> {
    let project = toz_core::Project::resolve(None).ok()?;
    project
        .fallback_db_path()?
        .parent()?
        .parent()
        .map(Path::to_path_buf)
}

fn field(value: &str, max: usize) -> String {
    value
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
        .take(max)
        .collect()
}

pub fn record(harness: &str, outcome: &str, reason: &str, tool: &str, bytes: usize) -> Result<()> {
    let harness = match harness {
        "claude-code" | "codex" | "pi" | "opencode" => harness,
        _ => "unknown",
    };
    let outcome = match outcome {
        "captured" | "skipped" | "failed" => outcome,
        _ => "failed",
    };
    let reason = match reason {
        "stored" | "invalid-payload" | "unsupported-shape" | "excluded" | "pass-through"
        | "spawn" | "timeout" | "exit" | "empty-response" | "invalid-response"
        | "missing-update" | "hook-error" => reason,
        _ => "other",
    };
    let event = Event {
        time: now(),
        harness: harness.to_string(),
        outcome: outcome.to_string(),
        reason: reason.to_string(),
        tool: field(tool, 64),
        bytes,
    };
    let primary = toz_core::config::config_dir()?;
    match record_in(&primary, &event) {
        Ok(()) => Ok(()),
        Err(primary_error) => {
            let Some(fallback) = fallback_root().filter(|p| p != &primary) else {
                return Err(primary_error);
            };
            record_in(&fallback, &event)
                .with_context(|| format!("primary diagnostics unavailable: {primary_error:#}"))
        }
    }
}

fn record_in(dir: &Path, event: &Event) -> Result<()> {
    let (current, previous, lock_path) = paths(dir);
    fs::create_dir_all(current.parent().context("diagnostics directory")?)?;
    let lock = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(false)
        .mode(0o600)
        .open(&lock_path)?;
    lock.lock()?;
    if current.metadata().is_ok_and(|m| m.len() >= MAX_LOG_BYTES) {
        match fs::remove_file(&previous) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.into()),
        }
        fs::rename(&current, &previous)?;
    }
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .mode(0o600)
        .open(current)?;
    serde_json::to_writer(&mut file, &event)?;
    file.write_all(b"\n")?;
    Ok(())
}

pub fn record_best_effort(harness: &str, outcome: &str, reason: &str, tool: &str, bytes: usize) {
    let _ = record(harness, outcome, reason, tool, bytes);
}

fn read_file(path: &Path, cutoff: u64, summary: &mut Summary) -> Result<()> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(e).with_context(|| format!("opening {}", path.display())),
    };
    for line in BufReader::new(file).lines() {
        let line = line?;
        let event = match serde_json::from_str::<Event>(&line) {
            Ok(event) => event,
            Err(_) => {
                summary.unreadable_lines += 1;
                continue;
            }
        };
        if event.time < cutoff {
            continue;
        }
        match event.outcome.as_str() {
            "captured" => summary.captured += 1,
            "skipped" => summary.skipped += 1,
            "failed" => {
                summary.failed += 1;
                *summary
                    .failures_by_reason
                    .entry(event.reason.clone())
                    .or_default() += 1;
                if event.time >= summary.last_failure_time {
                    summary.last_failure_time = event.time;
                    summary.last_failure = Some(format!(
                        "{} {} {} at unix {}",
                        event.harness, event.tool, event.reason, event.time
                    ));
                }
            }
            _ => {}
        }
    }
    Ok(())
}

pub fn recent() -> Result<Summary> {
    let mut roots = BTreeSet::new();
    roots.insert(toz_core::config::config_dir()?);
    if let Some(root) = fallback_root() {
        roots.insert(root);
    }
    summarize(&roots, now().saturating_sub(WINDOW_SECS))
}

/// Counts events newer than `cutoff` across `roots`, reading both the current log and the
/// rotated one it replaced.
fn summarize(roots: &BTreeSet<PathBuf>, cutoff: u64) -> Result<Summary> {
    let mut summary = Summary::default();
    for root in roots {
        let (current, previous, _) = paths(root);
        let previous_ok = read_file(&previous, cutoff, &mut summary).is_ok();
        let current_ok = read_file(&current, cutoff, &mut summary).is_ok();
        if !previous_ok || !current_ok {
            summary.unavailable_sources += 1;
        }
    }
    Ok(summary)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn event(time: u64, outcome: &str, reason: &str) -> Event {
        Event {
            time,
            harness: "pi".into(),
            outcome: outcome.into(),
            reason: reason.into(),
            tool: "bash".into(),
            bytes: 42,
        }
    }

    fn write_events(path: &Path, events: &[Event]) {
        let mut text = String::new();
        for event in events {
            text.push_str(&serde_json::to_string(event).unwrap());
            text.push('\n');
        }
        fs::write(path, text).unwrap();
    }

    fn serialized(event: &Event) -> String {
        format!("{}\n", serde_json::to_string(event).unwrap())
    }

    #[test]
    fn rotation_keeps_the_newest_events_in_the_current_log() {
        let dir = tempfile::tempdir().unwrap();
        let (current, previous, _) = paths(dir.path());

        // A log already at the size limit is rotated aside before the next event is appended.
        let old = "x".repeat(MAX_LOG_BYTES as usize);
        fs::write(&current, &old).unwrap();
        record_in(dir.path(), &event(1, "captured", "stored")).unwrap();
        assert_eq!(fs::read_to_string(&previous).unwrap(), old);
        assert_eq!(
            fs::read_to_string(&current).unwrap(),
            serialized(&event(1, "captured", "stored"))
        );

        // With room again, later events accumulate in the current log; the rotated file is intact.
        record_in(dir.path(), &event(2, "failed", "timeout")).unwrap();
        assert_eq!(fs::read_to_string(&previous).unwrap(), old);
        assert_eq!(
            fs::read_to_string(&current).unwrap(),
            format!(
                "{}{}",
                serialized(&event(1, "captured", "stored")),
                serialized(&event(2, "failed", "timeout"))
            )
        );
    }

    #[test]
    fn recent_counts_events_from_the_current_and_rotated_logs() {
        let dir = tempfile::tempdir().unwrap();
        let (current, previous, _) = paths(dir.path());
        let cutoff = now().saturating_sub(WINDOW_SECS);
        write_events(&previous, &[event(now(), "skipped", "excluded")]);
        write_events(
            &current,
            &[
                event(now(), "captured", "stored"),
                // Older than the window, so it must not be counted.
                event(1, "failed", "timeout"),
            ],
        );

        let summary = summarize(&BTreeSet::from([dir.path().to_path_buf()]), cutoff).unwrap();
        assert_eq!(summary.captured, 1);
        assert_eq!(summary.skipped, 1);
        assert_eq!(summary.failed, 0);
        assert_eq!(summary.unreadable_lines, 0);
    }
}
