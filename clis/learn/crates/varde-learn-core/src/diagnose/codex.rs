use std::collections::{HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

use serde_json::Value;

use super::{
    ChildSession, Coverage, CurrentOverlap, EvidenceRecord, GitMetadata, InspectionSnapshot,
    MAX_DISCOVERY_FILES, MAX_FAMILY, MAX_FAMILY_SOURCE_BYTES, MAX_RECORD_BYTES, MAX_RECORDS,
    MAX_SOURCE_BYTES, MAX_TEXT_EXCERPT, MAX_WARNINGS, NormalizedRecordBudget, RecordAnchor,
    SessionMetadata, SourceSnapshot, build_snapshot, digest, error, file_identity,
};
use crate::LearnError;

const MAX_DISCOVERY_BYTES: usize = 16 * 1024 * 1024;

#[derive(Debug)]
struct Header {
    session: SessionMetadata,
    forked_from_id: Option<String>,
    history_base: Option<Value>,
}

struct ReadSource {
    source: SourceSnapshot,
    bytes: Vec<u8>,
    initial_truncated: bool,
}

struct ParsedSource {
    header: Header,
    source: SourceSnapshot,
    records: Vec<EvidenceRecord>,
    processed_records: usize,
    incomplete_tail: bool,
    malformed_records: usize,
    omitted_records: usize,
    truncated: bool,
    warnings: Vec<String>,
}

struct Discovery {
    sessions: Vec<(PathBuf, Header)>,
    truncated: bool,
    uncertain: bool,
    limit: Option<DiscoveryLimit>,
}

#[derive(Clone, Copy)]
enum DiscoveryLimit {
    Entries,
    Bytes,
}

pub(super) fn inspect_id(home: &Path, thread_id: &str) -> Result<InspectionSnapshot, LearnError> {
    let discovery = scan_sessions(home)?;
    if discovery.truncated || discovery.uncertain {
        let reason = match discovery.limit {
            Some(DiscoveryLimit::Bytes) => format!(
                "Codex session discovery exhausted its {} MiB byte budget; use --path",
                MAX_DISCOVERY_BYTES / (1024 * 1024)
            ),
            Some(DiscoveryLimit::Entries) => format!(
                "Codex session discovery exceeded the {MAX_DISCOVERY_FILES} entry scan limit; use --path"
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

pub(super) fn inspect_path(home: &Path, path: &Path) -> Result<InspectionSnapshot, LearnError> {
    let discovery = scan_sessions(home).unwrap_or(Discovery {
        sessions: Vec::new(),
        truncated: true,
        uncertain: true,
        limit: None,
    });
    inspect_path_with_family(home, path, &discovery)
}

fn inspect_path_with_family(
    home: &Path,
    path: &Path,
    discovery: &Discovery,
) -> Result<InspectionSnapshot, LearnError> {
    let mut normalized_budget = NormalizedRecordBudget::new();
    let mut selected = parse_source(path, MAX_SOURCE_BYTES, MAX_RECORDS, &mut normalized_budget)?;
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

    if selected.header.forked_from_id.is_some()
        || selected.header.history_base.is_some()
        || selected
            .header
            .session
            .history_mode
            .as_deref()
            .is_some_and(|mode| mode != "full")
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
                MAX_DISCOVERY_BYTES / (1024 * 1024)
            ),
            Some(DiscoveryLimit::Entries) =>
                "Codex metadata discovery reached its entry scan limit; linked-child coverage is partial".to_owned(),
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
        let Ok(child) = parse_source(
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
        if child.header.forked_from_id.is_some()
            || child.header.history_base.is_some()
            || child
                .header
                .session
                .history_mode
                .as_deref()
                .is_some_and(|mode| mode != "full")
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
        processed_records = processed_records.saturating_add(child.processed_records);
        truncated |= child.truncated;
        if child.incomplete_tail || child.malformed_records > 0 || child.truncated {
            complete = false;
        }
        warnings.extend(child.warnings);
    }
    let unknown_records = records
        .iter()
        .any(|record| record.unknown_payload_excerpt.is_some());
    if unknown_records {
        complete = false;
        warnings.push("unknown Codex event types were retained as bounded excerpts; event semantics are incomplete".into());
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

fn scan_sessions(home: &Path) -> Result<Discovery, LearnError> {
    let root = home.join("sessions");
    let Ok(metadata) = fs::symlink_metadata(&root) else {
        return Ok(Discovery {
            sessions: Vec::new(),
            truncated: false,
            uncertain: false,
            limit: None,
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
    while let Some((directory, depth)) = stack.pop() {
        if depth > 8 {
            truncated = true;
            uncertain = true;
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
                });
            }
            let Ok(entry) = entry else {
                uncertain = true;
                continue;
            };
            let path = entry.path();
            let Ok(file_type) = entry.file_type() else {
                uncertain = true;
                continue;
            };
            if file_type.is_symlink() {
                uncertain = true;
                continue;
            }
            if file_type.is_dir() {
                stack.push((path, depth + 1));
                continue;
            }
            if !file_type.is_file() {
                uncertain = true;
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
            let remaining_bytes = MAX_DISCOVERY_BYTES.saturating_sub(metadata_bytes);
            if remaining_bytes == 0 {
                return Ok(Discovery {
                    sessions: output,
                    truncated: true,
                    uncertain: true,
                    limit: Some(DiscoveryLimit::Bytes),
                });
            }
            let (header, bytes_read) = read_header(&path, remaining_bytes);
            metadata_bytes = metadata_bytes.saturating_add(bytes_read);
            match header {
                Ok(header) => {
                    output.push((path, header));
                }
                Err(_) => {
                    uncertain = true;
                    if bytes_read == remaining_bytes {
                        return Ok(Discovery {
                            sessions: output,
                            truncated: true,
                            uncertain: true,
                            limit: Some(DiscoveryLimit::Bytes),
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
    })
}

fn read_header(path: &Path, byte_limit: usize) -> (Result<Header, LearnError>, usize) {
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
        parse_header(&value)
    })();
    (result, bytes_read)
}

fn parse_header(value: &Value) -> Result<Header, LearnError> {
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
        .map(str::to_owned);
    if !cli_version.as_deref().is_some_and(known_codex_version) {
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
    let direct_parent = payload.get("parent_thread_id").and_then(Value::as_str);
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
    })
}

pub(super) fn verified_header_identity(
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
        .is_some_and(|version| version == "0.155.1")
}

fn discover_descendants<'a>(
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

fn child_header_matches(parsed: &Header, discovered: &Header, expected_parent: &str) -> bool {
    parsed.session.thread_id == discovered.session.thread_id
        && parsed.session.parent_thread_id.as_deref() == Some(expected_parent)
        && discovered.session.parent_thread_id.as_deref() == Some(expected_parent)
}

fn parse_source(
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
    let mut header = parse_header(&value)?;
    header.session.source_id = canonical.clone();
    let mut records = Vec::new();
    let mut warnings = Vec::new();
    let mut malformed_records = 0usize;
    let mut omitted_records = 0usize;
    let mut processed_records = 0usize;
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
    Ok(ParsedSource {
        header,
        source: source.source,
        records,
        processed_records,
        incomplete_tail,
        malformed_records,
        omitted_records,
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

fn event_kind(value: &Value) -> String {
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
    let known = matches!(
        kind.as_str(),
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
    );
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

fn bounded_text(text: &str, limit: usize) -> String {
    let mut output = String::new();
    for character in text.chars().take(limit) {
        output.push(character);
    }
    if text.chars().count() > limit {
        output.push('…');
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    fn header(thread_id: &str, parent_thread_id: Option<&str>) -> Header {
        Header {
            session: SessionMetadata {
                harness: "codex".into(),
                thread_id: thread_id.into(),
                session_id: None,
                parent_thread_id: parent_thread_id.map(str::to_owned),
                parent_provenance: None,
                started_at: None,
                cwd: None,
                cli_version: Some("0.155.1".into()),
                history_mode: None,
                git: None,
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
            forked_from_id: None,
            history_base: None,
        }
    }

    #[test]
    fn selected_root_duplicates_in_a_cycle_do_not_override_explicit_selection() {
        let sessions = vec![
            (PathBuf::from("selected"), header("root", Some("leaf"))),
            (PathBuf::from("copy"), header("root", None)),
            (PathBuf::from("leaf"), header("leaf", Some("root"))),
        ];
        let (children, ambiguous) = discover_descendants("root", &sessions);
        assert!(!ambiguous);
        assert_eq!(children.len(), 1);
        assert_eq!(children[0].1.session.thread_id, "leaf");
    }

    #[test]
    fn ambiguous_descendants_are_omitted_regardless_of_order_or_parent() {
        for other_parent in ["root", "unrelated"] {
            let mut sessions = vec![
                (PathBuf::from("first"), header("duplicate", Some("root"))),
                (
                    PathBuf::from("second"),
                    header("duplicate", Some(other_parent)),
                ),
                (
                    PathBuf::from("grandchild"),
                    header("grandchild", Some("duplicate")),
                ),
                (PathBuf::from("unique"), header("unique", Some("root"))),
            ];
            for _ in 0..2 {
                let (children, ambiguous) = discover_descendants("root", &sessions);
                assert!(ambiguous);
                assert_eq!(children.len(), 1);
                assert_eq!(children[0].1.session.thread_id, "unique");
                sessions.reverse();
            }
        }
    }

    #[test]
    fn nested_ambiguity_keeps_only_verified_ancestors() {
        let sessions = vec![
            (PathBuf::from("child"), header("child", Some("root"))),
            (PathBuf::from("first"), header("duplicate", Some("child"))),
            (PathBuf::from("second"), header("duplicate", Some("child"))),
        ];
        let (children, ambiguous) = discover_descendants("root", &sessions);
        assert!(ambiguous);
        assert_eq!(children.len(), 1);
        assert_eq!(children[0].1.session.thread_id, "child");
    }

    #[test]
    fn unrelated_duplicates_do_not_taint_a_unique_family() {
        let sessions = vec![
            (PathBuf::from("child"), header("child", Some("root"))),
            (
                PathBuf::from("grandchild"),
                header("grandchild", Some("child")),
            ),
            (
                PathBuf::from("first"),
                header("duplicate", Some("unrelated")),
            ),
            (
                PathBuf::from("second"),
                header("duplicate", Some("unrelated")),
            ),
        ];
        let (children, ambiguous) = discover_descendants("root", &sessions);
        assert!(!ambiguous);
        assert_eq!(children.len(), 2);
        assert_eq!(children[0].1.session.thread_id, "child");
        assert_eq!(children[1].1.session.thread_id, "grandchild");
    }

    #[test]
    fn linked_child_header_must_keep_its_discovered_identity_and_parent() {
        let discovered = header("child", Some("parent"));
        assert!(child_header_matches(
            &header("child", Some("parent")),
            &discovered,
            "parent"
        ));
        assert!(!child_header_matches(
            &header("replacement", Some("parent")),
            &discovered,
            "parent"
        ));
        assert!(!child_header_matches(
            &header("child", Some("other-parent")),
            &discovered,
            "parent"
        ));
    }

    #[test]
    fn parsing_charges_large_inherited_identity_before_retaining_each_record() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("rollout.jsonl");
        let thread_id = "t".repeat(65_536);
        let mut lines = vec![serde_json::json!({
            "type":"session_meta",
            "payload":{"id":thread_id,"cli_version":"0.155.1"}
        })];
        lines.push(serde_json::json!({
            "type":"turn_context",
            "payload":{"cwd":"c".repeat(32_768)}
        }));
        for index in 0..40 {
            lines.push(serde_json::json!({
                "type":"response_item",
                "timestamp":"2026-09-27T10:00:00Z",
                "payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":format!("event-{index}")}]}
            }));
        }
        fs::write(
            &path,
            lines
                .iter()
                .map(serde_json::Value::to_string)
                .collect::<Vec<_>>()
                .join("\n")
                + "\n",
        )
        .unwrap();

        let mut budget = NormalizedRecordBudget::new();
        let parsed = parse_source(&path, MAX_SOURCE_BYTES, MAX_RECORDS, &mut budget).unwrap();
        let serialized_bytes = parsed
            .records
            .iter()
            .map(|record| serde_json::to_vec(record).unwrap().len())
            .sum::<usize>();
        assert!(serialized_bytes <= super::super::NORMALIZED_RECORD_BUDGET_BYTES);
        assert_eq!(serialized_bytes, budget.used_bytes());
        assert!(parsed.records.len() < 41);
        assert!(parsed.truncated);
        assert!(parsed.omitted_records > 0);
        assert!(parsed.records.iter().all(|record| {
            record.cwd.as_ref().is_some_and(|cwd| cwd.len() == 32_768)
                && record.session_thread_id.len() == 65_536
        }));
        assert!(
            parsed
                .records
                .windows(2)
                .all(|records| { records[1].anchor.record_index > records[0].anchor.record_index })
        );
    }

    #[test]
    fn header_discovery_charges_buffered_prefetch_to_its_byte_budget() {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "varde-codex-header-budget-{}-{unique}",
            std::process::id()
        ));
        fs::create_dir(&directory).unwrap();
        let path = directory.join("rollout.jsonl");
        let header = serde_json::json!({
            "type": "session_meta",
            "payload": { "id": "thread", "cli_version": "0.155.1" }
        });
        let mut contents = serde_json::to_vec(&header).unwrap();
        contents.push(b'\n');
        let tail_end = contents.len() + 4 * 1024;
        contents.resize(tail_end, b'x');
        fs::write(&path, contents).unwrap();

        let (result, bytes_read) = read_header(&path, 128);
        assert!(result.is_ok());
        assert_eq!(bytes_read, 128);

        fs::remove_dir_all(directory).unwrap();
    }
}
