//! Run the user-configured, harness-independent plan wake command.

use crate::commands::msg::MAX_TEXT_CHARS;
use crate::commands::watch::Event;
use anyhow::{Context, Result};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

pub(super) struct WakeRunner {
    argv: Vec<String>,
    timeout: Duration,
    max_failures: u32,
    failures: u32,
    disabled: bool,
}

impl WakeRunner {
    pub(super) fn load() -> Result<Self> {
        let config =
            varde_workflow_core::memory::load_config().context("could not load Varde config")?;
        let orchestration = config.orchestration;
        let (argv, command_error) = orchestration.wake_command();
        if let Some(reason) = command_error {
            eprintln!(
                "varde plan watch: orchestration.wake_command ignored ({reason}); using an empty command"
            );
        }
        let (timeout, timeout_error) = orchestration.wake_timeout_seconds();
        if let Some(reason) = timeout_error {
            eprintln!(
                "varde plan watch: orchestration.wake_timeout_seconds ignored ({reason}); using {timeout}"
            );
        }
        let (max_failures, failures_error) = orchestration.wake_max_failures();
        if let Some(reason) = failures_error {
            eprintln!(
                "varde plan watch: orchestration.wake_max_failures ignored ({reason}); using {max_failures}"
            );
        }
        Ok(Self {
            argv,
            timeout: Duration::from_secs(timeout),
            max_failures,
            failures: 0,
            disabled: false,
        })
    }

    pub(super) fn empty() -> Self {
        Self {
            argv: Vec::new(),
            timeout: Duration::from_secs(0),
            max_failures: 0,
            failures: 0,
            disabled: false,
        }
    }

    pub(super) fn run(&mut self, event: &Event) -> Result<Option<String>> {
        if self.argv.is_empty() || self.disabled {
            return Ok(None);
        }
        let result = run_command(&self.argv, self.timeout, event);
        match result {
            Ok(()) => {
                self.failures = 0;
                Ok(None)
            }
            Err(reason) => {
                self.failures += 1;
                let message = format!("wake failed: {reason}");
                if self.failures >= self.max_failures {
                    self.disabled = true;
                    Ok(Some(format!("{message}; wake is disabled until restart")))
                } else {
                    Ok(Some(message))
                }
            }
        }
    }
}

fn run_command(
    argv: &[String],
    timeout: Duration,
    event: &Event,
) -> std::result::Result<(), String> {
    let Some((program, args)) = argv.split_first() else {
        return Ok(());
    };
    let mut child = Command::new(program)
        .args(args)
        .env(
            "VARDE_WAKE_EVENT",
            match event.kind {
                crate::commands::watch::EventKind::Stale => "stale",
                crate::commands::watch::EventKind::Blocked => "blocked",
                crate::commands::watch::EventKind::NeedsDecision => "needs-decision",
                crate::commands::watch::EventKind::MergeReady => "merge-ready",
                crate::commands::watch::EventKind::Finished => "finished",
            },
        )
        .env("VARDE_WAKE_PLAN", clean(&event.plan, MAX_TEXT_CHARS))
        .env(
            "VARDE_WAKE_OWNER",
            clean(event.owner.as_deref().unwrap_or(""), MAX_TEXT_CHARS),
        )
        .env("VARDE_WAKE_TEXT", clean(&event.line(), MAX_TEXT_CHARS))
        .stdin(Stdio::null())
        // Watcher stdout is an event stream for subscribers; keep the child out of it.
        .stdout(Stdio::null())
        .spawn()
        .map_err(|error| format!("could not start command: {error}"))?;
    let started = Instant::now();
    loop {
        let status = match child.try_wait() {
            Ok(status) => status,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("could not wait for command: {error}"));
            }
        };
        match status {
            Some(status) if status.success() => return Ok(()),
            Some(status) => return Err(format!("command exited with {status}")),
            None if started.elapsed() >= timeout => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("command timed out after {}s", timeout.as_secs()));
            }
            None => thread::sleep(Duration::from_millis(10)),
        }
    }
}

fn clean(value: &str, limit: usize) -> String {
    value
        .chars()
        .filter(|character| !character.is_control())
        .take(limit)
        .collect()
}
