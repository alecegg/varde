use std::collections::{HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};

use serde_json::Value;

use super::super::{
    ChildSession, Coverage, CurrentOverlap, DiscoveredSession, GitMetadata, InspectionSnapshot,
    MAX_DISCOVERY_FILES, MAX_FAMILY, MAX_FAMILY_SOURCE_BYTES, MAX_LIST_DISCOVERY_BYTES,
    MAX_RECORD_BYTES, MAX_RECORDS, MAX_SOURCE_BYTES, MAX_WARNINGS, NormalizedRecordBudget,
    SessionMetadata, build_snapshot, error, is_retro_analyst,
};
use super::events;
use crate::LearnError;

const MAX_LIST_METADATA_BYTES: usize = 96 * 1024 * 1024;
const MAX_DISCOVERY_FILE_BYTES: usize = 16 * 1024 * 1024;

#[derive(Debug)]
pub(crate) struct Header {
    pub(crate) session: SessionMetadata,
    pub(crate) forked_from_id: Option<String>,
    pub(crate) history_base: Option<Value>,
    pub(crate) parent_link_known: bool,
}

pub(crate) struct Discovery {
    pub(crate) sessions: Vec<(PathBuf, Header)>,
    pub(crate) truncated: bool,
    pub(crate) uncertain: bool,
    pub(crate) limit: Option<DiscoveryLimit>,
    pub(crate) skipped_headers: usize,
    pub(crate) skipped_entries: usize,
}

pub(crate) struct ListDiscovery {
    pub(crate) sessions: Vec<DiscoveredSession>,
    pub(crate) warnings: Vec<String>,
    pub(crate) has_readable_source: bool,
    pub(crate) archived: std::collections::HashSet<String>,
    pub(crate) tool_call_results: std::collections::HashMap<String, Vec<String>>,
}

#[derive(Clone, Copy)]
pub(crate) enum DiscoveryLimit {
    Entries,
    Bytes,
    RecordBytes,
}

pub(crate) fn inspect_id(home: &Path, thread_id: &str) -> Result<InspectionSnapshot, LearnError> {
    let discovery = scan_sessions(home)?;
    if discovery.truncated || discovery.uncertain {
        let reason = match discovery.limit {
            Some(DiscoveryLimit::Bytes) => format!(
                "Codex session listing exhausted its {} MiB metadata budget",
                MAX_LIST_METADATA_BYTES / (1024 * 1024)
            ),
            Some(DiscoveryLimit::Entries) => format!(
                "Codex session discovery exceeded the {MAX_DISCOVERY_FILES} entry scan limit; use --path"
            ),
            Some(DiscoveryLimit::RecordBytes) => format!(
                "Codex session discovery reached its {} KiB per-file header read limit; use --path",
                MAX_RECORD_BYTES / 1024
            ),
            None => "Codex session metadata was incomplete or could not be verified; use --path"
                .to_owned(),
        };
        return Err(error("diagnose_discovery_incomplete", reason));
    }
    let matches = discovery
        .sessions
        .iter()
        .filter(|(_, header)| header.session.thread_id == thread_id)
        .collect::<Vec<_>>();
    let [(path, _)] = matches.as_slice() else {
        return Err(if matches.is_empty() {
            error(
                "diagnose_session_not_found",
                format!("Codex thread `{thread_id}` was not found"),
            )
        } else {
            error(
                "diagnose_session_ambiguous",
                format!("multiple Codex rollouts identify thread `{thread_id}`; use --path"),
            )
        });
    };
    inspect_path_with_family(home, path, &discovery)
}

pub(crate) fn list_sessions(home: &Path, repo: &Path) -> Result<ListDiscovery, LearnError> {
    let discovery = scan_sessions_for_list(home)?;
    let has_readable_source = !discovery.sessions.is_empty();
    let mut warnings = Vec::new();
    match discovery.limit {
        Some(DiscoveryLimit::Entries) => warnings.push(format!(
            "Codex discovery reached the {MAX_DISCOVERY_FILES}-entry scan limit; remaining rollouts were skipped"
        )),
        Some(DiscoveryLimit::Bytes) => warnings.push(format!(
            "Codex metadata discovery reached its {} MiB byte limit; remaining rollouts were skipped",
            MAX_LIST_METADATA_BYTES / (1024 * 1024)
        )),
        Some(DiscoveryLimit::RecordBytes) => warnings.push(format!(
            "Codex discovery skipped rollout headers over its {} KiB per-file read limit",
            MAX_RECORD_BYTES / 1024
        )),
        None => {}
    }
    if discovery.skipped_headers > 0 {
        warnings.push(format!(
            "Codex discovery skipped {} rollout files with unreadable, malformed, oversized, or incomplete metadata headers",
            discovery.skipped_headers
        ));
    }
    if discovery.skipped_entries > 0 {
        warnings.push(format!(
            "Codex discovery skipped {} entries it could not inspect",
            discovery.skipped_entries
        ));
    }
    if discovery.uncertain && warnings.is_empty() {
        warnings.push(
            "Codex discovery skipped entries it could not verify; coverage is partial".into(),
        );
    }
    let mut first_user_bytes = 0usize;
    let mut sessions = Vec::with_capacity(discovery.sessions.len());
    let mut archived = std::collections::HashSet::new();
    let mut tool_call_results = std::collections::HashMap::new();
    let mut tool_results_bytes = 0usize;
    let mut skipped_first_user_records = 0usize;
    let mut first_user_budget_exhausted = false;
    for (path, header) in discovery.sessions {
        if !header
            .session
            .cwd
            .as_deref()
            .is_some_and(|cwd| super::super::list::cwd_is_in_repo(cwd, repo))
        {
            continue;
        }
        let (first_user, bytes_read) = first_user_analyst(&path);
        let next_bytes = first_user_bytes.saturating_add(bytes_read);
        if next_bytes > MAX_LIST_DISCOVERY_BYTES {
            first_user_budget_exhausted = true;
            break;
        }
        first_user_bytes = next_bytes;
        let retro_analyst = match first_user {
            Ok(retro_analyst) => retro_analyst,
            Err(_) => {
                skipped_first_user_records += 1;
                continue;
            }
        };
        let session = header.session;
        let identity = format!("codex:{}", session.thread_id);
        if path.starts_with(home.join("sessions/archived")) {
            archived.insert(identity.clone());
        }
        let remaining = MAX_LIST_DISCOVERY_BYTES.saturating_sub(tool_results_bytes);
        let (results, bytes_read) = read_tool_call_results(&path, remaining);
        tool_results_bytes = tool_results_bytes.saturating_add(bytes_read);
        if !results.is_empty() {
            tool_call_results.insert(session.thread_id.clone(), results);
        }
        let parent_identity = session
            .parent_thread_id
            .as_deref()
            .map(|parent| format!("codex:{parent}"));
        let mut aliases = vec![session.thread_id.clone()];
        if let Some(session_id) = session.session_id.as_ref()
            && !aliases.contains(session_id)
        {
            aliases.push(session_id.clone());
        }
        sessions.push(DiscoveredSession {
            harness: "codex",
            identity,
            session_id: session.thread_id,
            aliases,
            parent_identity,
            parent_known: header.parent_link_known,
            started_at: session.started_at,
            cwd: session.cwd,
            retro_analyst,
        });
    }
    if tool_results_bytes >= MAX_LIST_DISCOVERY_BYTES {
        warnings.push(format!(
            "Codex tool-result linkage reached its {} MiB scan limit; remaining workers may be unlinked",
            MAX_LIST_DISCOVERY_BYTES / (1024 * 1024)
        ));
    }
    if skipped_first_user_records > 0 {
        warnings.push(format!(
            "Codex discovery skipped {skipped_first_user_records} rollouts because their first user record was unreadable, malformed, oversized, or incomplete"
        ));
    }
    if first_user_budget_exhausted {
        warnings.push(format!(
            "Codex discovery reached its {} MiB first-user scan limit; remaining repo rollouts were skipped",
            MAX_LIST_DISCOVERY_BYTES / (1024 * 1024)
        ));
    }
    Ok(ListDiscovery {
        sessions,
        warnings,
        has_readable_source,
        archived,
        tool_call_results,
    })
}

fn read_tool_call_results(path: &Path, byte_limit: usize) -> (Vec<String>, usize) {
    if byte_limit == 0 {
        return (Vec::new(), 0);
    }
    let Ok(file) = File::open(path) else {
        return (Vec::new(), 0);
    };
    let byte_limit = byte_limit.min(MAX_DISCOVERY_FILE_BYTES);
    let mut reader = BufReader::new(file).take(byte_limit as u64);
    let mut results = Vec::new();
    let mut line = Vec::new();
    let mut bytes_read = 0usize;
    while let Ok(count) = reader.read_until(b'\n', &mut line) {
        if count == 0 {
            break;
        }
        bytes_read = bytes_read.saturating_add(count);
        if line.len() > MAX_RECORD_BYTES {
            line.clear();
            continue;
        }
        let Ok(value) = serde_json::from_slice::<Value>(&line[..line.len().saturating_sub(1)])
        else {
            line.clear();
            continue;
        };
        let payload = value.get("payload").unwrap_or(&value);
        if matches!(
            payload.get("type").and_then(Value::as_str),
            Some("function_call_output" | "custom_tool_call_output")
        ) {
            if let Some(output) = payload.get("output").or_else(|| payload.get("content")) {
                let evidence = output
                    .as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| output.to_string());
                results.push(evidence);
            }
        }
        line.clear();
    }
    (results, bytes_read)
}

fn first_user_analyst(path: &Path) -> (Result<bool, LearnError>, usize) {
    let mut bytes_read = 0usize;
    let result = (|| {
        let file = File::open(path).map_err(|cause| {
            error(
                "diagnose_source_invalid",
                format!("cannot read Codex session prompt: {cause}"),
            )
        })?;
        let mut reader = BufReader::new(file).take((MAX_DISCOVERY_FILE_BYTES + 1) as u64);
        let mut line = Vec::new();
        loop {
            line.clear();
            let count = reader.read_until(b'\n', &mut line).map_err(|cause| {
                error(
                    "diagnose_source_invalid",
                    format!("cannot read Codex session prompt: {cause}"),
                )
            })?;
            if count == 0 {
                return Ok(false);
            }
            bytes_read = bytes_read.saturating_add(count);
            if bytes_read > MAX_DISCOVERY_FILE_BYTES || line.len() > MAX_RECORD_BYTES {
                return Err(error(
                    "diagnose_discovery_incomplete",
                    "Codex first-user record exceeded its byte bound",
                ));
            }
            if !line.ends_with(b"\n") {
                return Err(error(
                    "diagnose_discovery_incomplete",
                    "Codex first-user record was incomplete",
                ));
            }
            let value: Value =
                serde_json::from_slice(&line[..line.len() - 1]).map_err(|cause| {
                    error(
                        "diagnose_discovery_incomplete",
                        format!("cannot parse Codex record before the first user record: {cause}"),
                    )
                })?;
            if let Some(text) = codex_user_text(&value) {
                return Ok(is_retro_analyst(text));
            }
        }
    })();
    (result, bytes_read)
}

fn codex_user_text(value: &Value) -> Option<&str> {
    let payload = value.get("payload")?;
    if payload.get("type").and_then(Value::as_str) != Some("message")
        || payload.get("role").and_then(Value::as_str) != Some("user")
    {
        return None;
    }
    Some(
        payload
            .get("content")
            .and_then(first_content_text)
            .unwrap_or_default(),
    )
}

fn first_content_text(content: &Value) -> Option<&str> {
    content.as_str().or_else(|| {
        content
            .as_array()?
            .iter()
            .find_map(|part| part.get("text").and_then(Value::as_str))
    })
}

pub(crate) fn inspect_path(home: &Path, path: &Path) -> Result<InspectionSnapshot, LearnError> {
    let discovery = scan_sessions(home).unwrap_or(Discovery {
        sessions: Vec::new(),
        truncated: true,
        uncertain: true,
        limit: None,
        skipped_headers: 0,
        skipped_entries: 0,
    });
    inspect_path_with_family(home, path, &discovery)
}

fn inspect_path_with_family(
    home: &Path,
    path: &Path,
    discovery: &Discovery,
) -> Result<InspectionSnapshot, LearnError> {
    let mut normalized_budget = NormalizedRecordBudget::new();
    let mut selected =
        events::parse_source(path, MAX_SOURCE_BYTES, MAX_RECORDS, &mut normalized_budget)?;
    let thread_id = selected.header.session.thread_id.clone();
    let current = std::env::var("CODEX_THREAD_ID")
        .ok()
        .filter(|value| !value.trim().is_empty());
    let (mut descendants, family_ambiguous) = discover_descendants(&thread_id, &discovery.sessions);
    let family_truncated = descendants.len() > MAX_FAMILY;
    descendants.truncate(MAX_FAMILY);
    let mut child_sessions = Vec::new();
    let mut sources = vec![selected.source.clone()];
    let mut records = std::mem::take(&mut selected.records);
    let mut warnings = selected.warnings.clone();
    let mut incomplete_tail = selected.incomplete_tail;
    let mut malformed_records = selected.malformed_records;
    let mut omitted_records = selected.omitted_records;
    let mut unknown_events = selected.unknown_events;
    let mut inherited_events = selected.inherited_events;
    let mut processed_records = selected.processed_records;
    let mut truncated = selected.truncated;
    let mut complete =
        !selected.incomplete_tail && selected.malformed_records == 0 && !selected.truncated;
    let discovery_truncated = discovery.truncated || discovery.uncertain;
    let mut family_linkage_uncertain = discovery_truncated || family_ambiguous;
    let mut family_bytes_used = selected.source.captured_length as usize;

    if family_ambiguous {
        complete = false;
        warnings.push("multiple Codex rollouts identify a linked child thread; ambiguous child branches were omitted".into());
    }

    if selected.inherited_events == 0
        && (selected.header.forked_from_id.is_some()
            || selected.header.history_base.is_some()
            || selected
                .header
                .session
                .history_mode
                .as_deref()
                .is_some_and(|mode| mode != "full"))
    {
        complete = false;
        warnings.push("Codex rollout has inherited or forked history metadata; physical records may not represent a complete independent history".into());
    }
    if family_truncated {
        complete = false;
        truncated = true;
        family_linkage_uncertain = true;
        warnings.push(format!(
            "linked child family exceeded the {MAX_FAMILY} child limit"
        ));
    }
    if discovery_truncated {
        complete = false;
        truncated = true;
        let warning = match discovery.limit {
            Some(DiscoveryLimit::Bytes) => format!(
                "Codex metadata discovery exhausted its {} MiB byte budget; linked-child coverage is partial",
                MAX_LIST_METADATA_BYTES / (1024 * 1024)
            ),
            Some(DiscoveryLimit::Entries) =>
                "Codex metadata discovery reached its entry scan limit; linked-child coverage is partial".to_owned(),
            Some(DiscoveryLimit::RecordBytes) => format!(
                "Codex metadata discovery skipped a header over its {} KiB per-file read limit; linked-child coverage is partial",
                MAX_RECORD_BYTES / 1024
            ),
            None => "Codex metadata discovery omitted or could not verify one or more entries; linked-child coverage is partial".to_owned(),
        };
        warnings.push(warning);
    }

    for (child_path, header, expected_parent) in descendants {
        let remaining_bytes = MAX_FAMILY_SOURCE_BYTES.saturating_sub(family_bytes_used);
        let remaining_records = MAX_RECORDS.saturating_sub(processed_records);
        if remaining_bytes == 0 || remaining_records == 0 {
            complete = false;
            truncated = true;
            warnings.push("linked-child family reached its aggregate byte or record limit".into());
            continue;
        }
        let child_limit = remaining_bytes.min(MAX_SOURCE_BYTES);
        let consumed_bytes = fs::metadata(&child_path)
            .ok()
            .map(|metadata| metadata.len().min(child_limit as u64) as usize)
            .unwrap_or(child_limit);
        family_bytes_used = family_bytes_used.saturating_add(consumed_bytes);
        let Ok(child) = events::parse_source(
            &child_path,
            child_limit,
            remaining_records,
            &mut normalized_budget,
        ) else {
            complete = false;
            family_linkage_uncertain = true;
            warnings.push("a linked child rollout could not be read".into());
            continue;
        };
        if !child_header_matches(&child.header, header, &expected_parent) {
            complete = false;
            family_linkage_uncertain = true;
            warnings.push(
                "a linked child rollout changed identity or parent relationship during inspection"
                    .into(),
            );
            continue;
        }
        if child.inherited_events == 0
            && (child.header.forked_from_id.is_some()
                || child.header.history_base.is_some()
                || child
                    .header
                    .session
                    .history_mode
                    .as_deref()
                    .is_some_and(|mode| mode != "full"))
        {
            complete = false;
            warnings.push(format!(
                "linked child `{}` has inherited or forked history metadata; physical records may not represent a complete independent history",
                child.header.session.thread_id
            ));
        }
        child_sessions.push(ChildSession {
            thread_id: child.header.session.thread_id.clone(),
            source_id: child.source.source_id.clone(),
            parent_thread_id: child.header.session.parent_thread_id.clone(),
            started_at: child.header.session.started_at.clone(),
            relationship_evidence: child
                .header
                .session
                .parent_provenance
                .clone()
                .unwrap_or_else(|| "session_meta.parent_thread_id".into()),
            transcript_id: None,
            agent_id: None,
            parent_agent_id: None,
            parent_tool_use_id: None,
            fork_session_id: None,
            fork_boundary: None,
        });
        sources.push(child.source.clone());
        records.extend(child.records);
        incomplete_tail |= child.incomplete_tail;
        malformed_records = malformed_records.saturating_add(child.malformed_records);
        omitted_records = omitted_records.saturating_add(child.omitted_records);
        unknown_events = unknown_events.saturating_add(child.unknown_events);
        inherited_events = inherited_events.saturating_add(child.inherited_events);
        processed_records = processed_records.saturating_add(child.processed_records);
        truncated |= child.truncated;
        if child.incomplete_tail || child.malformed_records > 0 || child.truncated {
            complete = false;
        }
        warnings.extend(child.warnings);
    }
    if unknown_events > 0 {
        warnings
            .push("unknown Codex event types were retained as bounded excerpts and counted".into());
    }
    if sources.len() > MAX_FAMILY + 1 {
        sources.truncate(MAX_FAMILY + 1);
        complete = false;
        truncated = true;
    }
    if records.len() > MAX_RECORDS {
        omitted_records = omitted_records.saturating_add(records.len() - MAX_RECORDS);
        records.truncate(MAX_RECORDS);
        complete = false;
        truncated = true;
        warnings.push(format!("evidence exceeded the {MAX_RECORDS} record limit"));
    }

    if !home.join("sessions").is_dir() {
        complete = false;
        family_linkage_uncertain = true;
        warnings.push(
            "Codex session directory was unavailable; linked-child coverage is unknown".into(),
        );
    }

    if warnings.len() > MAX_WARNINGS {
        warnings.truncate(MAX_WARNINGS - 1);
        warnings.push("additional coverage warnings were omitted at the warning limit".into());
    }

    let family_thread_ids = std::iter::once(thread_id.as_str())
        .chain(child_sessions.iter().map(|child| child.thread_id.as_str()))
        .collect::<HashSet<_>>();
    let overlap = match current.as_deref() {
        Some(current) if family_thread_ids.contains(current) => CurrentOverlap::Current,
        Some(_) if family_linkage_uncertain => CurrentOverlap::Unknown,
        Some(_) => CurrentOverlap::NotCurrent,
        None => CurrentOverlap::Unknown,
    };
    let source_complete = complete;
    let analysis_ready =
        source_complete && !matches!(overlap, CurrentOverlap::Current | CurrentOverlap::Unknown);
    let coverage = Coverage {
        complete,
        source_complete,
        analysis_ready,
        cutoff_verified: false,
        cutoff_anchor: None,
        incomplete_tail,
        truncated,
        record_count: records.len(),
        malformed_records,
        omitted_records,
        unknown_events,
        inherited_events,
        warnings,
    };
    build_snapshot(
        selected.header.session,
        child_sessions,
        sources,
        records,
        overlap,
        coverage,
    )
}

pub(crate) fn scan_sessions(home: &Path) -> Result<Discovery, LearnError> {
    scan_sessions_with_policy(home, true, None)
}

pub(crate) fn scan_sessions_for_list(home: &Path) -> Result<Discovery, LearnError> {
    scan_sessions_with_policy(home, false, Some(MAX_LIST_METADATA_BYTES))
}

fn scan_sessions_with_policy(
    home: &Path,
    require_known_version: bool,
    max_discovery_bytes: Option<usize>,
) -> Result<Discovery, LearnError> {
    let root = home.join("sessions");
    let Ok(metadata) = fs::symlink_metadata(&root) else {
        return Ok(Discovery {
            sessions: Vec::new(),
            truncated: false,
            uncertain: false,
            limit: None,
            skipped_headers: 0,
            skipped_entries: 0,
        });
    };
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(error(
            "diagnose_discovery_invalid",
            "Codex sessions path is not a real directory",
        ));
    }
    let mut stack = vec![(root, 0usize)];
    let mut output = Vec::new();
    let mut scanned = 0usize;
    let mut metadata_bytes = 0usize;
    let mut truncated = false;
    let mut uncertain = false;
    let mut skipped_headers = 0usize;
    let mut skipped_entries = 0usize;
    while let Some((directory, depth)) = stack.pop() {
        if depth > 8 {
            truncated = true;
            uncertain = true;
            skipped_entries += 1;
            continue;
        }
        let entries = fs::read_dir(&directory).map_err(|e| {
            error(
                "diagnose_discovery_failed",
                format!("cannot scan Codex sessions: {e}"),
            )
        })?;
        for entry in entries {
            scanned += 1;
            if scanned > MAX_DISCOVERY_FILES {
                return Ok(Discovery {
                    sessions: output,
                    truncated: true,
                    uncertain,
                    limit: Some(DiscoveryLimit::Entries),
                    skipped_headers,
                    skipped_entries,
                });
            }
            let Ok(entry) = entry else {
                uncertain = true;
                skipped_entries += 1;
                continue;
            };
            let path = entry.path();
            let Ok(file_type) = entry.file_type() else {
                uncertain = true;
                skipped_entries += 1;
                continue;
            };
            if file_type.is_symlink() {
                uncertain = true;
                skipped_entries += 1;
                continue;
            }
            if file_type.is_dir() {
                stack.push((path, depth + 1));
                continue;
            }
            if !file_type.is_file() {
                uncertain = true;
                skipped_entries += 1;
                continue;
            }
            if path.extension().and_then(|value| value.to_str()) != Some("jsonl")
                || !path
                    .file_name()
                    .and_then(|value| value.to_str())
                    .is_some_and(|name| name.starts_with("rollout-"))
            {
                continue;
            }
            let remaining_bytes =
                max_discovery_bytes.map(|limit| limit.saturating_sub(metadata_bytes));
            if remaining_bytes == Some(0) {
                return Ok(Discovery {
                    sessions: output,
                    truncated: true,
                    uncertain: true,
                    limit: Some(DiscoveryLimit::Bytes),
                    skipped_headers,
                    skipped_entries,
                });
            }
            let per_file_limit = remaining_bytes
                .unwrap_or(MAX_RECORD_BYTES + 1)
                .min(MAX_RECORD_BYTES + 1);
            let (header, bytes_read) = read_header(&path, per_file_limit, require_known_version);
            if max_discovery_bytes.is_some() {
                metadata_bytes = metadata_bytes.saturating_add(bytes_read);
            }
            match header {
                Ok(header) => {
                    output.push((path, header));
                }
                Err(_) => {
                    uncertain = true;
                    skipped_headers += 1;
                    if bytes_read > MAX_RECORD_BYTES && max_discovery_bytes.is_none() {
                        return Ok(Discovery {
                            sessions: output,
                            truncated: true,
                            uncertain: true,
                            limit: Some(DiscoveryLimit::RecordBytes),
                            skipped_headers,
                            skipped_entries,
                        });
                    }
                    if remaining_bytes.is_some_and(|limit| bytes_read == limit) {
                        return Ok(Discovery {
                            sessions: output,
                            truncated: true,
                            uncertain: true,
                            limit: Some(DiscoveryLimit::Bytes),
                            skipped_headers,
                            skipped_entries,
                        });
                    }
                }
            }
        }
    }
    Ok(Discovery {
        sessions: output,
        truncated,
        uncertain,
        limit: None,
        skipped_headers,
        skipped_entries,
    })
}

pub(crate) fn read_header(
    path: &Path,
    byte_limit: usize,
    require_known_version: bool,
) -> (Result<Header, LearnError>, usize) {
    let mut bytes_read = 0usize;
    let result = (|| {
        let canonical = path.canonicalize().map_err(|e| {
            error(
                "diagnose_source_invalid",
                format!("cannot resolve rollout: {e}"),
            )
        })?;
        let file = File::open(&canonical).map_err(|e| {
            error(
                "diagnose_source_invalid",
                format!("cannot open rollout: {e}"),
            )
        })?;
        let read_limit = byte_limit.min(MAX_RECORD_BYTES + 1) as u64;
        let mut reader = BufReader::new(file.take(read_limit));
        let mut line = Vec::new();
        let read_result = reader.read_until(b'\n', &mut line);
        bytes_read = (read_limit - reader.get_ref().limit()) as usize;
        read_result.map_err(|e| {
            error(
                "diagnose_source_invalid",
                format!("cannot read rollout header: {e}"),
            )
        })?;
        if line.len() > MAX_RECORD_BYTES || !line.ends_with(b"\n") {
            return Err(error(
                "diagnose_source_invalid",
                "Codex session metadata exceeds the header limit or remaining discovery byte budget",
            ));
        }
        let value: Value = serde_json::from_slice(&line[..line.len() - 1]).map_err(|e| {
            error(
                "diagnose_source_invalid",
                format!("invalid Codex session metadata: {e}"),
            )
        })?;
        if require_known_version {
            parse_header(&value)
        } else {
            parse_list_header(&value)
        }
    })();
    (result, bytes_read)
}

pub(crate) fn parse_header(value: &Value) -> Result<Header, LearnError> {
    parse_header_with_version_policy(value, true)
}

fn parse_list_header(value: &Value) -> Result<Header, LearnError> {
    parse_header_with_version_policy(value, false)
}

fn parse_header_with_version_policy(
    value: &Value,
    require_known_version: bool,
) -> Result<Header, LearnError> {
    if value.get("type").and_then(Value::as_str) != Some("session_meta") {
        return Err(error(
            "diagnose_source_unsupported",
            "first Codex rollout record is not session_meta",
        ));
    }
    let payload = value
        .get("payload")
        .and_then(Value::as_object)
        .ok_or_else(|| {
            error(
                "diagnose_source_invalid",
                "Codex session metadata payload is missing",
            )
        })?;
    let thread_id = payload
        .get("id")
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| {
            error(
                "diagnose_source_invalid",
                "Codex canonical thread ID is missing",
            )
        })?
        .to_owned();
    let cli_version = payload
        .get("cli_version")
        .and_then(Value::as_str)
        .filter(|version| !version.trim().is_empty())
        .map(str::to_owned);
    if cli_version.is_none()
        || (require_known_version && !cli_version.as_deref().is_some_and(known_codex_version))
    {
        return Err(error(
            "diagnose_codex_version_unsupported",
            format!(
                "Codex rollout version {cli_version:?} is not in the verified native reader set"
            ),
        ));
    }
    let source_parent = payload
        .get("source")
        .and_then(|value| value.get("subagent"))
        .and_then(|value| value.get("thread_spawn"))
        .and_then(|value| value.get("parent_thread_id"))
        .and_then(Value::as_str);
    let source_parent_present = payload
        .get("source")
        .and_then(|value| value.get("subagent"))
        .and_then(|value| value.get("thread_spawn"))
        .and_then(|value| value.get("parent_thread_id"))
        .is_some_and(|value| value.is_null() || value.is_string());
    let direct_parent = payload.get("parent_thread_id").and_then(Value::as_str);
    let parent_link_known = payload
        .get("parent_thread_id")
        .is_some_and(|value| value.is_null() || value.is_string())
        || source_parent_present;
    if direct_parent.is_some() && source_parent.is_some() && direct_parent != source_parent {
        return Err(error(
            "diagnose_source_invalid",
            "Codex parent thread metadata conflicts between session_meta fields",
        ));
    }
    let parent_thread_id = direct_parent.or(source_parent).map(str::to_owned);
    let parent_provenance = match (direct_parent, source_parent) {
        (Some(_), Some(_)) => Some(
            "session_meta.parent_thread_id+source.subagent.thread_spawn.parent_thread_id".into(),
        ),
        (Some(_), None) => Some("session_meta.parent_thread_id".into()),
        (None, Some(_)) => {
            Some("session_meta.source.subagent.thread_spawn.parent_thread_id".into())
        }
        (None, None) => None,
    };
    let git = payload
        .get("git")
        .and_then(Value::as_object)
        .map(|git| GitMetadata {
            commit_hash: git
                .get("commit_hash")
                .and_then(Value::as_str)
                .map(str::to_owned),
            branch: git.get("branch").and_then(Value::as_str).map(str::to_owned),
            repository_url: git
                .get("repository_url")
                .and_then(Value::as_str)
                .map(str::to_owned),
        });
    Ok(Header {
        session: SessionMetadata {
            harness: "codex".into(),
            thread_id,
            session_id: payload
                .get("session_id")
                .and_then(Value::as_str)
                .map(str::to_owned),
            parent_thread_id,
            parent_provenance,
            started_at: payload
                .get("timestamp")
                .and_then(Value::as_str)
                .or_else(|| value.get("timestamp").and_then(Value::as_str))
                .map(str::to_owned),
            cwd: payload
                .get("cwd")
                .and_then(Value::as_str)
                .map(str::to_owned),
            cli_version,
            history_mode: payload
                .get("history_mode")
                .and_then(Value::as_str)
                .map(str::to_owned),
            git,
            source_id: String::new(),
            transcript_id: None,
            project_namespace: None,
            agent_id: None,
            parent_agent_id: None,
            parent_tool_use_id: None,
            current_directory: None,
            fork_session_id: None,
            fork_boundary: None,
        },
        forked_from_id: payload
            .get("forked_from_id")
            .and_then(Value::as_str)
            .map(str::to_owned),
        history_base: payload.get("history_base").cloned(),
        parent_link_known,
    })
}

pub(crate) fn verified_header_identity(
    value: &Value,
) -> Result<(String, Option<String>, bool), LearnError> {
    let header = parse_header(value)?;
    let inherited = header.forked_from_id.is_some()
        || header.history_base.is_some()
        || header
            .session
            .history_mode
            .as_deref()
            .is_some_and(|mode| mode != "full");
    Ok((
        header.session.thread_id,
        header.session.parent_thread_id,
        inherited,
    ))
}

fn known_codex_version(version: &str) -> bool {
    version
        .split(['-', '+'])
        .next()
        .is_some_and(|version| matches!(version, "0.155.1" | "0.165.0"))
}

pub(crate) fn discover_descendants<'a>(
    root_thread: &str,
    sessions: &'a [(PathBuf, Header)],
) -> (Vec<(PathBuf, &'a Header, String)>, bool) {
    let mut by_parent = HashMap::<String, Vec<(PathBuf, &'a Header)>>::new();
    let mut identity_counts = HashMap::<&str, usize>::new();
    for (path, header) in sessions {
        *identity_counts
            .entry(&header.session.thread_id)
            .or_default() += 1;
        if let Some(parent) = &header.session.parent_thread_id {
            by_parent
                .entry(parent.clone())
                .or_default()
                .push((path.clone(), header));
        }
    }
    let mut result = Vec::new();
    let mut ambiguous = false;
    let mut pending = vec![root_thread.to_owned()];
    let mut visited = HashSet::from([root_thread.to_owned()]);
    while let Some(parent) = pending.pop() {
        let Some(children) = by_parent.get(&parent) else {
            continue;
        };
        for (path, child) in children {
            if visited.contains(&child.session.thread_id) {
                continue;
            }
            // Check all discovered headers, including candidates that disagree
            // about their parent. Never choose a rollout by discovery order.
            if identity_counts[child.session.thread_id.as_str()] > 1 {
                ambiguous = true;
                continue;
            }
            visited.insert(child.session.thread_id.clone());
            result.push((path.clone(), *child, parent.clone()));
            pending.push(child.session.thread_id.clone());
            if result.len() >= MAX_DISCOVERY_FILES {
                return (result, ambiguous);
            }
        }
    }
    (result, ambiguous)
}

pub(crate) fn child_header_matches(
    parsed: &Header,
    discovered: &Header,
    expected_parent: &str,
) -> bool {
    parsed.session.thread_id == discovered.session.thread_id
        && parsed.session.parent_thread_id.as_deref() == Some(expected_parent)
        && discovered.session.parent_thread_id.as_deref() == Some(expected_parent)
}
