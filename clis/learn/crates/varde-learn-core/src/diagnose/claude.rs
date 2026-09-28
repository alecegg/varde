use std::collections::{HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::{Component, Path, PathBuf};

use serde_json::{Map, Value};

use super::{
    ChildSession, ClaudeHookContext, Coverage, CurrentOverlap, EvidenceRecord, InspectionSnapshot,
    MAX_DISCOVERY_FILES, MAX_FAMILY, MAX_FAMILY_SOURCE_BYTES, MAX_RECORD_BYTES, MAX_RECORDS,
    MAX_SOURCE_BYTES, MAX_TEXT_EXCERPT, MAX_WARNINGS, NormalizedRecordBudget, RecordAnchor,
    SessionMetadata, SourceSnapshot, ToolObservation, build_snapshot, digest, error, file_identity,
};
use crate::LearnError;

#[derive(Debug, Clone)]
struct Sidecar {
    tool_use_id: String,
    parent_agent_id: Option<String>,
}

#[derive(Debug)]
struct ChildFile {
    path: PathBuf,
    agent_id: String,
    sidecar: Option<Sidecar>,
}

#[derive(Debug)]
struct ParsedSource {
    source: SourceSnapshot,
    started_at: Option<String>,
    cwd: Option<String>,
    records: Vec<EvidenceRecord>,
    processed_records: usize,
    incomplete_tail: bool,
    malformed_records: usize,
    omitted_records: usize,
    truncated: bool,
    warnings: Vec<String>,
    unknown_records: bool,
    identity_incomplete: bool,
}

struct TranscriptIdentity<'a> {
    session_id: &'a str,
    thread_id: &'a str,
    transcript_id: &'a str,
    agent_id: Option<&'a str>,
    parent_agent_id: Option<&'a str>,
    parent_tool_use_id: Option<&'a str>,
}

#[derive(Debug)]
struct Discovery {
    project_dirs: Vec<PathBuf>,
    uncertain: bool,
    truncated: bool,
}

pub(super) fn inspect_id(
    projects_root: &Path,
    session_id: &str,
) -> Result<InspectionSnapshot, LearnError> {
    validate_session_id(session_id)?;
    let root = canonical_projects_root(projects_root)?;
    let discovery = scan_projects(&root)?;
    if discovery.uncertain || discovery.truncated {
        return Err(error(
            "diagnose_discovery_incomplete",
            "Claude project metadata discovery was incomplete; use an explicit transcript path",
        ));
    }
    let mut matches = Vec::new();
    let mut metadata_bytes = 0usize;
    for project_dir in &discovery.project_dirs {
        let candidate = project_dir.join(format!("{session_id}.jsonl"));
        match fs::symlink_metadata(&candidate) {
            Ok(metadata) if metadata.is_file() && !metadata.file_type().is_symlink() => {
                let (parsed, bytes_read) = read_identity(&candidate)?;
                metadata_bytes = metadata_bytes.saturating_add(bytes_read);
                if metadata_bytes > MAX_FAMILY_SOURCE_BYTES {
                    return Err(error(
                        "diagnose_discovery_incomplete",
                        "Claude metadata discovery exceeded its aggregate byte bound; use --path",
                    ));
                }
                if parsed == session_id {
                    matches.push(candidate);
                }
            }
            Ok(_) => {}
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => {
                return Err(error(
                    "diagnose_discovery_incomplete",
                    "Claude project metadata could not be verified",
                ));
            }
        }
    }
    match matches.as_slice() {
        [] => Err(error(
            "diagnose_session_not_found",
            format!(
                "Claude session `{session_id}` was not found under the configured projects root"
            ),
        )),
        [path] => inspect_main(&root, path, session_id),
        _ => Err(error(
            "diagnose_session_ambiguous",
            format!(
                "Claude session `{session_id}` appears in multiple project namespaces; use --path"
            ),
        )),
    }
}

pub(super) fn inspect_path(
    projects_root: &Path,
    path: &Path,
) -> Result<InspectionSnapshot, LearnError> {
    inspect_path_snapshot(projects_root, path)
}

pub(super) fn inspect_current(
    projects_root: &Path,
    session_id: &str,
    context: &ClaudeHookContext,
) -> Result<InspectionSnapshot, LearnError> {
    validate_session_id(session_id)?;
    let root = canonical_projects_root(projects_root)?;
    let main_path = canonical_hook_path(&root, &context.transcript_path)?;
    let output = inspect_path_snapshot(&root, &main_path)?;
    if output.session.session_id.as_deref() != Some(session_id) {
        return Err(error(
            "diagnose_current_context_invalid",
            "Claude hook session ID does not match its recorded transcript",
        ));
    }
    let target_path = match &context.agent_transcript_path {
        Some(path) => canonical_hook_path(&root, path)?,
        None => main_path,
    };
    let target_source = output
        .sources
        .iter()
        .find(|source| source.canonical_path == target_path.to_string_lossy());
    let Some(target_source) = target_source else {
        return Err(error(
            "diagnose_current_context_invalid",
            "Claude hook transcript is not part of the selected session family",
        ));
    };
    if let Some(agent_id) = &context.agent_id
        && target_source.agent_id.as_deref() != Some(agent_id.as_str())
    {
        return Err(error(
            "diagnose_current_context_invalid",
            "Claude hook agent ID does not match the selected child transcript",
        ));
    }
    let mut output = output;
    output.overlap = CurrentOverlap::Current;
    output.coverage.analysis_ready = false;
    output.coverage.complete = false;
    output.coverage.warnings.push(
        "current Claude session overlaps this evidence family; provide a verified pre-orchestration cutoff".into(),
    );
    Ok(output)
}

fn inspect_path_snapshot(
    projects_root: &Path,
    path: &Path,
) -> Result<InspectionSnapshot, LearnError> {
    let root = canonical_projects_root(projects_root)?;
    let source_path = canonical_native_path(&root, path)?;
    let relative = source_path.strip_prefix(&root).map_err(|_| {
        error(
            "diagnose_source_outside_root",
            "Claude transcript is outside the configured projects root",
        )
    })?;
    let parts = relative.components().collect::<Vec<_>>();
    if parts.len() < 2 {
        return Err(error(
            "diagnose_source_invalid",
            "Claude transcript path must be within a project namespace",
        ));
    }
    let namespace = normal_component(parts[0])?;
    let project_dir = root.join(&namespace);
    let (session_id, main_path) = if parts.len() == 2 {
        let filename = normal_component(parts[1])?;
        let session_id = filename.strip_suffix(".jsonl").ok_or_else(|| {
            error(
                "diagnose_source_invalid",
                "Claude transcript must have a .jsonl extension",
            )
        })?;
        validate_session_id(session_id)?;
        (session_id.to_owned(), source_path.clone())
    } else {
        let session_id = normal_component(parts[1])?;
        validate_session_id(&session_id)?;
        if normal_component(parts[2])? != "subagents" {
            return Err(error(
                "diagnose_source_invalid",
                "nested Claude paths must be under the session subagents directory",
            ));
        }
        (
            session_id.clone(),
            project_dir.join(format!("{session_id}.jsonl")),
        )
    };
    if !main_path.exists() {
        return Err(error(
            "diagnose_source_invalid",
            "the main Claude session transcript for this path is missing",
        ));
    }
    let main_path = canonical_native_path(&root, &main_path)?;
    let snapshot = inspect_main(&root, &main_path, &session_id)?;
    if source_path != main_path
        && !snapshot
            .sources
            .iter()
            .any(|source| source.canonical_path == source_path.to_string_lossy())
    {
        return Err(error(
            "diagnose_source_invalid",
            "explicit Claude child transcript was not found in the selected session family",
        ));
    }
    Ok(snapshot)
}

fn inspect_main(
    projects_root: &Path,
    main_path: &Path,
    session_id: &str,
) -> Result<InspectionSnapshot, LearnError> {
    validate_session_id(session_id)?;
    let root = canonical_projects_root(projects_root)?;
    let main_path = canonical_native_path(&root, main_path)?;
    let project_dir = main_path.parent().ok_or_else(|| {
        error(
            "diagnose_source_invalid",
            "Claude main transcript has no project directory",
        )
    })?;
    let relative_project = project_dir.strip_prefix(&root).map_err(|_| {
        error(
            "diagnose_source_outside_root",
            "Claude project path is outside the configured projects root",
        )
    })?;
    if relative_project.components().count() != 1
        || main_path.file_name().and_then(|name| name.to_str())
            != Some(format!("{session_id}.jsonl").as_str())
    {
        return Err(error(
            "diagnose_source_invalid",
            "Claude main transcript identity does not match its project path",
        ));
    }
    let namespace = relative_project.to_string_lossy().into_owned();
    let main_thread_id = format!("claude:{namespace}:{session_id}");
    let main_transcript_id = format!("{main_thread_id}:main");
    let main_identity = TranscriptIdentity {
        session_id,
        thread_id: &main_thread_id,
        transcript_id: &main_transcript_id,
        agent_id: None,
        parent_agent_id: None,
        parent_tool_use_id: None,
    };
    let mut normalized_budget = NormalizedRecordBudget::new();
    let mut main = parse_source(
        &main_path,
        &main_identity,
        MAX_SOURCE_BYTES,
        MAX_RECORDS,
        &mut normalized_budget,
    )?;

    let children_root = project_dir.join(session_id).join("subagents");
    let (child_files, discovery_uncertain, mut discovery_truncated) =
        discover_child_files(&children_root)?;
    let family_truncated = child_files.len() > MAX_FAMILY;
    let mut child_files = child_files;
    child_files.truncate(MAX_FAMILY);
    if family_truncated {
        discovery_truncated = true;
    }

    let mut children = Vec::new();
    let mut sources = vec![main.source.clone()];
    let mut records = std::mem::take(&mut main.records);
    let mut warnings = std::mem::take(&mut main.warnings);
    let mut incomplete_tail = main.incomplete_tail;
    let mut malformed_records = main.malformed_records;
    let mut omitted_records = main.omitted_records;
    let mut processed_records = main.processed_records;
    let mut truncated = main.truncated || discovery_truncated;
    let mut complete = !main.truncated
        && !main.incomplete_tail
        && main.malformed_records == 0
        && !main.identity_incomplete;
    if main.unknown_records {
        complete = false;
        warnings.push("unknown Claude event types were retained as bounded excerpts; event semantics are incomplete".into());
    }
    if discovery_uncertain {
        complete = false;
        warnings.push("Claude subagent discovery or sidecar linkage is incomplete".into());
    }
    if family_truncated {
        complete = false;
        warnings.push(format!(
            "Claude child family exceeded the {MAX_FAMILY} transcript limit"
        ));
    }

    let mut family_bytes = main.source.captured_length as usize;
    for child_file in child_files {
        let remaining_bytes = MAX_FAMILY_SOURCE_BYTES.saturating_sub(family_bytes);
        let remaining_records = MAX_RECORDS.saturating_sub(processed_records);
        if remaining_bytes == 0 || remaining_records == 0 {
            complete = false;
            truncated = true;
            warnings.push("Claude child family reached its aggregate byte or record limit".into());
            break;
        }
        let child_relative = child_file
            .path
            .strip_prefix(project_dir.join(session_id))
            .map_err(|_| {
                error(
                    "diagnose_source_invalid",
                    "Claude child transcript escaped its session directory",
                )
            })?
            .to_string_lossy()
            .replace('\\', "/");
        let transcript_id = format!(
            "{main_thread_id}:agent:{}:{child_relative}",
            child_file.agent_id
        );
        let child_thread_id = transcript_id.clone();
        let (parent_agent_id, parent_tool_use_id) = match &child_file.sidecar {
            Some(sidecar) => (
                sidecar.parent_agent_id.clone(),
                Some(sidecar.tool_use_id.clone()),
            ),
            None => {
                complete = false;
                warnings.push(format!(
                    "Claude child `{}` has missing or invalid .meta.json linkage",
                    child_file.agent_id
                ));
                (None, None)
            }
        };
        let child_limit = remaining_bytes.min(MAX_SOURCE_BYTES);
        let attempted_bytes = fs::metadata(&child_file.path)
            .map(|metadata| metadata.len().min(child_limit as u64) as usize)
            .unwrap_or(child_limit);
        family_bytes = family_bytes.saturating_add(attempted_bytes);
        let child_identity = TranscriptIdentity {
            session_id,
            thread_id: &child_thread_id,
            transcript_id: &transcript_id,
            agent_id: Some(&child_file.agent_id),
            parent_agent_id: parent_agent_id.as_deref(),
            parent_tool_use_id: parent_tool_use_id.as_deref(),
        };
        let Ok(mut child) = parse_source(
            &child_file.path,
            &child_identity,
            child_limit,
            remaining_records,
            &mut normalized_budget,
        ) else {
            complete = false;
            warnings.push(format!(
                "Claude child `{}` could not be read or did not match its parent session",
                child_file.agent_id
            ));
            continue;
        };
        if child
            .warnings
            .iter()
            .any(|warning| warning.contains("conflicting native agent ID"))
        {
            complete = false;
            warnings.push(format!(
                "Claude child `{}` contains a conflicting native agent ID",
                child_file.agent_id
            ));
        }
        if child.truncated
            || child.incomplete_tail
            || child.malformed_records > 0
            || child.unknown_records
            || child.identity_incomplete
        {
            complete = false;
        }
        if child.unknown_records {
            warnings.push(format!(
                "unknown Claude event types in child `{}` were retained as bounded excerpts",
                child_file.agent_id
            ));
        }
        let child_source_id = child.source.source_id.clone();
        children.push(ChildSession {
            thread_id: child_thread_id.clone(),
            source_id: child_source_id,
            parent_thread_id: None,
            started_at: child.started_at.clone(),
            relationship_evidence: child_file
                .sidecar
                .as_ref()
                .map(|_| "Claude .meta.json toolUseId".to_owned())
                .unwrap_or_else(|| "unverified Claude child sidecar".to_owned()),
            transcript_id: Some(transcript_id),
            agent_id: Some(child_file.agent_id),
            parent_agent_id,
            parent_tool_use_id,
            fork_session_id: None,
            fork_boundary: None,
        });
        sources.push(child.source);
        records.append(&mut child.records);
        processed_records = processed_records.saturating_add(child.processed_records);
        incomplete_tail |= child.incomplete_tail;
        malformed_records = malformed_records.saturating_add(child.malformed_records);
        omitted_records = omitted_records.saturating_add(child.omitted_records);
        truncated |= child.truncated;
        warnings.append(&mut child.warnings);
    }

    let mut agent_transcripts = HashMap::<String, Vec<String>>::new();
    for child in &children {
        if let Some(agent_id) = &child.agent_id {
            agent_transcripts
                .entry(agent_id.clone())
                .or_default()
                .push(child.thread_id.clone());
        }
    }
    let parent_tool_calls = records
        .iter()
        .filter_map(|record| {
            record
                .tool_use_id
                .as_ref()
                .map(|tool_id| (record.session_thread_id.clone(), tool_id.clone()))
        })
        .collect::<HashSet<_>>();
    for child in &mut children {
        let Some(tool_use_id) = child.parent_tool_use_id.as_ref() else {
            complete = false;
            child.relationship_evidence = "Claude child parent link is missing".into();
            continue;
        };
        let candidate_parent = match child.parent_agent_id.as_ref() {
            Some(agent_id) => agent_transcripts
                .get(agent_id)
                .filter(|transcripts| transcripts.len() == 1)
                .and_then(|transcripts| transcripts.first().cloned()),
            None => Some(main_thread_id.clone()),
        };
        let Some(candidate_parent) = candidate_parent else {
            complete = false;
            child.relationship_evidence =
                "Claude sidecar parent agent is missing or ambiguous".into();
            warnings.push(format!(
                "Claude child `{}` has an unverified parent agent link",
                child.agent_id.as_deref().unwrap_or("unknown")
            ));
            continue;
        };
        if parent_tool_calls.contains(&(candidate_parent.clone(), tool_use_id.clone())) {
            child.parent_thread_id = Some(candidate_parent);
            child.relationship_evidence =
                "Claude sidecar toolUseId matched the parent transcript".into();
        } else {
            complete = false;
            child.relationship_evidence =
                "Claude sidecar toolUseId did not match a parent tool call".into();
            warnings.push(format!(
                "Claude child `{}` toolUseId could not be verified in its parent transcript",
                child.agent_id.as_deref().unwrap_or("unknown")
            ));
        }
    }

    deduplicate_usage_snapshots(&mut records, &mut warnings, &mut complete);
    if sources.len() > MAX_FAMILY + 1 {
        sources.truncate(MAX_FAMILY + 1);
        complete = false;
        truncated = true;
    }
    if warnings.len() > MAX_WARNINGS {
        warnings.truncate(MAX_WARNINGS - 1);
        warnings
            .push("additional Claude coverage warnings were omitted at the warning limit".into());
    }
    let overlap = CurrentOverlap::Unknown;
    let source_complete = complete;
    let analysis_ready = source_complete && matches!(overlap, CurrentOverlap::NotCurrent);
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
    let session = SessionMetadata {
        harness: "claude".into(),
        thread_id: main_thread_id,
        session_id: Some(session_id.to_owned()),
        parent_thread_id: None,
        parent_provenance: None,
        started_at: main.started_at,
        cwd: main.cwd,
        cli_version: None,
        history_mode: None,
        git: None,
        source_id: sources[0].source_id.clone(),
        transcript_id: Some(main_transcript_id),
        project_namespace: Some(namespace),
        agent_id: None,
        parent_agent_id: None,
        parent_tool_use_id: None,
        current_directory: None,
        fork_session_id: None,
        fork_boundary: None,
    };
    for record in &mut records {
        if record.transcript_id.is_none() {
            record.transcript_id = session.transcript_id.clone();
        }
    }
    build_snapshot(session, children, sources, records, overlap, coverage)
}

fn scan_projects(root: &Path) -> Result<Discovery, LearnError> {
    let entries = fs::read_dir(root).map_err(|e| {
        error(
            "diagnose_discovery_failed",
            format!("cannot scan Claude projects: {e}"),
        )
    })?;
    let mut project_dirs = Vec::new();
    let mut uncertain = false;
    let mut scanned = 0usize;
    for entry in entries {
        scanned += 1;
        if scanned > MAX_DISCOVERY_FILES {
            return Ok(Discovery {
                project_dirs,
                uncertain: true,
                truncated: true,
            });
        }
        let Ok(entry) = entry else {
            uncertain = true;
            continue;
        };
        let path = entry.path();
        let Ok(kind) = entry.file_type() else {
            uncertain = true;
            continue;
        };
        if kind.is_symlink() {
            uncertain = true;
            continue;
        }
        if kind.is_dir() {
            project_dirs.push(path);
        }
    }
    Ok(Discovery {
        project_dirs,
        uncertain,
        truncated: false,
    })
}

fn discover_child_files(root: &Path) -> Result<(Vec<ChildFile>, bool, bool), LearnError> {
    match fs::symlink_metadata(root) {
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            return Ok((Vec::new(), false, false));
        }
        Err(_) => return Ok((Vec::new(), true, false)),
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
            return Ok((Vec::new(), true, false));
        }
        Ok(_) => {}
    }
    let mut stack = vec![(root.to_path_buf(), 0usize)];
    let mut files = Vec::new();
    let mut scanned = 0usize;
    let mut uncertain = false;
    let mut truncated = false;
    while let Some((directory, depth)) = stack.pop() {
        if depth > 8 {
            uncertain = true;
            truncated = true;
            continue;
        }
        let Ok(entries) = fs::read_dir(&directory) else {
            uncertain = true;
            continue;
        };
        for entry in entries {
            scanned += 1;
            if scanned > MAX_DISCOVERY_FILES {
                uncertain = true;
                truncated = true;
                return Ok((files, uncertain, truncated));
            }
            let Ok(entry) = entry else {
                uncertain = true;
                continue;
            };
            let path = entry.path();
            let Ok(kind) = entry.file_type() else {
                uncertain = true;
                continue;
            };
            if kind.is_symlink() {
                uncertain = true;
                continue;
            }
            if kind.is_dir() {
                stack.push((path, depth + 1));
                continue;
            }
            if !kind.is_file() {
                uncertain = true;
                continue;
            }
            let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
                uncertain = true;
                continue;
            };
            let Some(agent_id) = name
                .strip_prefix("agent-")
                .and_then(|name| name.strip_suffix(".jsonl"))
                .map(str::to_owned)
            else {
                continue;
            };
            if agent_id.is_empty() {
                uncertain = true;
                continue;
            }
            let sidecar_path = path.with_extension("meta.json");
            let sidecar = read_sidecar(&sidecar_path);
            if sidecar.is_none() {
                uncertain = true;
            }
            files.push(ChildFile {
                path,
                agent_id,
                sidecar,
            });
        }
    }
    files.sort_by(|left, right| left.path.cmp(&right.path));
    Ok((files, uncertain, truncated))
}

fn read_sidecar(path: &Path) -> Option<Sidecar> {
    let metadata = fs::symlink_metadata(path).ok()?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() > MAX_RECORD_BYTES as u64
    {
        return None;
    }
    let mut file = File::open(path).ok()?;
    let mut bytes = Vec::new();
    file.by_ref()
        .take((MAX_RECORD_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .ok()?;
    if bytes.len() > MAX_RECORD_BYTES {
        return None;
    }
    let value: Value = serde_json::from_slice(&bytes).ok()?;
    let object = value.as_object()?;
    let tool_use_id = object.get("toolUseId")?.as_str()?.trim();
    if tool_use_id.is_empty() {
        return None;
    }
    let parent_agent_id = match object.get("parentAgentId") {
        None | Some(Value::Null) => None,
        Some(Value::String(parent_id)) if !parent_id.trim().is_empty() => Some(parent_id.clone()),
        Some(_) => return None,
    };
    Some(Sidecar {
        tool_use_id: tool_use_id.to_owned(),
        parent_agent_id,
    })
}

pub(super) fn verified_thread_identity(
    source: &SourceSnapshot,
    header: &Value,
) -> Result<(String, String), LearnError> {
    let session_id = header
        .get("sessionId")
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| error("diagnose_source_changed", "Claude header has no sessionId"))?;
    let path = Path::new(&source.canonical_path);
    let components = path
        .components()
        .filter_map(|component| component.as_os_str().to_str())
        .collect::<Vec<_>>();
    let projects_index = components
        .iter()
        .rposition(|component| *component == "projects")
        .ok_or_else(|| {
            error(
                "diagnose_source_changed",
                "Claude source is outside a projects directory",
            )
        })?;
    let namespace = components.get(projects_index + 1).ok_or_else(|| {
        error(
            "diagnose_source_changed",
            "Claude source has no project namespace",
        )
    })?;
    let main_thread = format!("claude:{namespace}:{session_id}");
    let subagents_index = components
        .iter()
        .enumerate()
        .skip(projects_index + 1)
        .find_map(|(index, component)| (*component == "subagents").then_some(index));
    let (expected_thread, root_thread) = if let Some(index) = subagents_index {
        if index < projects_index + 3 {
            return Err(error(
                "diagnose_source_changed",
                "Claude child path does not contain its session directory",
            ));
        }
        let agent_id = source.agent_id.as_deref().ok_or_else(|| {
            error(
                "diagnose_source_changed",
                "Claude child source lost its native agent identity",
            )
        })?;
        if components.get(index - 1).copied() != Some(session_id)
            || components.get(index - 2).copied() != Some(namespace)
        {
            return Err(error(
                "diagnose_source_changed",
                "Claude child path no longer matches its native session",
            ));
        }
        let relative = components[index..].join("/");
        let expected_filename = format!("agent-{agent_id}.jsonl");
        if components.last().copied() != Some(expected_filename.as_str()) {
            return Err(error(
                "diagnose_source_changed",
                "Claude child filename no longer matches its native agent identity",
            ));
        }
        let sidecar = read_sidecar(&path.with_extension("meta.json")).ok_or_else(|| {
            error(
                "diagnose_source_changed",
                "Claude child linkage sidecar is missing or invalid",
            )
        })?;
        if source.parent_tool_use_id.as_deref() != Some(sidecar.tool_use_id.as_str())
            || source.parent_agent_id != sidecar.parent_agent_id
        {
            return Err(error(
                "diagnose_source_changed",
                "Claude child linkage metadata changed after inspection",
            ));
        }
        let transcript_id = format!("{main_thread}:agent:{agent_id}:{relative}");
        if source.transcript_id.as_deref() != Some(transcript_id.as_str()) {
            return Err(error(
                "diagnose_source_changed",
                "Claude child transcript identity does not match its source path",
            ));
        }
        (transcript_id, main_thread)
    } else {
        let expected_filename = format!("{session_id}.jsonl");
        if components.last().copied() != Some(expected_filename.as_str())
            || source.agent_id.is_some()
            || source.parent_agent_id.is_some()
            || source.parent_tool_use_id.is_some()
        {
            return Err(error(
                "diagnose_source_changed",
                "Claude main transcript identity does not match its source path",
            ));
        }
        let transcript_id = format!("{main_thread}:main");
        if source.transcript_id.as_deref() != Some(transcript_id.as_str()) {
            return Err(error(
                "diagnose_source_changed",
                "Claude transcript identity does not match its source path",
            ));
        }
        (main_thread.clone(), main_thread)
    };
    if source.session_thread_id.as_deref() != Some(expected_thread.as_str()) {
        return Err(error(
            "diagnose_source_changed",
            "Claude source thread identity changed after inspection",
        ));
    }
    Ok((expected_thread, root_thread))
}

fn parse_source(
    path: &Path,
    identity: &TranscriptIdentity<'_>,
    byte_limit: usize,
    record_limit: usize,
    normalized_budget: &mut NormalizedRecordBudget,
) -> Result<ParsedSource, LearnError> {
    let (source, bytes, initially_truncated) = read_bounded_source(path, byte_limit)?;
    let mut lines = bytes.split_inclusive(|byte| *byte == b'\n');
    let Some(first_line) = lines.next() else {
        return Err(error(
            "diagnose_source_invalid",
            "Claude transcript is empty",
        ));
    };
    if !first_line.ends_with(b"\n") || first_line.len().saturating_sub(1) > MAX_RECORD_BYTES {
        return Err(error(
            "diagnose_source_invalid",
            "Claude transcript header is incomplete or too large",
        ));
    }
    let first_value: Value =
        serde_json::from_slice(&first_line[..first_line.len() - 1]).map_err(|e| {
            error(
                "diagnose_source_invalid",
                format!("invalid Claude transcript header: {e}"),
            )
        })?;
    let first_session = first_value
        .get("sessionId")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            error(
                "diagnose_source_invalid",
                "Claude transcript header has no verified sessionId",
            )
        })?;
    if first_session != identity.session_id {
        return Err(error(
            "diagnose_source_invalid",
            "Claude transcript sessionId conflicts with its selected filename",
        ));
    }
    let started_at = first_value
        .get("timestamp")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let session_cwd = first_value
        .get("cwd")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let canonical_path = source.canonical_path.clone();
    let mut source = source;
    source.harness = Some("claude".into());
    source.session_thread_id = Some(identity.thread_id.to_owned());
    source.transcript_id = Some(identity.transcript_id.to_owned());
    source.agent_id = identity.agent_id.map(str::to_owned);
    source.parent_agent_id = identity.parent_agent_id.map(str::to_owned);
    source.parent_tool_use_id = identity.parent_tool_use_id.map(str::to_owned);

    let mut records = Vec::new();
    let mut warnings = Vec::new();
    let mut malformed_records = 0usize;
    let mut omitted_records = 0usize;
    let mut processed_records = 0usize;
    let mut budget_warning_emitted = false;
    let incomplete_tail = bytes.last().is_some_and(|byte| *byte != b'\n');
    let mut truncated = initially_truncated;
    let mut unknown_records = false;
    let mut identity_incomplete = false;
    let mut byte_start = 0usize;
    let mut index = 0u64;
    let mut all_lines = std::iter::once(first_line).chain(lines);
    for line in &mut all_lines {
        if !line.ends_with(b"\n") {
            omitted_records = omitted_records.saturating_add(1);
            break;
        }
        let raw = &line[..line.len() - 1];
        let start = byte_start;
        byte_start = byte_start.saturating_add(line.len());
        let current_index = index;
        index = index.saturating_add(1);
        if raw.len() > MAX_RECORD_BYTES {
            malformed_records = malformed_records.saturating_add(1);
            omitted_records = omitted_records.saturating_add(1);
            truncated = true;
            continue;
        }
        let Ok(value) = serde_json::from_slice::<Value>(raw) else {
            malformed_records = malformed_records.saturating_add(1);
            omitted_records = omitted_records.saturating_add(1);
            continue;
        };
        if value
            .get("sessionId")
            .and_then(Value::as_str)
            .is_some_and(|id| id != identity.session_id)
        {
            return Err(error(
                "diagnose_source_invalid",
                "Claude transcript contains a conflicting sessionId",
            ));
        }
        if processed_records >= record_limit {
            omitted_records = omitted_records.saturating_add(1);
            truncated = true;
            break;
        }
        let anchor = RecordAnchor {
            source_id: canonical_path.clone(),
            record_index: current_index,
            byte_start: start as u64,
            byte_end: (start + raw.len()) as u64,
            record_digest: digest(raw),
            native_id: value.get("uuid").and_then(Value::as_str).map(str::to_owned),
            session_id: Some(identity.session_id.to_owned()),
            storage_sequence: None,
            context_digest: None,
        };
        let record = normalize_record(
            &value,
            anchor,
            identity.thread_id,
            Some(identity.transcript_id),
            identity.agent_id,
            identity.parent_agent_id,
            identity.parent_tool_use_id,
        )?;
        unknown_records |= record.unknown_payload_excerpt.is_some();
        if record.anchor.native_id.is_none() {
            identity_incomplete = true;
            warnings.push(format!(
                "Claude record {current_index} has no native UUID identity"
            ));
        }
        if let (Some(expected_agent), Some(observed_agent)) = (
            identity.agent_id,
            value.get("agentId").and_then(Value::as_str),
        ) && expected_agent != observed_agent
        {
            identity_incomplete = true;
            warnings.push(format!(
                "Claude child `{expected_agent}` record {current_index} has a conflicting native agent ID"
            ));
        }
        processed_records = processed_records.saturating_add(1);
        if !normalized_budget.try_add(&record) {
            omitted_records = omitted_records.saturating_add(1);
            truncated = true;
            if !budget_warning_emitted {
                warnings.push(
                    "Claude normalized records exceeded the shared snapshot byte budget; records were omitted".into(),
                );
                budget_warning_emitted = true;
            }
            continue;
        }
        records.push(record);
    }
    if incomplete_tail {
        warnings.push("Claude transcript ends with an incomplete JSONL record".into());
    }
    if initially_truncated {
        warnings.push(format!(
            "Claude transcript exceeded the {byte_limit} byte source limit"
        ));
    }
    Ok(ParsedSource {
        source,
        started_at,
        cwd: session_cwd,
        records,
        processed_records,
        incomplete_tail,
        malformed_records,
        omitted_records,
        truncated,
        warnings,
        unknown_records,
        identity_incomplete,
    })
}

pub(crate) fn normalize_record(
    value: &Value,
    anchor: RecordAnchor,
    thread_id: &str,
    transcript_id: Option<&str>,
    agent_id: Option<&str>,
    parent_agent_id: Option<&str>,
    parent_tool_use_id: Option<&str>,
) -> Result<EvidenceRecord, LearnError> {
    let top_type = value
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let message = value.get("message").unwrap_or(&Value::Null);
    let role = message
        .get("role")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let content = message.get("content").and_then(Value::as_array);
    let tool_use = content.and_then(|blocks| {
        blocks
            .iter()
            .find(|block| block.get("type").and_then(Value::as_str) == Some("tool_use"))
    });
    let tool_result = content.and_then(|blocks| {
        blocks
            .iter()
            .find(|block| block.get("type").and_then(Value::as_str) == Some("tool_result"))
    });
    let kind = if tool_result.is_some() {
        "tool_result"
    } else if tool_use.is_some() {
        "tool_call"
    } else if top_type == "progress" {
        "progress"
    } else if matches!(top_type, "assistant" | "user" | "system") {
        "message"
    } else {
        top_type
    };
    let text_parts = content
        .into_iter()
        .flatten()
        .filter_map(|block| {
            block
                .get("text")
                .or_else(|| block.get("content"))
                .and_then(Value::as_str)
        })
        .collect::<Vec<_>>();
    let text_excerpt = if let Some(text) = message.get("content").and_then(Value::as_str) {
        Some(bounded(text, MAX_TEXT_EXCERPT))
    } else if !text_parts.is_empty() {
        Some(bounded(&text_parts.join(" "), MAX_TEXT_EXCERPT))
    } else if top_type == "progress" {
        let detail = value.get("data").and_then(|data| data.get("message"));
        detail
            .and_then(Value::as_str)
            .map(|text| bounded(text, MAX_TEXT_EXCERPT))
            .or_else(|| excerpt(value.get("data"), MAX_TEXT_EXCERPT).0)
    } else {
        None
    };
    let provider_message_id = message.get("id").and_then(Value::as_str).map(str::to_owned);
    let tool_use_id = tool_use
        .and_then(|block| block.get("id"))
        .and_then(Value::as_str)
        .or_else(|| {
            tool_result
                .and_then(|block| block.get("tool_use_id"))
                .and_then(Value::as_str)
        })
        .map(str::to_owned);
    let tool_name = tool_use
        .and_then(|block| block.get("name"))
        .and_then(Value::as_str)
        .map(|name| bounded(name, 128));
    let (tool_input_excerpt, input_truncated) =
        excerpt(tool_use.and_then(|block| block.get("input")), 1_024);
    let (tool_output_excerpt, output_truncated) =
        excerpt(tool_result.and_then(|block| block.get("content")), 1_024);
    let tool_is_error = tool_result
        .and_then(|block| block.get("is_error"))
        .and_then(Value::as_bool)
        == Some(true);
    let tool_status = tool_result.map(|_| {
        if tool_is_error {
            "error".to_owned()
        } else {
            "success".to_owned()
        }
    });
    let tool_error = if tool_is_error {
        tool_output_excerpt.clone()
    } else {
        None
    };
    let tool_observations = content
        .into_iter()
        .flatten()
        .filter_map(|block| {
            let block_type = block.get("type").and_then(Value::as_str)?;
            if !matches!(block_type, "tool_use" | "tool_result") {
                return None;
            }
            let is_result = block_type == "tool_result";
            let id = if is_result {
                block.get("tool_use_id").and_then(Value::as_str)
            } else {
                block.get("id").and_then(Value::as_str)
            };
            let input = block.get("input");
            let output = if is_result {
                block.get("content")
            } else {
                None
            };
            let is_error =
                is_result && block.get("is_error").and_then(Value::as_bool) == Some(true);
            let (input_excerpt, input_truncated) = excerpt(input, 1_024);
            let (output_excerpt, output_truncated) = excerpt(output, 1_024);
            Some(ToolObservation {
                block_type: block_type.to_owned(),
                tool_use_id: id.map(str::to_owned),
                tool_name: block
                    .get("name")
                    .and_then(Value::as_str)
                    .map(|name| bounded(name, 128)),
                input_excerpt,
                output_excerpt: output_excerpt.clone(),
                status: if is_result {
                    Some(if is_error { "error" } else { "success" }.to_owned())
                } else {
                    None
                },
                error: if is_error {
                    output_excerpt.clone()
                } else {
                    None
                },
                detail_truncated: input_truncated || output_truncated,
            })
        })
        .collect::<Vec<_>>();
    let usage_record = usage_record(message.get("usage"));
    let known_blocks = content.into_iter().flatten().all(|block| {
        matches!(
            block.get("type").and_then(Value::as_str),
            Some("text")
                | Some("tool_use")
                | Some("tool_result")
                | Some("thinking")
                | Some("redacted_thinking")
                | Some("image")
                | Some("document")
        )
    });
    let known = matches!(top_type, "assistant" | "user" | "system" | "progress")
        && (top_type == "progress" || known_blocks);
    let unknown_payload_excerpt = if known {
        None
    } else {
        excerpt(Some(value), 512).0
    };
    let unknown_truncated = unknown_payload_excerpt
        .as_ref()
        .is_some_and(|excerpt| excerpt.ends_with('…'));
    Ok(EvidenceRecord {
        session_thread_id: thread_id.to_owned(),
        anchor,
        timestamp: value
            .get("timestamp")
            .and_then(Value::as_str)
            .map(str::to_owned),
        kind: kind.to_owned(),
        role,
        text_excerpt,
        tool_name,
        tool_input_excerpt,
        tool_output_excerpt,
        tool_status,
        tool_error,
        detail_truncated: input_truncated
            || output_truncated
            || unknown_truncated
            || tool_observations
                .iter()
                .any(|observation| observation.detail_truncated),
        tool_observations,
        unknown_payload_excerpt,
        turn_id: None,
        response_id: provider_message_id.clone(),
        cwd: value.get("cwd").and_then(Value::as_str).map(str::to_owned),
        git_head: None,
        failure_reason: None,
        compacted_before_tokens: None,
        usage_total: None,
        usage_last: None,
        usage_record,
        transcript_id: transcript_id.map(str::to_owned),
        provider_message_id,
        agent_id: value
            .get("agentId")
            .and_then(Value::as_str)
            .or(agent_id)
            .map(str::to_owned),
        parent_agent_id: parent_agent_id.map(str::to_owned),
        parent_native_id: value
            .get("parentUuid")
            .and_then(Value::as_str)
            .map(str::to_owned),
        tool_use_id,
        parent_tool_use_id: parent_tool_use_id.map(str::to_owned),
        is_sidechain: value.get("isSidechain").and_then(Value::as_bool),
        is_meta: value.get("isMeta").and_then(Value::as_bool),
        is_compact_summary: value.get("isCompactSummary").and_then(Value::as_bool),
        timestamp_raw: value.get("timestamp").cloned(),
        session_location: None,
        location_provenance: None,
    })
}

fn deduplicate_usage_snapshots(
    records: &mut [EvidenceRecord],
    warnings: &mut Vec<String>,
    complete: &mut bool,
) {
    let mut latest = HashMap::<(String, String), usize>::new();
    for index in 0..records.len() {
        if records[index].usage_record.is_none() {
            continue;
        }
        let Some(message_id) = records[index].provider_message_id.clone() else {
            *complete = false;
            warnings.push("Claude usage snapshot has no provider message ID; duplicate accounting cannot be verified".into());
            continue;
        };
        let Some(transcript_id) = records[index].transcript_id.clone() else {
            continue;
        };
        let key = (transcript_id, message_id);
        if let Some(previous) = latest.insert(key, index) {
            let previous_usage = records[previous].usage_record.clone();
            if let (Some(previous_usage), Some(current_usage)) = (
                previous_usage.as_ref().and_then(Value::as_object),
                records[index]
                    .usage_record
                    .as_mut()
                    .and_then(Value::as_object_mut),
            ) {
                for (name, value) in previous_usage {
                    current_usage
                        .entry(name.clone())
                        .or_insert_with(|| value.clone());
                }
            }
            records[previous].usage_record = None;
            warnings.push("repeated Claude provider message snapshots were retained but only the latest usage snapshot is counted".into());
        }
    }
}

fn usage_record(usage: Option<&Value>) -> Option<Value> {
    let object = usage?.as_object()?;
    let allowed = [
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ];
    let fields = allowed
        .into_iter()
        .filter_map(|key| {
            object
                .get(key)
                .filter(|value| value.is_number())
                .map(|value| (key.to_owned(), value.clone()))
        })
        .collect::<Map<_, _>>();
    (!fields.is_empty()).then_some(Value::Object(fields))
}

fn read_identity(path: &Path) -> Result<(String, usize), LearnError> {
    let metadata = fs::symlink_metadata(path).map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("cannot stat Claude transcript: {e}"),
        )
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(error(
            "diagnose_source_invalid",
            "Claude transcript is not a regular file",
        ));
    }
    let file = File::open(path).map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("cannot read Claude transcript: {e}"),
        )
    })?;
    let mut reader = BufReader::new(file);
    let mut line = Vec::new();
    reader
        .by_ref()
        .take((MAX_RECORD_BYTES + 1) as u64)
        .read_until(b'\n', &mut line)
        .map_err(|e| {
            error(
                "diagnose_source_invalid",
                format!("cannot read Claude header: {e}"),
            )
        })?;
    if line.len() > MAX_RECORD_BYTES || !line.ends_with(b"\n") {
        return Err(error(
            "diagnose_source_invalid",
            "Claude transcript header is incomplete or oversized",
        ));
    }
    let value: Value = serde_json::from_slice(&line[..line.len() - 1]).map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("invalid Claude session metadata: {e}"),
        )
    })?;
    let session_id = value
        .get("sessionId")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| {
            error(
                "diagnose_source_invalid",
                "Claude transcript header has no sessionId",
            )
        })?;
    Ok((session_id, line.len()))
}

fn read_bounded_source(
    path: &Path,
    limit: usize,
) -> Result<(SourceSnapshot, Vec<u8>, bool), LearnError> {
    let metadata = fs::symlink_metadata(path).map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("cannot stat Claude transcript: {e}"),
        )
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(error(
            "diagnose_source_invalid",
            "Claude transcript is not a regular file",
        ));
    }
    let canonical = path.canonicalize().map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("cannot resolve Claude transcript: {e}"),
        )
    })?;
    let mut file = File::open(&canonical).map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("cannot open Claude transcript: {e}"),
        )
    })?;
    let before = file.metadata().map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("cannot inspect Claude transcript: {e}"),
        )
    })?;
    let (device, inode, modified_ns) = file_identity(&before);
    let initial_length = before.len();
    let mut bytes = Vec::new();
    file.by_ref()
        .take((limit + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|e| {
            error(
                "diagnose_source_read_failed",
                format!("cannot read Claude transcript: {e}"),
            )
        })?;
    let initially_truncated = bytes.len() > limit;
    bytes.truncate(limit);
    let after = file.metadata().map_err(|e| {
        error(
            "diagnose_source_read_failed",
            format!("cannot restat Claude transcript: {e}"),
        )
    })?;
    let (after_device, after_inode, after_modified_ns) = file_identity(&after);
    if (device, inode) != (after_device, after_inode)
        || after.len() < initial_length
        || (after.len() == initial_length && modified_ns != after_modified_ns)
    {
        return Err(error(
            "diagnose_source_changed",
            "Claude transcript changed while it was being inspected",
        ));
    }
    file.seek(SeekFrom::Start(0)).map_err(|e| {
        error(
            "diagnose_source_read_failed",
            format!("cannot verify Claude transcript: {e}"),
        )
    })?;
    let mut verified = vec![0; bytes.len()];
    file.read_exact(&mut verified).map_err(|e| {
        error(
            "diagnose_source_changed",
            format!("Claude transcript prefix changed: {e}"),
        )
    })?;
    if verified != bytes {
        return Err(error(
            "diagnose_source_changed",
            "Claude transcript prefix changed while it was being inspected",
        ));
    }
    let path = canonical.to_string_lossy().into_owned();
    let source = SourceSnapshot {
        source_id: path.clone(),
        canonical_path: path,
        device,
        inode,
        initial_length,
        captured_length: bytes.len() as u64,
        modified_ns,
        prefix_digest: digest(&bytes),
        harness: None,
        session_thread_id: None,
        transcript_id: None,
        agent_id: None,
        parent_agent_id: None,
        parent_tool_use_id: None,
        format: Some("claude-jsonl".into()),
        companions: Vec::new(),
    };
    Ok((source, bytes, initially_truncated))
}

fn canonical_projects_root(path: &Path) -> Result<PathBuf, LearnError> {
    let metadata = fs::symlink_metadata(path).map_err(|e| {
        error(
            "diagnose_discovery_failed",
            format!("cannot stat Claude projects root: {e}"),
        )
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(error(
            "diagnose_discovery_invalid",
            "Claude projects root is not a real directory",
        ));
    }
    path.canonicalize().map_err(|e| {
        error(
            "diagnose_discovery_failed",
            format!("cannot resolve Claude projects root: {e}"),
        )
    })
}

fn canonical_native_path(root: &Path, path: &Path) -> Result<PathBuf, LearnError> {
    if fs::symlink_metadata(path).is_ok_and(|metadata| metadata.file_type().is_symlink()) {
        return Err(error(
            "diagnose_source_invalid",
            "Claude transcript path cannot be a symlink",
        ));
    }
    let canonical = path.canonicalize().map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("cannot resolve Claude transcript path: {e}"),
        )
    })?;
    if !canonical.starts_with(root) {
        return Err(error(
            "diagnose_source_outside_root",
            "Claude transcript is outside the configured projects root",
        ));
    }
    let metadata = fs::symlink_metadata(&canonical).map_err(|e| {
        error(
            "diagnose_source_invalid",
            format!("cannot stat Claude transcript: {e}"),
        )
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(error(
            "diagnose_source_invalid",
            "Claude transcript is not a regular file",
        ));
    }
    Ok(canonical)
}

fn canonical_hook_path(root: &Path, path: &Path) -> Result<PathBuf, LearnError> {
    if fs::symlink_metadata(path).is_ok_and(|metadata| metadata.file_type().is_symlink()) {
        return Err(error(
            "diagnose_current_context_invalid",
            "Claude hook transcript cannot be a symlink",
        ));
    }
    let canonical = path.canonicalize().map_err(|e| {
        error(
            "diagnose_current_context_invalid",
            format!("cannot resolve Claude hook transcript: {e}"),
        )
    })?;
    if !canonical.starts_with(root) {
        return Err(error(
            "diagnose_current_context_invalid",
            "Claude hook transcript is outside the configured projects root",
        ));
    }
    Ok(canonical)
}

fn validate_session_id(session_id: &str) -> Result<(), LearnError> {
    if session_id.trim().is_empty()
        || session_id.len() > 128
        || Path::new(session_id)
            .file_name()
            .and_then(|name| name.to_str())
            != Some(session_id)
        || session_id == "."
        || session_id == ".."
    {
        return Err(error(
            "diagnose_session_id_invalid",
            "Claude session ID is empty or not a safe filename",
        ));
    }
    Ok(())
}

fn normal_component(component: Component<'_>) -> Result<String, LearnError> {
    let Component::Normal(value) = component else {
        return Err(error(
            "diagnose_source_invalid",
            "Claude transcript path contains a non-normal component",
        ));
    };
    value.to_str().map(str::to_owned).ok_or_else(|| {
        error(
            "diagnose_source_invalid",
            "Claude transcript path is not valid UTF-8",
        )
    })
}

fn excerpt(value: Option<&Value>, limit: usize) -> (Option<String>, bool) {
    let Some(value) = value.filter(|value| !value.is_null()) else {
        return (None, false);
    };
    let serialized = value
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| value.to_string());
    let truncated = serialized.chars().count() > limit;
    (Some(bounded(&serialized, limit)), truncated)
}

fn bounded(text: &str, limit: usize) -> String {
    let mut output = text.chars().take(limit).collect::<String>();
    if text.chars().count() > limit {
        output.push('…');
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_transcript(path: &Path, session_id: &str, records: &[Value]) {
        let mut lines = vec![serde_json::json!({"sessionId":session_id,"cwd":"/fixture"})];
        lines.extend_from_slice(records);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(
            path,
            lines
                .iter()
                .map(Value::to_string)
                .collect::<Vec<_>>()
                .join("\n")
                + "\n",
        )
        .unwrap();
    }

    fn records(count: usize, session_id: &str, agent_id: Option<&str>) -> Vec<Value> {
        (0..count)
            .map(|index| {
                serde_json::json!({
                    "type":"assistant","uuid":format!("record-{index}"),"parentUuid":null,
                    "sessionId":session_id,"agentId":agent_id,
                    "timestamp":"2026-09-27T10:00:00.000Z",
                    "message":{"id":format!("message-{index}"),"role":"assistant","content":[{"type":"text","text":"small"}]}
                })
            })
            .collect()
    }

    #[test]
    fn linked_transcripts_share_the_normalized_record_budget() {
        let directory = tempfile::tempdir().unwrap();
        let session_id = "00000000-0000-4000-8000-000000000001";
        let main_path = directory.path().join("main.jsonl");
        let child_path = directory.path().join("child.jsonl");
        write_transcript(&main_path, session_id, &records(5, session_id, None));
        write_transcript(
            &child_path,
            session_id,
            &records(10, session_id, Some("child")),
        );

        let main_thread = "m".repeat(60_000);
        let main_transcript = "t".repeat(60_000);
        let child_thread = "c".repeat(60_000);
        let child_transcript = "u".repeat(60_000);
        let parent_tool_use_id = "p".repeat(60_000);
        let main_identity = TranscriptIdentity {
            session_id,
            thread_id: &main_thread,
            transcript_id: &main_transcript,
            agent_id: None,
            parent_agent_id: None,
            parent_tool_use_id: None,
        };
        let child_identity = TranscriptIdentity {
            session_id,
            thread_id: &child_thread,
            transcript_id: &child_transcript,
            agent_id: Some("child"),
            parent_agent_id: Some("parent"),
            parent_tool_use_id: Some(&parent_tool_use_id),
        };
        let mut budget = NormalizedRecordBudget::new();
        let main = parse_source(
            &main_path,
            &main_identity,
            MAX_SOURCE_BYTES,
            MAX_RECORDS,
            &mut budget,
        )
        .unwrap();
        let child = parse_source(
            &child_path,
            &child_identity,
            MAX_SOURCE_BYTES,
            MAX_RECORDS,
            &mut budget,
        )
        .unwrap();
        let normalized_bytes = main
            .records
            .iter()
            .chain(&child.records)
            .map(|record| serde_json::to_vec(record).unwrap().len())
            .sum::<usize>();

        assert!(normalized_bytes <= super::super::NORMALIZED_RECORD_BUDGET_BYTES);
        assert_eq!(normalized_bytes, budget.used_bytes());
        assert_eq!(main.records.len(), 6);
        assert!(child.records.len() < 10);
        assert!(child.truncated);
        assert!(child.omitted_records > 0);
        assert!(child.records.iter().all(|record| {
            record.session_thread_id == child_thread
                && record.parent_tool_use_id.as_deref() == Some(parent_tool_use_id.as_str())
        }));
    }
}
