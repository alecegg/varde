//! Official client arguments and Codex's JSONL-to-artifact conversion.
use super::OutputHarness;
use crate::error::LearnError;
use serde_json::{Value, json};
use std::{collections::BTreeSet, fs, path::Path};

pub(super) fn args(
    harness: OutputHarness,
    model: Option<&str>,
    prompt: &str,
    cwd: &Path,
    judge: bool,
) -> Vec<String> {
    let mut args = match harness {
        OutputHarness::Claude => vec![
            "-p".into(),
            prompt.into(),
            "--output-format".into(),
            "json".into(),
            "--disable-slash-commands".into(),
            "--setting-sources".into(),
            if judge { "local" } else { "project,local" }.into(),
        ],
        OutputHarness::Codex => vec![
            "exec".into(),
            "--json".into(),
            "--sandbox".into(),
            if judge {
                "read-only"
            } else {
                "workspace-write"
            }
            .into(),
            "--ephemeral".into(),
            "--ignore-user-config".into(),
            "--skip-git-repo-check".into(),
            "-c".into(),
            "project_doc_max_bytes=0".into(),
        ],
    };
    if let Some(model) = model.or(harness.default_model()) {
        args.extend(["--model".into(), model.into()]);
    }
    if harness == OutputHarness::Codex {
        if !judge {
            args.push("--approve-for-me".into());
        }
        for feature in ["plugins", "hooks", "memories"] {
            args.extend(["--disable".into(), feature.into()]);
        }
        let mut roots = Vec::new();
        if let Some(home) = std::env::var_os("HOME") {
            roots.push(std::path::PathBuf::from(&home).join(".agents/skills"));
            roots.push(std::path::PathBuf::from(home).join(".codex/skills"));
        }
        if let Some(home) = std::env::var_os("CODEX_HOME") {
            roots.push(std::path::PathBuf::from(home).join("skills"));
        }
        roots.push("/etc/codex/skills".into());
        for ancestor in cwd.ancestors() {
            roots.push(ancestor.join(".agents/skills"));
            roots.push(ancestor.join(".codex/skills"));
        }
        let mut skills = BTreeSet::new();
        for root in roots {
            discover_skills(&root, &mut skills, &mut BTreeSet::new());
        }
        let entries: Vec<String> = skills
            .iter()
            .map(|path| {
                format!(
                    "{{path={},enabled=false}}",
                    serde_json::to_string(&path.to_string_lossy()).unwrap()
                )
            })
            .collect();
        args.extend([
            "-c".into(),
            format!("skills.config=[{}]", entries.join(",")),
            "-".into(),
        ]);
    }
    args
}

fn discover_skills(
    root: &Path,
    skills: &mut BTreeSet<std::path::PathBuf>,
    visited: &mut BTreeSet<std::path::PathBuf>,
) {
    let Ok(canonical) = fs::canonicalize(root) else {
        return;
    };
    if !visited.insert(canonical.clone()) {
        return;
    }
    if canonical.join("SKILL.md").is_file() {
        skills.insert(canonical);
        return;
    }
    let Ok(entries) = fs::read_dir(canonical) else {
        return;
    };
    for entry in entries.flatten() {
        if entry.path().is_dir() {
            discover_skills(&entry.path(), skills, visited);
        }
    }
}

/// Preserve tool lifecycle events in occurrence order and require one successful terminal turn.
pub(super) fn normalize_codex(text: &str) -> Result<Value, String> {
    let mut started = false;
    let mut completed = false;
    let mut result = String::new();
    let mut content = Vec::new();
    let mut usage = Value::Null;
    for line in text.lines().filter(|line| !line.trim().is_empty()) {
        let event: Value =
            serde_json::from_str(line).map_err(|err| format!("Malformed Codex JSONL: {err}"))?;
        if completed {
            return Err("Codex events appeared after terminal turn".into());
        }
        match event.get("type").and_then(Value::as_str) {
            Some("thread.started" | "warning") => {}
            Some("turn.started") if !started => started = true,
            Some(phase @ ("item.started" | "item.updated" | "item.completed")) if started => {
                let item = event
                    .get("item")
                    .filter(|v| v.is_object())
                    .ok_or("Missing Codex item")?;
                let kind = item
                    .get("type")
                    .and_then(Value::as_str)
                    .ok_or("Missing Codex item type")?;
                if kind == "agent_message" && phase == "item.completed" {
                    result = item
                        .get("text")
                        .and_then(Value::as_str)
                        .ok_or("Missing agent message text")?
                        .into();
                } else if matches!(
                    kind,
                    "command_execution"
                        | "file_change"
                        | "mcp_tool_call"
                        | "collab_tool_call"
                        | "web_search"
                ) {
                    content.push(json!({"type":"tool_use","name":kind,"event_type":phase,"input":{"event_type":phase,"item":item}}));
                }
            }
            Some("turn.completed") if started => {
                completed = true;
                usage = event.get("usage").cloned().unwrap_or(Value::Null);
            }
            Some("turn.failed" | "error") => return Err(format!("Codex run failed: {event}")),
            _ => return Err(format!("Unexpected Codex event: {event}")),
        }
    }
    if !completed {
        return Err("Codex trace has no completed terminal turn".into());
    }
    Ok(json!({"result":result,"messages":[{"content":content}],"usage":usage}))
}

fn validate_claude(text: &str) -> Result<Value, String> {
    let value: Value =
        serde_json::from_str(text).map_err(|err| format!("Malformed Claude JSON: {err}"))?;
    if !value.is_object() {
        return Err("Claude response must be a result object".into());
    }
    if value.get("type").and_then(Value::as_str) != Some("result") {
        return Err("Claude response has no result type".into());
    }
    if value.get("subtype").and_then(Value::as_str) != Some("success") {
        return Err("Claude result has no successful subtype".into());
    }
    if value.get("is_error").and_then(Value::as_bool) != Some(false) {
        return Err("Claude result did not report is_error=false".into());
    }
    if value.get("result").and_then(Value::as_str).is_none() {
        return Err("Claude result has no text result".into());
    }
    Ok(value)
}

pub(super) fn read_raw(
    harness: OutputHarness,
    path: &Path,
    normalized: &Path,
) -> Result<(Option<Value>, Option<String>), LearnError> {
    let text = fs::read_to_string(path).unwrap_or_default();
    match harness {
        OutputHarness::Claude => match validate_claude(&text) {
            Ok(value) => Ok((Some(value), None)),
            Err(error) => Ok((None, Some(error))),
        },
        OutputHarness::Codex => match normalize_codex(&text) {
            Ok(value) => {
                fs::write(
                    normalized,
                    serde_json::to_vec_pretty(&value).map_err(|err| {
                        LearnError::Usage(format!(
                            "failed to encode normalized Codex output: {err}"
                        ))
                    })?,
                )
                .map_err(|err| {
                    LearnError::Usage(format!("failed to write {}: {err}", normalized.display()))
                })?;
                Ok((Some(value), None))
            }
            Err(error) => {
                fs::write(normalized, json!({"error":error}).to_string()).map_err(|err| {
                    LearnError::Usage(format!("failed to write {}: {err}", normalized.display()))
                })?;
                Ok((None, Some(error)))
            }
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn claude_requires_successful_text_result_and_preserves_metadata() {
        let valid = json!({"type":"result","subtype":"success","is_error":false,"result":"",
            "usage":{"input_tokens":12},"total_cost_usd":0.1});
        assert_eq!(validate_claude(&valid.to_string()).unwrap(), valid);
        for text in ["", "invalid-json", "null", "[]", "{}"] {
            assert!(validate_claude(text).is_err(), "{text}");
        }
        for (field, wrong) in [
            ("type", json!("assistant")),
            ("subtype", json!("error_max_turns")),
            ("is_error", json!(true)),
            ("is_error", json!("false")),
            ("result", Value::Null),
            ("result", json!(42)),
        ] {
            let mut invalid = valid.clone();
            invalid[field] = wrong;
            assert!(validate_claude(&invalid.to_string()).is_err(), "{invalid}");
        }
        for field in ["type", "subtype", "is_error", "result"] {
            let mut invalid = valid.clone();
            invalid.as_object_mut().unwrap().remove(field);
            assert!(validate_claude(&invalid.to_string()).is_err(), "{invalid}");
        }
    }

    #[test]
    fn lifecycle_order_preserves_edit_start_before_review_completion() {
        let events = [
            json!({"type":"turn.started"}),
            json!({"type":"warning","message":"recoverable"}),
            json!({"type":"item.started","item":{"type":"collab_tool_call","id":"review"}}),
            json!({"type":"item.started","item":{"type":"file_change","id":"edit"}}),
            json!({"type":"item.completed","item":{"type":"collab_tool_call","id":"review","status":"completed"}}),
            json!({"type":"item.completed","item":{"type":"file_change","id":"edit","status":"completed"}}),
            json!({"type":"turn.completed"}),
        ];
        let normalized = normalize_codex(
            &events
                .iter()
                .map(Value::to_string)
                .collect::<Vec<_>>()
                .join("\n"),
        )
        .unwrap();
        let tools = normalized["messages"][0]["content"].as_array().unwrap();
        assert_eq!(tools.len(), 4);
        assert_eq!(tools[1]["input"]["event_type"], "item.started");
        assert_eq!(tools[1]["input"]["item"]["id"], "edit");
        assert_eq!(tools[2]["input"]["event_type"], "item.completed");
        assert_eq!(tools[2]["input"]["item"]["id"], "review");
    }
}
