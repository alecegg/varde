use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

use serde_json::Value;

use super::super::{
    EvidenceRecord, MAX_RECORD_BYTES, MAX_SOURCE_BYTES, MAX_TEXT_EXCERPT, NormalizedRecordBudget,
    RecordAnchor, SourceSnapshot, digest, error, file_identity,
};
use super::discovery::{self, Header};
use crate::LearnError;

struct ReadSource {
    source: SourceSnapshot,
    bytes: Vec<u8>,
    initial_truncated: bool,
}

pub(crate) struct ParsedSource {
    pub(crate) header: Header,
    pub(crate) source: SourceSnapshot,
    pub(crate) records: Vec<EvidenceRecord>,
    pub(crate) processed_records: usize,
    pub(crate) incomplete_tail: bool,
    pub(crate) malformed_records: usize,
    pub(crate) omitted_records: usize,
    pub(crate) unknown_events: usize,
    pub(crate) inherited_events: usize,
    pub(crate) truncated: bool,
    pub(crate) warnings: Vec<String>,
}

pub(crate) fn parse_source(
    path: &Path,
    byte_limit: usize,
    record_limit: usize,
    normalized_budget: &mut NormalizedRecordBudget,
) -> Result<ParsedSource, LearnError> {
    let source = read_source(path, byte_limit)?;
    let canonical = source.source.canonical_path.clone();
    let mut lines = source.bytes.split_inclusive(|byte| *byte == b'\n');
    let first = lines
        .next()
        .ok_or_else(|| error("diagnose_source_invalid", "Codex rollout is empty"))?;
    if !first.ends_with(b"\n") || first.len() > MAX_RECORD_BYTES {
        return Err(error(
            "diagnose_source_invalid",
            "Codex session metadata record is incomplete or too large",
        ));
    }
    let value: Value = serde_json::from_slice(&first[..first.len() - 1]).map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("invalid Codex session metadata: {e}"),
        )
    })?;
    let mut header = discovery::parse_header(&value)?;
    header.session.source_id = canonical.clone();
    let mut records = Vec::new();
    let mut warnings = Vec::new();
    let mut malformed_records = 0usize;
    let mut omitted_records = 0usize;
    let mut processed_records = 0usize;
    let mut unknown_events = 0usize;
    let mut inherited_events = 0usize;
    let inherited_boundary = header.forked_from_id.clone();
    let mut inherited_remaining = if inherited_boundary.is_some() {
        0
    } else {
        inherited_prefix_count(&header)
    };
    let mut inherited_boundary_seen = inherited_boundary.is_none();
    let mut budget_warning_emitted = false;
    let mut incomplete_tail = source.bytes.last().is_some_and(|byte| *byte != b'\n');
    let mut truncated = source.initial_truncated;
    let mut byte_start = first.len();
    let mut record_index = 1u64;
    let mut turn_cwd = None;
    if source.initial_truncated {
        warnings.push(format!(
            "Codex rollout exceeded the {MAX_SOURCE_BYTES} byte source limit"
        ));
    }
    for line in lines {
        if !line.ends_with(b"\n") {
            incomplete_tail = true;
            omitted_records = omitted_records.saturating_add(1);
            break;
        }
        let raw = &line[..line.len() - 1];
        let start = byte_start;
        byte_start = byte_start.saturating_add(line.len());
        let index = record_index;
        record_index = record_index.saturating_add(1);
        if raw.len() > MAX_RECORD_BYTES {
            malformed_records = malformed_records.saturating_add(1);
            omitted_records = omitted_records.saturating_add(1);
            truncated = true;
            warnings.push(format!("record {index} exceeded the per-record byte limit"));
            continue;
        }
        if raw.is_empty() {
            continue;
        }
        let Ok(value) = serde_json::from_slice::<Value>(raw) else {
            malformed_records = malformed_records.saturating_add(1);
            omitted_records = omitted_records.saturating_add(1);
            warnings.push(format!("record {index} was malformed JSON and was omitted"));
            continue;
        };
        if value.get("type").and_then(Value::as_str) == Some("session_meta") {
            if value.get("payload").is_some_and(|meta| {
                meta.get("history_base").is_some() || meta.get("forked_from_id").is_some()
            }) {
                warnings.push(
                    "rollout contains copied session metadata for an inherited history prefix"
                        .into(),
                );
                truncated = true;
            }
            continue;
        }
        let payload = value.get("payload").unwrap_or(&Value::Null);
        let kind = event_kind(&value);
        if !inherited_boundary_seen {
            inherited_events = inherited_events.saturating_add(1);
            if native_id(&value).as_deref() == inherited_boundary.as_deref() {
                inherited_boundary_seen = true;
            }
            continue;
        }
        if inherited_remaining > 0 {
            inherited_remaining -= 1;
            inherited_events = inherited_events.saturating_add(1);
            continue;
        }
        if kind == "turn_context" {
            turn_cwd = payload
                .get("cwd")
                .and_then(Value::as_str)
                .map(str::to_owned)
                .or(turn_cwd);
        }
        if processed_records >= record_limit {
            omitted_records = omitted_records.saturating_add(1);
            truncated = true;
            warnings.push(format!(
                "Codex rollout exceeded the {record_limit} aggregate record limit"
            ));
            break;
        }
        let anchor = RecordAnchor {
            source_id: canonical.clone(),
            record_index: index,
            byte_start: start as u64,
            byte_end: (start + raw.len()) as u64,
            record_digest: digest(raw),
            native_id: native_id(&value),
            session_id: None,
            storage_sequence: None,
            context_digest: None,
        };
        let mut record = normalize_record(&value, anchor, &header.session.thread_id)?;
        if !known_event_kind(&record.kind) {
            unknown_events = unknown_events.saturating_add(1);
        }
        if record.cwd.is_none() {
            record.cwd = turn_cwd.clone();
        } else if kind == "turn_context" {
            turn_cwd = record.cwd.clone();
        }
        processed_records = processed_records.saturating_add(1);
        if !normalized_budget.try_add(&record) {
            omitted_records = omitted_records.saturating_add(1);
            truncated = true;
            if !budget_warning_emitted {
                warnings.push(
                    "Codex normalized records exceeded the shared snapshot byte budget; records were omitted".into(),
                );
                budget_warning_emitted = true;
            }
            continue;
        }
        records.push(record);
    }
    if incomplete_tail {
        omitted_records = omitted_records.saturating_add(1);
        warnings
            .push("an incomplete final JSONL record was excluded from the verified prefix".into());
    }
    if !inherited_boundary_seen {
        truncated = true;
        warnings.push("forked Codex history boundary was not present in the rollout".into());
    }
    Ok(ParsedSource {
        header,
        source: source.source,
        records,
        processed_records,
        incomplete_tail,
        malformed_records,
        omitted_records,
        unknown_events,
        inherited_events,
        truncated,
        warnings,
    })
}

fn read_source(path: &Path, byte_limit: usize) -> Result<ReadSource, LearnError> {
    let canonical = path.canonicalize().map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("cannot resolve rollout: {e}"),
        )
    })?;
    let mut file = File::open(&canonical).map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("cannot open rollout: {e}"),
        )
    })?;
    let before = file.metadata().map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("cannot stat rollout: {e}"),
        )
    })?;
    if !before.is_file() {
        return Err(error(
            "diagnose_source_invalid",
            "Codex rollout source is not a regular file",
        ));
    }
    let (device, inode, modified_ns) = file_identity(&before);
    let initial_length = before.len();
    let byte_limit = byte_limit.min(MAX_SOURCE_BYTES);
    let limit = initial_length.min(byte_limit as u64) as usize;
    let mut bytes = Vec::with_capacity(limit);
    file.by_ref()
        .take(limit as u64)
        .read_to_end(&mut bytes)
        .map_err(|e| {
            error(
                "diagnose_source_read_failed",
                format!("cannot read Codex rollout: {e}"),
            )
        })?;
    let after = file.metadata().map_err(|e| {
        error(
            "diagnose_source_read_failed",
            format!("cannot restat Codex rollout: {e}"),
        )
    })?;
    let (after_device, after_inode, after_modified_ns) = file_identity(&after);
    if (device, inode) != (after_device, after_inode)
        || after.len() < initial_length
        || (after.len() == initial_length && modified_ns != after_modified_ns)
    {
        return Err(error(
            "diagnose_source_changed",
            "Codex rollout changed while it was being inspected",
        ));
    }
    file.seek(SeekFrom::Start(0)).map_err(|e| {
        error(
            "diagnose_source_read_failed",
            format!("cannot verify Codex rollout: {e}"),
        )
    })?;
    let mut verification = vec![0; bytes.len()];
    file.read_exact(&mut verification).map_err(|e| {
        error(
            "diagnose_source_changed",
            format!("Codex rollout prefix changed while reading: {e}"),
        )
    })?;
    if verification != bytes {
        return Err(error(
            "diagnose_source_changed",
            "Codex rollout prefix changed while it was being inspected",
        ));
    }
    let source = SourceSnapshot {
        source_id: canonical.to_string_lossy().into_owned(),
        canonical_path: canonical.to_string_lossy().into_owned(),
        device,
        inode,
        initial_length,
        captured_length: bytes.len() as u64,
        modified_ns,
        prefix_digest: digest(&bytes),
        harness: Some("codex".into()),
        session_thread_id: None,
        transcript_id: None,
        agent_id: None,
        parent_agent_id: None,
        parent_tool_use_id: None,
        format: Some("codex-jsonl".into()),
        companions: Vec::new(),
    };
    Ok(ReadSource {
        source,
        bytes,
        initial_truncated: initial_length > byte_limit as u64,
    })
}

pub(crate) fn event_kind(value: &Value) -> String {
    let top = value
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let nested = value
        .get("payload")
        .and_then(|payload| payload.get("type"))
        .and_then(Value::as_str);
    match top {
        "event_msg" if nested == Some("item_completed") || nested == Some("item_started") => {
            match value
                .get("payload")
                .and_then(|payload| payload.get("item"))
                .and_then(|item| item.get("type"))
                .and_then(Value::as_str)
            {
                Some("function_call") | Some("custom_tool_call") => "tool_call".into(),
                Some("function_call_output") | Some("custom_tool_call_output") => {
                    "tool_result".into()
                }
                Some("message") => "message".into(),
                _ => nested.unwrap_or(top).to_owned(),
            }
        }
        "event_msg" => nested.unwrap_or(top).to_owned(),
        "response_item" => match nested {
            Some("message") => "message".into(),
            Some("function_call") | Some("custom_tool_call") => "tool_call".into(),
            Some("function_call_output") | Some("custom_tool_call_output") => "tool_result".into(),
            Some(other) => other.into(),
            None => top.into(),
        },
        other => other.into(),
    }
}

fn known_event_kind(kind: &str) -> bool {
    matches!(
        kind,
        "message"
            | "tool_call"
            | "tool_result"
            | "turn_context"
            | "turn_failed"
            | "turn_aborted"
            | "turn_started"
            | "task_started"
            | "task_complete"
            | "item_started"
            | "item_completed"
            | "token_count"
            | "token_usage_record"
            | "compacted"
            | "warning"
            | "error"
            | "reasoning"
            | "agent_message"
            | "web_search_call"
            | "mcp_tool_call"
            | "custom_tool_call"
            | "session_meta"
    )
}

fn inherited_prefix_count(header: &Header) -> usize {
    header
        .history_base
        .as_ref()
        .and_then(|value| {
            value.as_u64().or_else(|| {
                ["inherited_events", "event_count", "record_count"]
                    .iter()
                    .find_map(|key| value.get(key).and_then(Value::as_u64))
            })
        })
        .unwrap_or(0)
        .min(usize::MAX as u64) as usize
}

pub(crate) fn native_id(value: &Value) -> Option<String> {
    value
        .get("payload")
        .and_then(|payload| payload.get("id"))
        .and_then(Value::as_str)
        .or_else(|| {
            value
                .get("payload")
                .and_then(|payload| payload.get("response_id"))
                .and_then(Value::as_str)
        })
        .or_else(|| value.get("id").and_then(Value::as_str))
        .map(str::to_owned)
}

pub(crate) fn normalize_record(
    value: &Value,
    anchor: RecordAnchor,
    thread_id: &str,
) -> Result<EvidenceRecord, LearnError> {
    let payload = value.get("payload").unwrap_or(&Value::Null);
    let kind = event_kind(value);
    let item = payload
        .get("item")
        .filter(|value| value.is_object())
        .unwrap_or(payload);
    let role = payload
        .get("role")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let text_excerpt = if kind == "message" {
        message_excerpt(payload)
    } else {
        None
    };
    let failure_reason = if kind == "turn_failed" || kind.contains("error") {
        payload
            .get("reason")
            .or_else(|| payload.get("message"))
            .and_then(Value::as_str)
            .map(|text| bounded_text(text, 256))
    } else {
        None
    };
    let usage_total = payload
        .get("info")
        .and_then(|info| info.get("total_token_usage"))
        .and_then(usage_object);
    let usage_last = payload
        .get("info")
        .and_then(|info| info.get("last_token_usage"))
        .and_then(usage_object);
    let compacted_before_tokens = payload.get("tokens_before").and_then(Value::as_u64);
    let tool_name = item
        .get("name")
        .or_else(|| item.get("tool_name"))
        .and_then(Value::as_str)
        .map(|name| bounded_text(name, 128));
    let (tool_input_excerpt, input_truncated) =
        excerpt_value(item.get("arguments").or_else(|| item.get("input")), 1_024);
    let (tool_output_excerpt, output_truncated) =
        excerpt_value(item.get("output").or_else(|| item.get("content")), 1_024);
    let (tool_error, error_truncated) =
        excerpt_value(item.get("error").or_else(|| payload.get("error")), 512);
    let tool_status = item
        .get("status")
        .or_else(|| payload.get("status"))
        .and_then(Value::as_str)
        .map(|status| bounded_text(status, 64));
    let response_id = payload
        .get("response_id")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let turn_id = payload
        .get("turn_id")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let usage_record = if value.get("type").and_then(Value::as_str) == Some("token_usage_record") {
        usage_record(payload)
    } else {
        None
    };
    let known = known_event_kind(&kind);
    let (unknown_payload_excerpt, unknown_truncated) = if known {
        (None, false)
    } else {
        excerpt_value(Some(payload), 512)
    };
    Ok(EvidenceRecord {
        session_thread_id: thread_id.into(),
        anchor,
        timestamp: value
            .get("timestamp")
            .and_then(Value::as_str)
            .or_else(|| payload.get("timestamp").and_then(Value::as_str))
            .map(str::to_owned),
        kind,
        role,
        text_excerpt,
        tool_name,
        tool_input_excerpt,
        tool_output_excerpt,
        tool_status,
        tool_error,
        tool_observations: Vec::new(),
        detail_truncated: input_truncated
            || output_truncated
            || error_truncated
            || unknown_truncated,
        unknown_payload_excerpt,
        turn_id,
        response_id,
        cwd: payload
            .get("cwd")
            .and_then(Value::as_str)
            .map(str::to_owned),
        git_head: None,
        failure_reason,
        compacted_before_tokens,
        usage_total,
        usage_last,
        usage_record,
        transcript_id: None,
        provider_message_id: None,
        agent_id: None,
        parent_agent_id: None,
        parent_native_id: None,
        tool_use_id: None,
        parent_tool_use_id: None,
        is_sidechain: None,
        is_meta: None,
        is_compact_summary: None,
        timestamp_raw: None,
        session_location: None,
        location_provenance: None,
    })
}

fn message_excerpt(payload: &Value) -> Option<String> {
    let content = payload.get("content")?.as_array()?;
    let joined = content
        .iter()
        .filter_map(|part| {
            part.get("text")
                .or_else(|| part.get("input_text"))
                .and_then(Value::as_str)
        })
        .collect::<Vec<_>>()
        .join(" ");
    (!joined.is_empty()).then(|| bounded_text(&joined, MAX_TEXT_EXCERPT))
}

fn usage_object(value: &Value) -> Option<Value> {
    let object = value.as_object()?;
    let allowed = [
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    ];
    let values = allowed
        .into_iter()
        .filter_map(|key| {
            object
                .get(key)
                .filter(|value| value.is_number())
                .map(|value| (key.to_owned(), value.clone()))
        })
        .collect::<serde_json::Map<_, _>>();
    (!values.is_empty()).then_some(Value::Object(values))
}

pub(crate) fn context_occupancy(record: &Value) -> Option<u64> {
    let value = record
        .pointer("/payload/info/last_token_usage")
        .and_then(usage_object)?;
    value.get("input_tokens")?.as_u64()
}

fn usage_record(payload: &Value) -> Option<Value> {
    let mut record = serde_json::Map::new();
    for key in [
        "thread_id",
        "turn_id",
        "session_id",
        "root_turn_id",
        "response_id",
    ] {
        if let Some(value) = payload.get(key).filter(|value| value.is_string()) {
            record.insert(key.to_owned(), value.clone());
        }
    }
    for key in ["usage", "turn_token_usage", "thread_token_usage"] {
        if let Some(value) = payload.get(key).and_then(usage_object) {
            record.insert(key.to_owned(), value);
        }
    }
    (!record.is_empty()).then_some(Value::Object(record))
}

fn excerpt_value(value: Option<&Value>, limit: usize) -> (Option<String>, bool) {
    let Some(value) = value else {
        return (None, false);
    };
    if value.is_null() {
        return (None, false);
    }
    let serialized = if let Some(text) = value.as_str() {
        text.to_owned()
    } else {
        value.to_string()
    };
    let truncated = serialized.chars().count() > limit;
    (Some(bounded_text(&serialized, limit)), truncated)
}

pub(crate) fn bounded_text(text: &str, limit: usize) -> String {
    let mut output = String::new();
    for character in text.chars().take(limit) {
        output.push(character);
    }
    if text.chars().count() > limit {
        output.push('…');
    }
    output
}
