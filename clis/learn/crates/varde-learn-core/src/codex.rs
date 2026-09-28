//! Codex substring-proxy scoring for `eval trigger`.
//!
//! Codex has no documented skill-invocation event, so a "hit" is any
//! completed `command_execution` whose command contains the absolute
//! `--skill-path`. Port of `skills/eval-tools/parse-codex-trace.py`.

use std::collections::HashSet;
use std::path::Path;

use serde_json::Value;

use crate::trigger::{contains_auth_phrase, parse_events};

const KNOWN_EVENTS: [&str; 9] = [
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "item.started",
    "item.updated",
    "item.completed",
    "warning",
    "error",
];

const KNOWN_ITEMS: [&str; 9] = [
    "agent_message",
    "command_execution",
    "file_change",
    "web_search",
    "mcp_tool_call",
    "reasoning",
    "todo_list",
    "plan",
    "collab_tool_call",
];

/// Port of `parse-codex-trace.py`. Every `fail(...)` call becomes an
/// `Err(())`; the caller turns that into a generic "unusable trace"
/// message, so only the pass/fail shape of each check needs to match, not
/// its wording.
pub(crate) fn parse_codex(trace: &[u8], skill_path: &Path) -> Result<bool, ()> {
    let events = parse_events(trace)?;
    let skill_target = skill_path.to_string_lossy();
    let mut state = TraceState::default();
    for event in &events {
        state.inspect(event, &skill_target)?;
    }
    state.finish()
}

#[derive(Default)]
struct TraceState {
    pending_commands: HashSet<String>,
    thread_started: u32,
    turn_started: u32,
    turn_completed: u32,
    saw_failure: bool,
    hit: bool,
}

impl TraceState {
    fn inspect(&mut self, event: &Value, skill_target: &str) -> Result<(), ()> {
        let obj = event.as_object().ok_or(())?;
        let kind = obj.get("type").and_then(Value::as_str).ok_or(())?;
        if !KNOWN_EVENTS.contains(&kind) {
            return Err(());
        }
        match kind {
            "turn.failed" | "error" => self.saw_failure = true,
            "thread.started" => {
                if obj.get("thread_id").and_then(Value::as_str).is_some() {
                    self.thread_started += 1;
                }
            }
            "turn.started" => self.turn_started += 1,
            "turn.completed" => self.turn_completed += 1,
            "warning" if obj.get("message").and_then(Value::as_str).is_none() => return Err(()),
            _ => {}
        }
        if kind.starts_with("item.") {
            self.inspect_item(obj.get("item").ok_or(())?, kind, skill_target)?;
        }
        Ok(())
    }

    fn inspect_item(&mut self, value: &Value, kind: &str, skill_target: &str) -> Result<(), ()> {
        let item = value.as_object().ok_or(())?;
        let item_type = item.get("type").and_then(Value::as_str).ok_or(())?;
        let item_id = item.get("id").and_then(Value::as_str).ok_or(())?;
        if !KNOWN_ITEMS.contains(&item_type) {
            return Err(());
        }
        if item_type == "command_execution" {
            self.inspect_command(item, item_id, kind, skill_target)?;
        }
        if item_type == "agent_message" {
            let text = item.get("text").and_then(Value::as_str).ok_or(())?;
            if contains_auth_phrase(text) {
                return Err(());
            }
        }
        Ok(())
    }

    fn inspect_command(
        &mut self,
        item: &serde_json::Map<String, Value>,
        item_id: &str,
        kind: &str,
        skill_target: &str,
    ) -> Result<(), ()> {
        let command = item.get("command").and_then(Value::as_str).ok_or(())?;
        if kind == "item.started" {
            self.pending_commands.insert(item_id.to_string());
            let status = item.get("status").and_then(Value::as_str);
            if !matches!(status, None | Some("in_progress")) {
                return Err(());
            }
        }
        if kind == "item.completed" {
            let status = item.get("status").and_then(Value::as_str);
            let exit_code = item.get("exit_code").and_then(Value::as_i64);
            if !matches!(status, Some("completed") | Some("failed")) || exit_code.is_none() {
                return Err(());
            }
            self.pending_commands.remove(item_id);
            if command.contains(skill_target) {
                if status != Some("completed") || exit_code != Some(0) {
                    return Err(());
                }
                self.hit = true;
            }
        }
        Ok(())
    }

    fn finish(self) -> Result<bool, ()> {
        if self.saw_failure
            || self.thread_started != 1
            || self.turn_started != 1
            || self.turn_completed != 1
            || !self.pending_commands.is_empty()
        {
            return Err(());
        }
        Ok(self.hit)
    }
}

#[cfg(test)]
mod tests {
    use super::parse_codex;
    use serde_json::{Value, json};
    use std::path::Path;

    fn trace(events: &[Value]) -> Vec<u8> {
        events
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n")
            .into_bytes()
    }

    fn command(status: &str, exit_code: Option<i64>) -> Value {
        let mut item = json!({
            "id": "command-1",
            "type": "command_execution",
            "command": "cat /tmp/fixture/SKILL.md",
            "status": status,
        });
        if let Some(exit_code) = exit_code {
            item["exit_code"] = json!(exit_code);
        }
        item
    }

    fn lifecycle(started: Value, completed: Value) -> Vec<u8> {
        trace(&[
            json!({"type": "thread.started", "thread_id": "thread-1"}),
            json!({"type": "turn.started"}),
            json!({"type": "item.started", "item": started}),
            json!({"type": "item.completed", "item": completed}),
            json!({"type": "turn.completed"}),
        ])
    }

    #[test]
    fn completed_command_after_start_counts_as_hit() {
        let bytes = lifecycle(command("in_progress", None), command("completed", Some(0)));
        assert_eq!(
            parse_codex(&bytes, Path::new("/tmp/fixture/SKILL.md")),
            Ok(true)
        );
    }

    #[test]
    fn started_command_without_completion_is_rejected() {
        let bytes = trace(&[
            json!({"type": "thread.started", "thread_id": "thread-1"}),
            json!({"type": "turn.started"}),
            json!({"type": "item.started", "item": command("in_progress", None)}),
            json!({"type": "turn.completed"}),
        ]);
        assert_eq!(
            parse_codex(&bytes, Path::new("/tmp/fixture/SKILL.md")),
            Err(())
        );
    }

    #[test]
    fn completed_command_requires_status_and_exit_code() {
        for completed in [command("in_progress", Some(0)), command("completed", None)] {
            let bytes = lifecycle(command("in_progress", None), completed);
            assert_eq!(
                parse_codex(&bytes, Path::new("/tmp/fixture/SKILL.md")),
                Err(())
            );
        }
    }
}
