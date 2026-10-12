//! Bounded extraction of the latest usable context-occupancy sample.

use std::fs::{self, File};
use std::io::{Read, Seek, SeekFrom};
use std::path::{Component, Path};

use serde_json::Value;

const MAX_USAGE_BYTES: usize = 1024 * 1024;
const MAX_USAGE_RECORDS: usize = 2_000;
pub(super) const MAX_CONTEXT_USAGE_BYTES: usize = MAX_USAGE_BYTES;
pub(super) const MAX_CONTEXT_USAGE_RECORDS: usize = MAX_USAGE_RECORDS;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContextUsageHarness {
    Claude,
    Codex,
    Opencode,
    Pi,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContextUsage {
    pub current_tokens: u64,
    pub model: Option<String>,
    pub context_window: Option<u64>,
}

/// Read the latest context sample from a verified native session file, or use
/// a direct plugin sample when supplied. Pi session files are a fallback for
/// callers that cannot provide Pi's direct usage value.
pub fn context_usage(
    harness: ContextUsageHarness,
    session_file: Option<&Path>,
    direct_usage: Option<&Value>,
) -> Option<ContextUsage> {
    if let Some(direct) = direct_usage.and_then(|value| parse_direct(harness, value)) {
        return Some(direct);
    }
    let path = session_file?;
    if harness == ContextUsageHarness::Opencode
        && path.extension().and_then(|extension| extension.to_str()) == Some("json")
    {
        let (current_tokens, model) = super::opencode::context_usage_from_export(path)?;
        return Some(ContextUsage {
            current_tokens,
            model,
            context_window: None,
        });
    }
    if !safe_usage_path(harness, path) {
        return None;
    }
    let records = read_tail(path)?;
    parse_records(harness, &records)
}

fn parse_direct(harness: ContextUsageHarness, value: &Value) -> Option<ContextUsage> {
    if !matches!(
        harness,
        ContextUsageHarness::Opencode | ContextUsageHarness::Pi
    ) {
        return None;
    }
    let usage = value.get("usage").unwrap_or(value);
    let current_tokens = match harness {
        ContextUsageHarness::Opencode => sum_fields(
            usage,
            &["input", "output", "reasoning", "cacheRead", "cacheWrite"],
        )?,
        ContextUsageHarness::Pi => {
            sum_fields(usage, &["input", "output", "cacheRead", "cacheWrite"])?
        }
        _ => return None,
    };
    Some(ContextUsage {
        current_tokens,
        model: value
            .get("model")
            .and_then(|model| model.get("id").or_else(|| model.get("modelID")))
            .and_then(Value::as_str)
            .or_else(|| value.get("modelID").and_then(Value::as_str))
            .map(str::to_owned),
        context_window: value
            .get("model")
            .and_then(|model| model.get("contextWindow"))
            .or_else(|| value.get("contextWindow"))
            .and_then(Value::as_u64)
            .filter(|window| *window > 0),
    })
}

fn parse_records(harness: ContextUsageHarness, records: &[Value]) -> Option<ContextUsage> {
    let mut latest = None;
    for record in records {
        if is_reset(record) {
            latest = None;
            continue;
        }
        let sample = match harness {
            ContextUsageHarness::Codex => codex_sample(record),
            ContextUsageHarness::Claude => claude_sample(record),
            ContextUsageHarness::Opencode => opencode_sample(record),
            ContextUsageHarness::Pi => pi_sample(record),
        };
        if sample.is_some() {
            latest = sample;
        }
    }
    latest
}

fn is_reset(record: &Value) -> bool {
    matches!(
        record.get("type").and_then(Value::as_str),
        Some("compacted" | "compaction" | "compact_boundary" | "session_reset")
    )
}

fn codex_sample(record: &Value) -> Option<ContextUsage> {
    if record.pointer("/payload/type").and_then(Value::as_str) != Some("token_count") {
        return None;
    }
    let info = record.pointer("/payload/info")?;
    let current_tokens = super::codex::context_occupancy(record)?;
    Some(ContextUsage {
        current_tokens,
        model: info
            .get("model")
            .and_then(Value::as_str)
            .or_else(|| record.pointer("/payload/model").and_then(Value::as_str))
            .map(str::to_owned),
        context_window: info
            .get("model_context_window")
            .and_then(Value::as_u64)
            .filter(|window| *window > 0),
    })
}

fn claude_sample(record: &Value) -> Option<ContextUsage> {
    if !matches!(
        record.get("type").and_then(Value::as_str),
        Some("assistant" | "user")
    ) {
        return None;
    }
    let current_tokens = super::claude::context_occupancy(record)?;
    Some(ContextUsage {
        current_tokens,
        model: record
            .pointer("/message/model")
            .and_then(Value::as_str)
            .map(str::to_owned),
        context_window: None,
    })
}

fn opencode_sample(record: &Value) -> Option<ContextUsage> {
    if record.get("type").and_then(Value::as_str) != Some("message") {
        return None;
    }
    let message = record.get("message").unwrap_or(record);
    let current_tokens = super::opencode::context_occupancy(record)?;
    Some(ContextUsage {
        current_tokens,
        model: message
            .get("modelID")
            .or_else(|| message.get("model_id"))
            .and_then(Value::as_str)
            .map(str::to_owned),
        context_window: message
            .get("model_context_window")
            .and_then(Value::as_u64)
            .filter(|window| *window > 0),
    })
}

fn pi_sample(record: &Value) -> Option<ContextUsage> {
    if record.get("type").and_then(Value::as_str) != Some("message") {
        return None;
    }
    let message = record.get("message")?;
    if message.get("role").and_then(Value::as_str) != Some("assistant") {
        return None;
    }
    let usage = message.get("usage")?;
    Some(ContextUsage {
        current_tokens: sum_fields(usage, &["input", "output", "cacheRead", "cacheWrite"])?,
        model: message
            .get("model")
            .and_then(|model| model.get("id"))
            .and_then(Value::as_str)
            .map(str::to_owned),
        context_window: message
            .get("model")
            .and_then(|model| model.get("contextWindow"))
            .and_then(Value::as_u64)
            .filter(|window| *window > 0),
    })
}

fn sum_fields(value: &Value, fields: &[&str]) -> Option<u64> {
    let mut found = false;
    let mut total = 0u64;
    for field in fields {
        if let Some(value) = value.get(field) {
            let value = value.as_u64()?;
            total = total.checked_add(value)?;
            found = true;
        }
    }
    found.then_some(total)
}

fn safe_usage_path(harness: ContextUsageHarness, path: &Path) -> bool {
    let Ok(metadata) = fs::symlink_metadata(path) else {
        return false;
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() == 0 {
        return false;
    }
    let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
        return false;
    };
    if !name.ends_with(".jsonl") {
        return false;
    }
    if !path.is_absolute() {
        return false;
    }
    let Ok(canonical) = path.canonicalize() else {
        return false;
    };
    let components = canonical
        .components()
        .filter_map(|component| match component {
            Component::Normal(part) => part.to_str(),
            _ => None,
        })
        .collect::<Vec<_>>();
    let has_anchor = match harness {
        ContextUsageHarness::Codex => components
            .windows(2)
            .any(|pair| pair == [".codex", "sessions"]),
        ContextUsageHarness::Claude => components
            .windows(2)
            .any(|pair| pair == [".claude", "projects"]),
        ContextUsageHarness::Opencode => components.contains(&".opencode"),
        ContextUsageHarness::Pi => components
            .windows(3)
            .any(|parts| parts == [".pi", "agent", "sessions"]),
    };
    if !has_anchor {
        return false;
    }
    true
}

fn read_tail(path: &Path) -> Option<Vec<Value>> {
    let file = File::open(path).ok()?;
    let before = file.metadata().ok()?;
    let length = before.len();
    if length == 0 {
        return None;
    }
    let mut file = file;
    let start = length.saturating_sub(MAX_USAGE_BYTES as u64);
    file.seek(SeekFrom::Start(start)).ok()?;
    let mut bytes = Vec::with_capacity((length - start) as usize);
    file.by_ref()
        .take((MAX_USAGE_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .ok()?;
    let after = file.metadata().ok()?;
    if before.len() != after.len()
        || before.modified().ok()? != after.modified().ok()?
        || bytes.len() != (length - start) as usize
        || bytes.len() > MAX_USAGE_BYTES
        || bytes.last() != Some(&b'\n')
    {
        return None;
    }
    if start > 0 {
        let Some(boundary) = bytes.iter().position(|byte| *byte == b'\n') else {
            return None;
        };
        bytes.drain(..=boundary);
    }
    let lines = bytes
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty());
    let mut records = Vec::new();
    for line in lines {
        if line.len() > super::MAX_RECORD_BYTES || records.len() == MAX_USAGE_RECORDS {
            return None;
        }
        records.push(serde_json::from_slice(line).ok()?);
    }
    (!records.is_empty()).then_some(records)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn codex_uses_latest_context_snapshot_and_ignores_cumulative_total() {
        let records = vec![
            json!({"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":40},"total_token_usage":{"input_tokens":900},"model_context_window":1000,"model":"m"}}}),
            json!({"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":65},"total_token_usage":{"input_tokens":1200},"model_context_window":1000,"model":"m"}}}),
        ];
        let sample = parse_records(ContextUsageHarness::Codex, &records).unwrap();
        assert_eq!(sample.current_tokens, 65);
        assert_eq!(sample.context_window, Some(1000));
        assert_eq!(sample.model.as_deref(), Some("m"));
    }

    #[test]
    fn compaction_resets_snapshot_until_a_new_usage_record_arrives() {
        let before = json!({"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":70}}}});
        let compact = json!({"type":"compacted"});
        assert_eq!(
            parse_records(
                ContextUsageHarness::Codex,
                &[before.clone(), compact.clone()]
            ),
            None
        );
        let after = json!({"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":12}}}});
        assert_eq!(
            parse_records(ContextUsageHarness::Codex, &[before, compact, after])
                .unwrap()
                .current_tokens,
            12
        );
    }

    #[test]
    fn missing_or_malformed_usage_is_not_a_snapshot() {
        let missing = json!({"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":99}}}});
        let malformed = json!({"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":"99"}}}});
        assert_eq!(
            parse_records(ContextUsageHarness::Codex, &[missing, malformed]),
            None
        );
    }

    #[test]
    fn provider_cache_components_follow_adapter_semantics() {
        let claude = json!({"type":"assistant","message":{"model":"claude","usage":{"input_tokens":10,"cache_read_input_tokens":20,"cache_creation_input_tokens":5,"output_tokens":4}}});
        assert_eq!(claude_sample(&claude).unwrap().current_tokens, 35);
        let opencode = json!({"type":"message","message":{"tokens":{"input":10,"output":2,"reasoning":1,"cache":{"read":20,"write":5}}}});
        assert_eq!(opencode_sample(&opencode).unwrap().current_tokens, 38);
    }

    #[test]
    fn pi_uses_direct_usage_or_bounded_session_file_fallback() {
        let root = tempfile::tempdir().unwrap();
        let path = root
            .path()
            .join(".pi/agent/sessions/project/2026-10-07T10-00-00.jsonl");
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(
            &path,
            "{\"type\":\"message\",\"message\":{\"role\":\"assistant\",\"model\":{\"id\":\"pi-model\",\"contextWindow\":80000},\"usage\":{\"input\":50,\"output\":4,\"cacheRead\":3,\"cacheWrite\":2}}}\n",
        )
        .unwrap();
        let fallback = context_usage(ContextUsageHarness::Pi, Some(&path), None).unwrap();
        assert_eq!(fallback.current_tokens, 59);
        assert_eq!(fallback.context_window, Some(80000));
        assert_eq!(fallback.model.as_deref(), Some("pi-model"));

        let direct = json!({
            "usage":{"input":60,"output":5,"cacheRead":4,"cacheWrite":1},
            "model":{"id":"pi-current","contextWindow":90000}
        });
        let current = context_usage(ContextUsageHarness::Pi, Some(&path), Some(&direct)).unwrap();
        assert_eq!(current.current_tokens, 70);
        assert_eq!(current.model.as_deref(), Some("pi-current"));
    }

    #[test]
    fn opencode_export_uses_the_latest_per_message_cache_components() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("session.json");
        std::fs::write(
            &path,
            serde_json::to_vec(&json!({
                "info":{"id":"session-fixture"},
                "messages":[
                    {"type":"assistant","model":{"id":"model-a"},"tokens":{"input":10,"output":3,"reasoning":2,"cache":{"read":7,"write":4}}},
                    {"type":"assistant","model":{"id":"model-b"},"tokens":{"input":12,"output":3,"reasoning":1,"cache":{"read":9,"write":2}}}
                ]
            }))
            .unwrap(),
        )
        .unwrap();
        let sample = context_usage(ContextUsageHarness::Opencode, Some(&path), None).unwrap();
        assert_eq!(sample.current_tokens, 27);
        assert_eq!(sample.model.as_deref(), Some("model-b"));
    }
}
