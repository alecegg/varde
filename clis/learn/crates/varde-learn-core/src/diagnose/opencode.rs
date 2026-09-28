use std::collections::HashSet;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use rusqlite::{Connection, OpenFlags, OptionalExtension, params};
use serde_json::{Value, json};
use tempfile::TempDir;
use time::{OffsetDateTime, format_description::well_known::Rfc3339};

use super::{
    ChildSession, Coverage, CurrentOverlap, EvidenceRecord, InspectionSnapshot, MAX_FAMILY,
    MAX_FAMILY_SOURCE_BYTES, MAX_RECORD_BYTES, MAX_RECORDS, MAX_SOURCE_BYTES, MAX_TEXT_EXCERPT,
    MAX_WARNINGS, NormalizedRecordBudget, RecordAnchor, SessionMetadata, SourceCompanion,
    SourceSnapshot, ToolObservation, build_snapshot, digest, error, file_identity,
    parse_rfc3339_nanos,
};
use crate::LearnError;

const OPENCODE_VERSION: &str = "2.0.12";
const SESSION_COLUMNS: &[&str] = &[
    "id",
    "project_id",
    "workspace_id",
    "parent_id",
    "fork_session_id",
    "fork_boundary",
    "slug",
    "directory",
    "path",
    "title",
    "version",
    "share_url",
    "summary_additions",
    "summary_deletions",
    "summary_files",
    "summary_diffs",
    "metadata",
    "cost",
    "tokens_input",
    "tokens_output",
    "tokens_reasoning",
    "tokens_cache_read",
    "tokens_cache_write",
    "revert",
    "permission",
    "agent",
    "model",
    "time_created",
    "time_updated",
    "time_idle",
    "time_viewed",
    "idle_outcome",
    "time_compacting",
    "time_archived",
    "time_suspended",
    "resume_attempts",
];
const MESSAGE_COLUMNS: &[&str] = &[
    "id",
    "session_id",
    "type",
    "seq",
    "time_created",
    "time_updated",
    "data",
];
const CAPTURE_ATTEMPTS: usize = 2;
const MAX_CAPTURE_BYTES: usize = MAX_FAMILY_SOURCE_BYTES;

#[derive(Debug, Clone)]
struct SessionRow {
    id: String,
    project_id: String,
    parent_id: Option<String>,
    fork_session_id: Option<String>,
    fork_boundary: Option<Value>,
    directory: String,
    version: String,
    time_created: i64,
}

#[derive(Debug, Clone)]
struct MessageRow {
    id: String,
    session_id: String,
    kind: String,
    sequence: i64,
    data: Value,
}

struct NormalizedMessageBatch {
    records: Vec<EvidenceRecord>,
    warnings: Vec<String>,
    omitted_records: usize,
    truncated: bool,
}

struct ReadSessionResult {
    records: Vec<EvidenceRecord>,
    processed_records: usize,
    has_gaps: bool,
    malformed_records: usize,
    omitted_records: usize,
    truncated: bool,
    warnings: Vec<String>,
}

struct DatabaseCopy {
    _directory: TempDir,
    path: PathBuf,
    source: SourceSnapshot,
}

struct CapturedComponent {
    path: PathBuf,
    bytes: Option<Vec<u8>>,
    identity: Option<(u64, u64, u128)>,
}

pub(super) fn inspect_id(root: &Path, session_id: &str) -> Result<InspectionSnapshot, LearnError> {
    validate_id(session_id)?;
    let database = database_path(root)?;
    inspect_database(&database, Some(session_id))
}

pub(super) fn inspect_path(_root: &Path, path: &Path) -> Result<InspectionSnapshot, LearnError> {
    let canonical = path.canonicalize().map_err(|cause| {
        error(
            "diagnose_source_invalid",
            format!("cannot resolve OpenCode path: {cause}"),
        )
    })?;
    let metadata = fs::symlink_metadata(&canonical).map_err(|cause| {
        error(
            "diagnose_source_invalid",
            format!("cannot stat OpenCode path: {cause}"),
        )
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(error(
            "diagnose_source_invalid",
            "OpenCode path must be a regular file",
        ));
    }
    let mut file = File::open(&canonical).map_err(|cause| {
        error(
            "diagnose_source_invalid",
            format!("cannot open OpenCode path: {cause}"),
        )
    })?;
    let mut prefix = [0; 16];
    let read = file.read(&mut prefix).map_err(|cause| {
        error(
            "diagnose_source_read_failed",
            format!("cannot inspect OpenCode path: {cause}"),
        )
    })?;
    if &prefix[..read] == b"SQLite format 3\0" {
        return inspect_database(&canonical, None);
    }
    let bytes = read_bounded_file(&canonical, MAX_SOURCE_BYTES)?;
    inspect_export(&canonical, &bytes)
}

/// Revalidate one immutable row witness. Unrelated session appends do not stale
/// the anchor; replacing the selected row or any preceding location switch does.
pub(super) fn revalidate_record(
    source: &SourceSnapshot,
    anchor: &RecordAnchor,
) -> Result<super::RevalidatedRecord, LearnError> {
    match source.format.as_deref() {
        Some("opencode-sqlite-2.0.12") => revalidate_database_record(source, anchor),
        Some("opencode-export-json") => revalidate_export_record(source, anchor),
        _ => Err(error(
            "diagnose_source_changed",
            "unsupported OpenCode witness format",
        )),
    }
}

fn database_path(root: &Path) -> Result<PathBuf, LearnError> {
    if root.is_file() {
        return root.canonicalize().map_err(|cause| {
            error(
                "diagnose_source_invalid",
                format!("cannot resolve OpenCode database: {cause}"),
            )
        });
    }
    let configured = std::env::var_os("OPENCODE_DB").map(PathBuf::from);
    let path = match configured {
        Some(path) if path.is_absolute() => path,
        Some(path) => root.join(path),
        None => root.join("opencode.db"),
    };
    path.canonicalize().map_err(|cause| {
        error(
            "diagnose_session_not_found",
            format!("cannot resolve OpenCode database: {cause}"),
        )
    })
}

fn inspect_database(
    path: &Path,
    selected_id: Option<&str>,
) -> Result<InspectionSnapshot, LearnError> {
    let canonical = path.canonicalize().map_err(|cause| {
        error(
            "diagnose_source_invalid",
            format!("cannot resolve OpenCode database: {cause}"),
        )
    })?;
    for _ in 0..CAPTURE_ATTEMPTS {
        let copied = match capture_database(&canonical) {
            Ok(copied) => copied,
            Err(LearnError::Diagnose {
                code: "diagnose_source_changed",
                ..
            }) => continue,
            Err(cause) => return Err(cause),
        };
        let parsed = inspect_database_copy(&copied, selected_id)?;
        match verify_source_components(&canonical, &copied.source) {
            Ok(true) => return Ok(parsed),
            Ok(false)
            | Err(LearnError::Diagnose {
                code: "diagnose_source_changed",
                ..
            }) => {}
            Err(cause) => return Err(cause),
        }
    }
    Err(error(
        "diagnose_source_changed",
        "OpenCode database or WAL changed during both bounded snapshot attempts",
    ))
}

fn capture_database(path: &Path) -> Result<DatabaseCopy, LearnError> {
    let components = capture_components(path)?;
    let database = components
        .first()
        .and_then(|component| component.bytes.as_ref())
        .ok_or_else(|| error("diagnose_source_invalid", "OpenCode database is missing"))?;
    let directory = tempfile::Builder::new()
        .prefix("varde-opencode-snapshot-")
        .tempdir()
        .map_err(|cause| {
            error(
                "diagnose_snapshot_failed",
                format!("cannot create private scratch: {cause}"),
            )
        })?;
    let file_name = path.file_name().unwrap_or_default();
    let scratch = directory.path().join(file_name);
    write_scratch(&scratch, database)?;
    if let Some(wal) = components
        .get(1)
        .and_then(|component| component.bytes.as_ref())
    {
        let wal_path = PathBuf::from(format!("{}-wal", scratch.display()));
        write_scratch(&wal_path, wal)?;
    }
    let main = components.first().expect("database component exists");
    let (device, inode, modified_ns) = main.identity.expect("present database has identity");
    let source_path = path.to_string_lossy().into_owned();
    let source = SourceSnapshot {
        source_id: source_path.clone(),
        canonical_path: source_path,
        device,
        inode,
        initial_length: database.len() as u64,
        captured_length: database.len() as u64,
        modified_ns,
        prefix_digest: digest(database),
        harness: Some("opencode".into()),
        session_thread_id: None,
        transcript_id: None,
        agent_id: None,
        parent_agent_id: None,
        parent_tool_use_id: None,
        format: Some("opencode-sqlite-2.0.12".into()),
        companions: components.iter().skip(1).map(companion_snapshot).collect(),
    };
    Ok(DatabaseCopy {
        _directory: directory,
        path: scratch,
        source,
    })
}

fn capture_components(database: &Path) -> Result<Vec<CapturedComponent>, LearnError> {
    let wal = PathBuf::from(format!("{}-wal", database.display()));
    let shm = PathBuf::from(format!("{}-shm", database.display()));
    let mut captured = Vec::with_capacity(3);
    let mut total = 0usize;
    for path in [database.to_path_buf(), wal, shm] {
        let component = read_component(&path)?;
        if let Some(bytes) = &component.bytes {
            total = total.saturating_add(bytes.len());
            if bytes.len() > MAX_SOURCE_BYTES || total > MAX_CAPTURE_BYTES {
                return Err(error(
                    "diagnose_source_limit",
                    "OpenCode database, WAL, and SHM exceed the bounded capture size",
                ));
            }
        } else if path == database {
            return Err(error(
                "diagnose_source_invalid",
                "OpenCode database is missing",
            ));
        }
        captured.push(component);
    }
    Ok(captured)
}

fn read_component(path: &Path) -> Result<CapturedComponent, LearnError> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(cause) if cause.kind() == std::io::ErrorKind::NotFound => {
            return Ok(CapturedComponent {
                path: path.to_path_buf(),
                bytes: None,
                identity: None,
            });
        }
        Err(cause) => {
            return Err(error(
                "diagnose_source_read_failed",
                format!("cannot stat OpenCode source: {cause}"),
            ));
        }
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(error(
            "diagnose_source_invalid",
            "OpenCode database sidecars must be regular files",
        ));
    }
    let identity = file_identity(&metadata);
    let mut file = OpenOptions::new().read(true).open(path).map_err(|cause| {
        error(
            "diagnose_source_read_failed",
            format!("cannot open OpenCode source: {cause}"),
        )
    })?;
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take((MAX_SOURCE_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|cause| {
            error(
                "diagnose_source_read_failed",
                format!("cannot read OpenCode source: {cause}"),
            )
        })?;
    if bytes.len() > MAX_SOURCE_BYTES {
        return Err(error(
            "diagnose_source_limit",
            "OpenCode database sidecar exceeds its byte limit",
        ));
    }
    let after = file.metadata().map_err(|cause| {
        error(
            "diagnose_source_read_failed",
            format!("cannot restat OpenCode source: {cause}"),
        )
    })?;
    if file_identity(&after) != identity || after.len() != bytes.len() as u64 {
        return Err(error(
            "diagnose_source_changed",
            "OpenCode database sidecar changed while being copied",
        ));
    }
    Ok(CapturedComponent {
        path: path.to_path_buf(),
        bytes: Some(bytes),
        identity: Some(identity),
    })
}

fn companion_snapshot(component: &CapturedComponent) -> SourceCompanion {
    match (&component.bytes, component.identity) {
        (Some(bytes), Some((device, inode, modified_ns))) => SourceCompanion {
            path: component.path.to_string_lossy().into_owned(),
            present: true,
            device: Some(device),
            inode: Some(inode),
            length: Some(bytes.len() as u64),
            modified_ns: Some(modified_ns),
            digest: Some(digest(bytes)),
        },
        _ => SourceCompanion {
            path: component.path.to_string_lossy().into_owned(),
            present: false,
            device: None,
            inode: None,
            length: None,
            modified_ns: None,
            digest: None,
        },
    }
}

fn verify_source_components(database: &Path, source: &SourceSnapshot) -> Result<bool, LearnError> {
    let current = capture_components(database)?;
    let main = current
        .first()
        .and_then(|component| component.bytes.as_ref());
    let expected_main = (
        source.device,
        source.inode,
        source.initial_length,
        source.modified_ns,
        source.prefix_digest.as_str(),
    );
    let Some(main_component) = current.first() else {
        return Ok(false);
    };
    let Some(bytes) = main else { return Ok(false) };
    let Some((device, inode, modified_ns)) = main_component.identity else {
        return Ok(false);
    };
    let actual_digest = digest(bytes);
    if (
        device,
        inode,
        bytes.len() as u64,
        modified_ns,
        actual_digest.as_str(),
    ) != expected_main
    {
        return Ok(false);
    }
    Ok(current
        .iter()
        .skip(1)
        .map(companion_snapshot)
        .zip(source.companions.iter())
        .all(|(left, right)| {
            left.path == right.path
                && left.present == right.present
                && left.device == right.device
                && left.inode == right.inode
                && left.length == right.length
                && left.modified_ns == right.modified_ns
                && left.digest == right.digest
        }))
}

fn write_scratch(path: &Path, bytes: &[u8]) -> Result<(), LearnError> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|cause| {
            error(
                "diagnose_snapshot_failed",
                format!("cannot create private SQLite copy: {cause}"),
            )
        })?;
    file.write_all(bytes).map_err(|cause| {
        error(
            "diagnose_snapshot_failed",
            format!("cannot write private SQLite copy: {cause}"),
        )
    })
}

fn inspect_database_copy(
    copy: &DatabaseCopy,
    selected_id: Option<&str>,
) -> Result<InspectionSnapshot, LearnError> {
    let connection = Connection::open_with_flags(
        &copy.path,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|cause| {
        error(
            "diagnose_store_invalid",
            format!("cannot open private OpenCode snapshot: {cause}"),
        )
    })?;
    connection
        .busy_timeout(std::time::Duration::from_millis(250))
        .map_err(|cause| {
            error(
                "diagnose_store_invalid",
                format!("cannot configure private snapshot: {cause}"),
            )
        })?;
    validate_schema(&connection)?;
    let root = match selected_id {
        Some(id) => load_session(&connection, id)?.ok_or_else(|| {
            error(
                "diagnose_session_not_found",
                format!("OpenCode session `{id}` was not found"),
            )
        })?,
        None => unique_session(&connection)?,
    };
    build_native_inspection(&connection, &copy.source, root)
}

fn validate_schema(connection: &Connection) -> Result<(), LearnError> {
    for (table, expected) in [
        ("session_v2", SESSION_COLUMNS),
        ("session_message", MESSAGE_COLUMNS),
    ] {
        let mut statement = connection
            .prepare(&format!("PRAGMA table_info({table})"))
            .map_err(|cause| {
                error(
                    "diagnose_store_schema",
                    format!("cannot inspect OpenCode schema: {cause}"),
                )
            })?;
        let actual = statement
            .query_map([], |row| row.get::<_, String>(1))
            .map_err(|cause| {
                error(
                    "diagnose_store_schema",
                    format!("cannot inspect OpenCode schema: {cause}"),
                )
            })?
            .collect::<Result<HashSet<_>, _>>()
            .map_err(|cause| {
                error(
                    "diagnose_store_schema",
                    format!("cannot read OpenCode schema: {cause}"),
                )
            })?;
        let missing = expected
            .iter()
            .filter(|column| !actual.contains(**column))
            .copied()
            .collect::<Vec<_>>();
        if !missing.is_empty() {
            return Err(error(
                "diagnose_store_schema",
                format!(
                    "OpenCode store is missing required {table} columns: {}",
                    missing.join(", ")
                ),
            ));
        }
        if actual.len() != expected.len() {
            return Err(error(
                "diagnose_store_schema",
                format!("OpenCode {table} schema differs from the supported 2.0.12 format"),
            ));
        }
    }
    Ok(())
}

fn load_session(connection: &Connection, id: &str) -> Result<Option<SessionRow>, LearnError> {
    connection
        .query_row(
            "SELECT id,project_id,parent_id,fork_session_id,fork_boundary,directory,version,time_created FROM session_v2 WHERE id=?1",
            [id],
            session_from_row,
        )
        .optional()
        .map_err(|cause| error("diagnose_store_read_failed", format!("cannot read OpenCode session: {cause}")))
}

fn unique_session(connection: &Connection) -> Result<SessionRow, LearnError> {
    let mut statement = connection
        .prepare("SELECT id,project_id,parent_id,fork_session_id,fork_boundary,directory,version,time_created FROM session_v2 ORDER BY time_created DESC,id LIMIT 2")
        .map_err(|cause| error("diagnose_store_read_failed", format!("cannot select OpenCode session: {cause}")))?;
    let mut rows = statement.query([]).map_err(|cause| {
        error(
            "diagnose_store_read_failed",
            format!("cannot select OpenCode session: {cause}"),
        )
    })?;
    let Some(row) = rows.next().map_err(|cause| {
        error(
            "diagnose_store_read_failed",
            format!("cannot read OpenCode session: {cause}"),
        )
    })?
    else {
        return Err(error(
            "diagnose_session_not_found",
            "OpenCode database contains no sessions",
        ));
    };
    let selected = session_from_row(row).map_err(|cause| {
        error(
            "diagnose_store_read_failed",
            format!("cannot decode OpenCode session: {cause}"),
        )
    })?;
    if rows
        .next()
        .map_err(|cause| {
            error(
                "diagnose_store_read_failed",
                format!("cannot read OpenCode session: {cause}"),
            )
        })?
        .is_some()
    {
        return Err(error(
            "diagnose_session_ambiguous",
            "OpenCode database path contains multiple sessions; use --session",
        ));
    }
    Ok(selected)
}

fn session_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<SessionRow> {
    let boundary: Option<String> = row.get(4)?;
    Ok(SessionRow {
        id: row.get(0)?,
        project_id: row.get(1)?,
        parent_id: row.get(2)?,
        fork_session_id: row.get(3)?,
        fork_boundary: boundary.and_then(|value| serde_json::from_str(&value).ok()),
        directory: row.get(5)?,
        version: row.get(6)?,
        time_created: row.get(7)?,
    })
}

fn build_native_inspection(
    connection: &Connection,
    source: &SourceSnapshot,
    root: SessionRow,
) -> Result<InspectionSnapshot, LearnError> {
    if root.version != OPENCODE_VERSION {
        return Err(error(
            "diagnose_store_version",
            format!("unsupported OpenCode version `{}`", root.version),
        ));
    }
    let mut sessions = vec![root.clone()];
    let mut children = Vec::new();
    let mut visited = HashSet::from([root.id.clone()]);
    let mut queue = vec![root.id.clone()];
    let mut partial = false;
    let mut warnings = Vec::new();
    while let Some(parent_id) = queue.pop() {
        let descendants = child_sessions(connection, &parent_id)?;
        for child in descendants {
            if sessions.len() >= MAX_FAMILY {
                partial = true;
                warnings.push(format!(
                    "OpenCode child family exceeded the {MAX_FAMILY}-session bound"
                ));
                break;
            }
            if !visited.insert(child.id.clone()) {
                partial = true;
                warnings.push(
                    "OpenCode parent_id cycle or duplicate child relationship was detected".into(),
                );
                continue;
            }
            if child.version != OPENCODE_VERSION {
                partial = true;
                warnings.push(format!(
                    "linked OpenCode child `{}` uses an unsupported format version",
                    child.id
                ));
                continue;
            }
            if child.fork_session_id.is_some() {
                partial = true;
                warnings.push(format!(
                    "OpenCode child `{}` has materialized fork history whose originating rows were not prepended",
                    child.id
                ));
            }
            children.push(ChildSession {
                thread_id: child.id.clone(),
                source_id: source.source_id.clone(),
                parent_thread_id: child.parent_id.clone(),
                started_at: timestamp_from_ms(child.time_created),
                relationship_evidence: "OpenCode session_v2.parent_id".into(),
                transcript_id: None,
                agent_id: None,
                parent_agent_id: None,
                parent_tool_use_id: None,
                fork_session_id: child.fork_session_id.clone(),
                fork_boundary: child.fork_boundary.clone(),
            });
            queue.push(child.id.clone());
            sessions.push(child);
        }
    }
    if root.parent_id.is_some() {
        warnings.push(
            "selected OpenCode session has a parent_id; parent history was not prepended".into(),
        );
    }
    if root.fork_session_id.is_some() {
        partial = true;
        warnings.push("OpenCode fork rows are materialized; inherited incident provenance is not established, so coverage is partial".into());
    }
    let mut records = Vec::new();
    let mut processed_records = 0usize;
    let mut malformed_records = 0usize;
    let mut omitted_records = 0usize;
    let mut truncated = false;
    let mut normalized_budget = NormalizedRecordBudget::new();
    for session in &sessions {
        let remaining = MAX_RECORDS.saturating_sub(processed_records);
        if remaining == 0 {
            partial = true;
            truncated = true;
            break;
        }
        let session_result = read_session_records(
            connection,
            source,
            session,
            remaining,
            &mut normalized_budget,
        )?;
        processed_records = processed_records.saturating_add(session_result.processed_records);
        if session_result.has_gaps {
            partial = true;
        }
        malformed_records = malformed_records.saturating_add(session_result.malformed_records);
        omitted_records = omitted_records.saturating_add(session_result.omitted_records);
        truncated |= session_result.truncated;
        if session_result.truncated
            || session_result.malformed_records > 0
            || session_result.omitted_records > 0
        {
            partial = true;
        }
        warnings.extend(session_result.warnings);
        records.extend(session_result.records);
    }
    if partial {
        warnings.push("OpenCode native history has gaps, inherited rows, unknown records, or bounded discovery limits".into());
    }
    warnings.truncate(MAX_WARNINGS);
    let session = SessionMetadata {
        harness: "opencode".into(),
        thread_id: root.id.clone(),
        session_id: Some(root.id.clone()),
        parent_thread_id: root.parent_id.clone(),
        parent_provenance: root
            .parent_id
            .as_ref()
            .map(|_| "OpenCode session_v2.parent_id".into()),
        started_at: timestamp_from_ms(root.time_created),
        cwd: None,
        cli_version: Some(root.version),
        history_mode: root
            .fork_session_id
            .as_ref()
            .map(|_| "forked_materialized_rows".into()),
        git: None,
        source_id: source.source_id.clone(),
        transcript_id: None,
        project_namespace: Some(root.project_id),
        agent_id: None,
        parent_agent_id: None,
        parent_tool_use_id: None,
        current_directory: Some(root.directory),
        fork_session_id: root.fork_session_id,
        fork_boundary: root.fork_boundary,
    };
    let source = source.clone();
    build_snapshot(
        session,
        children,
        vec![source],
        records.clone(),
        CurrentOverlap::Unknown,
        Coverage {
            complete: !partial,
            source_complete: !partial,
            analysis_ready: !partial,
            cutoff_verified: false,
            cutoff_anchor: None,
            incomplete_tail: false,
            truncated,
            record_count: records.len(),
            malformed_records,
            omitted_records,
            warnings,
        },
    )
}

fn child_sessions(connection: &Connection, parent_id: &str) -> Result<Vec<SessionRow>, LearnError> {
    let mut statement = connection.prepare(
        "SELECT id,project_id,parent_id,fork_session_id,fork_boundary,directory,version,time_created FROM session_v2 WHERE parent_id=?1 ORDER BY time_created,id LIMIT ?2",
    ).map_err(|cause| error("diagnose_store_read_failed", format!("cannot discover OpenCode children: {cause}")))?;
    statement
        .query_map(
            params![parent_id, (MAX_FAMILY + 1) as i64],
            session_from_row,
        )
        .map_err(|cause| {
            error(
                "diagnose_store_read_failed",
                format!("cannot discover OpenCode children: {cause}"),
            )
        })?
        .map(|row| {
            row.map_err(|cause| {
                error(
                    "diagnose_store_read_failed",
                    format!("cannot decode OpenCode child: {cause}"),
                )
            })
        })
        .collect()
}

fn read_session_records(
    connection: &Connection,
    source: &SourceSnapshot,
    session: &SessionRow,
    limit: usize,
    normalized_budget: &mut NormalizedRecordBudget,
) -> Result<ReadSessionResult, LearnError> {
    let mut statement = connection.prepare(
        "SELECT id,session_id,type,seq,time_created,length(data) FROM session_message WHERE session_id=?1 ORDER BY seq LIMIT ?2",
    ).map_err(|cause| error("diagnose_store_read_failed", format!("cannot query OpenCode messages: {cause}")))?;
    let mut data_statement = connection
        .prepare("SELECT data FROM session_message WHERE session_id=?1 AND seq=?2 AND id=?3")
        .map_err(|cause| {
            error(
                "diagnose_store_read_failed",
                format!("cannot read OpenCode message data: {cause}"),
            )
        })?;
    let mut rows = statement
        .query(params![&session.id, limit.saturating_add(1) as i64])
        .map_err(|cause| {
            error(
                "diagnose_store_read_failed",
                format!("cannot query OpenCode messages: {cause}"),
            )
        })?;
    let mut messages = Vec::new();
    let mut warnings = Vec::new();
    let mut malformed = 0usize;
    let mut omitted = 0usize;
    let mut truncated = false;
    let mut expected = 1i64;
    let mut gap = false;
    let mut processed_records = 0usize;
    while let Some(row) = rows.next().map_err(|cause| {
        error(
            "diagnose_store_read_failed",
            format!("cannot read OpenCode message: {cause}"),
        )
    })? {
        if processed_records >= limit {
            truncated = true;
            omitted = omitted.saturating_add(1);
            break;
        }
        processed_records = processed_records.saturating_add(1);
        let row_id: String = row.get(0).map_err(|cause| {
            error(
                "diagnose_store_read_failed",
                format!("invalid OpenCode message id: {cause}"),
            )
        })?;
        let row_session: String = row.get(1).map_err(|cause| {
            error(
                "diagnose_store_read_failed",
                format!("invalid OpenCode message session: {cause}"),
            )
        })?;
        let kind: String = row.get(2).map_err(|cause| {
            error(
                "diagnose_store_read_failed",
                format!("invalid OpenCode message type: {cause}"),
            )
        })?;
        let sequence: i64 = row.get(3).map_err(|cause| {
            error(
                "diagnose_store_read_failed",
                format!("invalid OpenCode sequence: {cause}"),
            )
        })?;
        let time_created: i64 = row.get(4).map_err(|cause| {
            error(
                "diagnose_store_read_failed",
                format!("invalid OpenCode message time: {cause}"),
            )
        })?;
        let data_length: i64 = row.get(5).map_err(|cause| {
            error(
                "diagnose_store_read_failed",
                format!("invalid OpenCode message data size: {cause}"),
            )
        })?;
        if row_session != session.id
            || sequence <= 0
            || row_id.is_empty()
            || data_length < 0
            || data_length as usize > MAX_RECORD_BYTES
        {
            malformed = malformed.saturating_add(1);
            gap = true;
            warnings.push(
                "OpenCode message row had invalid identity or exceeded the per-record limit".into(),
            );
            continue;
        }
        let data: String = data_statement
            .query_row(params![&row_session, sequence, &row_id], |row| row.get(0))
            .map_err(|cause| {
                error(
                    "diagnose_store_read_failed",
                    format!("cannot read bounded OpenCode message data: {cause}"),
                )
            })?;
        if sequence != expected {
            gap = true;
            warnings.push(format!(
                "OpenCode sequence gap before row {sequence}; historical location may be unknown"
            ));
        }
        expected = sequence.saturating_add(1);
        let parsed: Value = match serde_json::from_str::<Value>(&data) {
            Ok(value) if value.is_object() => value,
            _ => {
                malformed = malformed.saturating_add(1);
                warnings.push(format!(
                    "OpenCode message {row_id} contained malformed or non-object JSON"
                ));
                continue;
            }
        };
        let mut merged = parsed;
        let object = merged.as_object_mut().expect("object checked above");
        object.insert("id".into(), Value::String(row_id.clone()));
        object.insert("type".into(), Value::String(kind.clone()));
        match object.get_mut("time") {
            Some(Value::Object(time)) => {
                time.entry("created").or_insert_with(|| json!(time_created));
            }
            None => {
                object.insert("time".into(), json!({"created":time_created}));
            }
            _ => {
                gap = true;
                warnings.push(format!(
                    "OpenCode message {row_id} has invalid time metadata"
                ));
            }
        }
        let event = MessageRow {
            id: row_id,
            session_id: row_session,
            kind,
            sequence,
            data: merged,
        };
        messages.push(event);
    }
    let normalized = normalize_messages(source, session, &messages, normalized_budget)?;
    warnings.extend(normalized.warnings);
    omitted = omitted.saturating_add(normalized.omitted_records);
    truncated |= normalized.truncated;
    gap |= normalized.truncated || normalized.omitted_records > 0;
    let records = normalized.records;
    if records
        .iter()
        .any(|record| record.unknown_payload_excerpt.is_some())
    {
        warnings.push(
            "unknown OpenCode message types or content were retained as bounded excerpts".into(),
        );
        gap = true;
    }
    if records.iter().any(|record| record.timestamp.is_none()) {
        warnings.push("some OpenCode messages have unsupported or missing event times".into());
        gap = true;
    }
    if records.iter().any(|record| {
        record
            .tool_status
            .as_deref()
            .is_some_and(|status| status == "running" || status == "streaming")
    }) {
        warnings.push(
            "unfinished OpenCode native tool calls were retained; coverage is partial".into(),
        );
        gap = true;
    }
    Ok(ReadSessionResult {
        records,
        processed_records,
        has_gaps: gap,
        malformed_records: malformed,
        omitted_records: omitted,
        truncated,
        warnings,
    })
}

fn normalize_messages(
    source: &SourceSnapshot,
    session: &SessionRow,
    messages: &[MessageRow],
    normalized_budget: &mut NormalizedRecordBudget,
) -> Result<NormalizedMessageBatch, LearnError> {
    let mut records: Vec<EvidenceRecord> = Vec::with_capacity(messages.len().min(MAX_RECORDS));
    let mut warnings = Vec::new();
    let mut omitted_records = 0usize;
    let mut truncated = false;
    let mut budget_warning_emitted = false;
    let mut location_history = LocationHistory::new();
    let mut last_sequence = 0i64;
    let mut context_digest = digest(b"opencode-location-context-v1");
    for message in messages {
        if message.sequence != last_sequence + 1 {
            context_digest = extend_context_digest(
                &context_digest,
                json!({
                    "kind":"sequence-gap",
                    "expected":last_sequence + 1,
                    "observed":message.sequence,
                }),
            )?;
            location_history.on_gap();
        }
        last_sequence = message.sequence;
        let switch = message.kind == "location-switched";
        if switch {
            location_history.apply_switch(
                message,
                &mut records,
                normalized_budget,
                &mut warnings,
                &mut truncated,
            );
        }
        let (record, record_digest) = normalized_native_record(
            source,
            session,
            message,
            &context_digest,
            &location_history,
            switch,
        )?;
        if has_unfinished_tool(message) {
            warnings.push(format!(
                "OpenCode tool in message {} is unfinished and was retained",
                message.id
            ));
        }
        if normalized_budget.try_add(&record) {
            records.push(record);
        } else {
            omitted_records = omitted_records.saturating_add(1);
            truncated = true;
            if !budget_warning_emitted {
                warnings.push("OpenCode normalized records exceeded the shared snapshot byte budget; records were omitted".into());
                budget_warning_emitted = true;
            }
        }
        if switch {
            context_digest = extend_context_digest(
                &context_digest,
                json!({
                    "kind":"location-switched",
                    "id":message.id,
                    "sequence":message.sequence,
                    "record_digest":record_digest,
                }),
            )?;
        }
    }
    if session.fork_session_id.is_some() {
        warnings.push(
            "OpenCode fork ancestry is recorded separately; parent records were not prepended"
                .into(),
        );
    }
    Ok(NormalizedMessageBatch {
        records,
        warnings,
        omitted_records,
        truncated,
    })
}

fn normalized_native_record(
    source: &SourceSnapshot,
    session: &SessionRow,
    message: &MessageRow,
    context_digest: &str,
    location_history: &LocationHistory,
    switch: bool,
) -> Result<(EvidenceRecord, String), LearnError> {
    let raw_bytes = serde_json::to_vec(&message.data).map_err(|cause| {
        error(
            "diagnose_record_invalid",
            format!("cannot serialize OpenCode message: {cause}"),
        )
    })?;
    let record_digest = digest(&raw_bytes);
    let anchor = RecordAnchor {
        source_id: source.source_id.clone(),
        record_index: message.sequence.saturating_sub(1).max(0) as u64,
        byte_start: 0,
        byte_end: 0,
        record_digest: record_digest.clone(),
        native_id: Some(message.id.clone()),
        session_id: Some(message.session_id.clone()),
        storage_sequence: Some(message.sequence),
        context_digest: Some(context_digest.to_owned()),
    };
    let mut record = normalize_message(
        &message.data,
        anchor,
        &session.id,
        TimestampFormat::NativeMilliseconds,
    )?;
    record.session_location = location_history.location.clone();
    record.location_provenance = if switch && location_history.location.is_some() {
        Some("location-switched.location".into())
    } else if record.session_location.is_some() {
        Some(
            if location_history.saw_switch {
                "latest prior location-switched.location"
            } else {
                "unknown"
            }
            .into(),
        )
    } else {
        None
    };
    Ok((record, record_digest))
}

fn has_unfinished_tool(message: &MessageRow) -> bool {
    message.kind == "assistant"
        && message
            .data
            .get("content")
            .and_then(Value::as_array)
            .is_some_and(|parts| {
                parts.iter().any(|part| {
                    part.get("type").and_then(Value::as_str) == Some("tool")
                        && part
                            .pointer("/state/status")
                            .and_then(Value::as_str)
                            .is_some_and(|status| status == "running" || status == "streaming")
                })
            })
}

struct LocationHistory {
    location: Option<String>,
    saw_switch: bool,
    context_complete: bool,
}

impl LocationHistory {
    fn new() -> Self {
        Self {
            location: None,
            saw_switch: false,
            context_complete: true,
        }
    }

    fn on_gap(&mut self) {
        self.context_complete = false;
        self.location = None;
    }

    fn apply_switch(
        &mut self,
        message: &MessageRow,
        records: &mut [EvidenceRecord],
        normalized_budget: &mut NormalizedRecordBudget,
        warnings: &mut Vec<String>,
        truncated: &mut bool,
    ) {
        let previous_location = message
            .data
            .pointer("/previous/location/directory")
            .and_then(Value::as_str)
            .map(str::to_owned);
        let next_location = message
            .data
            .pointer("/location/directory")
            .and_then(Value::as_str)
            .map(str::to_owned);
        if !self.saw_switch && self.context_complete {
            if let Some(previous) = previous_location.as_deref() {
                if backfill_previous_location(records, previous, normalized_budget) {
                    *truncated = true;
                    warnings.push("OpenCode location history could not be backfilled within the normalized record byte budget; some earlier locations remain unknown".into());
                }
            } else {
                warnings.push("first OpenCode location switch omitted previous.location; earlier session locations remain unknown".into());
            }
        } else if let (Some(known), Some(previous)) =
            (self.location.as_deref(), previous_location.as_deref())
            && known != previous
        {
            self.context_complete = false;
            warnings.push(
                "OpenCode location-switch history has conflicting previous.location evidence"
                    .into(),
            );
        }
        self.location = next_location;
        self.saw_switch = true;
    }
}

fn backfill_previous_location(
    records: &mut [EvidenceRecord],
    previous: &str,
    normalized_budget: &mut NormalizedRecordBudget,
) -> bool {
    let mut failed = false;
    for record in records {
        if record.session_location.is_none() {
            let mut updated = record.clone();
            updated.session_location = Some(previous.to_owned());
            updated.location_provenance = Some("first location-switched.previous.location".into());
            if normalized_budget.try_replace(record, &updated) {
                *record = updated;
            } else {
                failed = true;
            }
        }
    }
    failed
}

fn extend_context_digest(previous: &str, evidence: Value) -> Result<String, LearnError> {
    let context =
        serde_json::to_vec(&json!({"previous":previous,"evidence":evidence})).map_err(|cause| {
            error(
                "diagnose_record_invalid",
                format!("cannot serialize OpenCode context evidence: {cause}"),
            )
        })?;
    Ok(digest(&context))
}

#[derive(Clone, Copy)]
enum TimestampFormat {
    NativeMilliseconds,
    Iso8601,
}

fn normalize_message(
    value: &Value,
    anchor: RecordAnchor,
    session_id: &str,
    format: TimestampFormat,
) -> Result<EvidenceRecord, LearnError> {
    let kind = value
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let content = value.get("content").and_then(Value::as_array);
    let tool = content.and_then(|parts| {
        parts
            .iter()
            .find(|part| part.get("type").and_then(Value::as_str) == Some("tool"))
    });
    let text_parts = content
        .into_iter()
        .flatten()
        .filter(|part| part.get("type").and_then(Value::as_str) == Some("text"))
        .filter_map(|part| part.get("text").and_then(Value::as_str))
        .collect::<Vec<_>>();
    let text = value
        .get("text")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .or_else(|| (!text_parts.is_empty()).then(|| text_parts.join(" ")));
    let (kind, role) = match kind {
        "user" => ("user".to_owned(), Some("user".to_owned())),
        "assistant" if tool.is_some() => ("tool_call".to_owned(), Some("assistant".to_owned())),
        "assistant" => ("assistant".to_owned(), Some("assistant".to_owned())),
        other => (
            other.to_owned(),
            value.get("role").and_then(Value::as_str).map(str::to_owned),
        ),
    };
    let tool_state = tool.and_then(|item| item.get("state"));
    let input = tool_state.and_then(|state| state.get("input"));
    let output = tool_state.and_then(|state| state.get("content"));
    let error_value = tool_state.and_then(|state| state.get("error"));
    let tool_status = tool_state
        .and_then(|state| state.get("status"))
        .and_then(Value::as_str)
        .map(str::to_owned);
    let tool_error = error_value.map(|value| {
        value
            .get("message")
            .unwrap_or(value)
            .as_str()
            .map(|message| bounded_text(message, 512))
            .unwrap_or_else(|| bounded_value(value, 512))
    });
    let top_level_error = value.get("error");
    let failure_reason = top_level_error.map(error_excerpt);
    let tool_status = tool_status.or_else(|| {
        if kind == "compaction" {
            value
                .get("status")
                .and_then(Value::as_str)
                .map(str::to_owned)
        } else {
            None
        }
    });
    let tool_observations = content
        .into_iter()
        .flatten()
        .filter_map(|item| {
            if item.get("type").and_then(Value::as_str) != Some("tool") {
                return None;
            }
            let state = item.get("state");
            let input = state.and_then(|state| state.get("input"));
            let output = state.and_then(|state| state.get("content"));
            let error = state.and_then(|state| state.get("error"));
            let (input_excerpt, input_truncated) = input
                .map(|value| {
                    (
                        Some(bounded_value(value, 1_024)),
                        value_exceeds(Some(value), 1_024),
                    )
                })
                .unwrap_or((None, false));
            let (output_excerpt, output_truncated) = output
                .map(|value| {
                    (
                        Some(bounded_value(value, 1_024)),
                        value_exceeds(Some(value), 1_024),
                    )
                })
                .unwrap_or((None, false));
            Some(ToolObservation {
                block_type: "tool".to_owned(),
                tool_use_id: item.get("id").and_then(Value::as_str).map(str::to_owned),
                tool_name: item
                    .get("name")
                    .and_then(Value::as_str)
                    .map(|name| bounded_text(name, 128)),
                input_excerpt,
                output_excerpt,
                status: state
                    .and_then(|state| state.get("status"))
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                error: error.map(error_excerpt),
                detail_truncated: input_truncated
                    || output_truncated
                    || error.is_some_and(|value| value_exceeds(Some(value), 512)),
            })
        })
        .collect::<Vec<_>>();
    let tokens = value.get("tokens");
    let input_tokens = tokens
        .and_then(|value| value.get("input"))
        .and_then(Value::as_u64);
    let output_tokens = tokens
        .and_then(|value| value.get("output"))
        .and_then(Value::as_u64);
    let reasoning = tokens
        .and_then(|value| value.get("reasoning"))
        .and_then(Value::as_u64);
    let cache_read = tokens
        .and_then(|value| value.pointer("/cache/read"))
        .and_then(Value::as_u64);
    let cache_write = tokens
        .and_then(|value| value.pointer("/cache/write"))
        .and_then(Value::as_u64);
    let usage_record = if [
        input_tokens,
        output_tokens,
        reasoning,
        cache_read,
        cache_write,
    ]
    .iter()
    .any(Option::is_some)
    {
        let total = [
            input_tokens,
            output_tokens,
            reasoning,
            cache_read,
            cache_write,
        ]
        .into_iter()
        .flatten()
        .fold(0u64, u64::saturating_add);
        Some(json!({
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "reasoning_tokens": reasoning, "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write, "total_tokens": total,
            "semantics": "per-message processed token components; not a session aggregate"
        }))
    } else {
        None
    };
    let timestamp_value = tool
        .and_then(|item| item.pointer("/time/created"))
        .or_else(|| value.pointer("/time/created"));
    let (timestamp, timestamp_raw) = match (format, timestamp_value) {
        (TimestampFormat::NativeMilliseconds, Some(Value::Number(number))) => {
            let raw = Value::Number(number.clone());
            (number.as_i64().and_then(timestamp_from_ms), Some(raw))
        }
        (TimestampFormat::Iso8601, Some(Value::String(raw))) => {
            let valid = parse_rfc3339_nanos(raw).is_some();
            (
                valid.then(|| raw.to_owned()),
                Some(Value::String(raw.to_owned())),
            )
        }
        _ => (None, timestamp_value.cloned()),
    };
    let explicit_cwd = tool
        .and_then(|part| part.pointer("/state/input/cwd"))
        .or_else(|| value.get("cwd"))
        .and_then(Value::as_str)
        .map(str::to_owned);
    let known_content = content.into_iter().flatten().all(|part| {
        matches!(
            part.get("type").and_then(Value::as_str),
            Some("text" | "tool" | "step-start" | "step-finish" | "reasoning")
        )
    });
    let legacy_tool_output = tool.is_some_and(|item| {
        item.pointer("/state/output").is_some() && item.pointer("/state/content").is_none()
    });
    let known = known_content
        && !legacy_tool_output
        && matches!(
            value.get("type").and_then(Value::as_str),
            Some(
                "user"
                    | "assistant"
                    | "system"
                    | "synthetic"
                    | "skill"
                    | "shell"
                    | "compaction"
                    | "idle"
                    | "agent-switched"
                    | "model-switched"
                    | "location-switched"
            )
        );
    let unknown_payload_excerpt = if known {
        None
    } else {
        Some(bounded_value(value, MAX_TEXT_EXCERPT))
    };
    let truncated = text
        .as_deref()
        .is_some_and(|value| value.len() > MAX_TEXT_EXCERPT)
        || tool.is_some_and(|item| {
            value_exceeds(item.pointer("/state/input"), 1024)
                || value_exceeds(item.pointer("/state/content"), 1024)
                || value_exceeds(item.pointer("/state/error"), 512)
        })
        || top_level_error.is_some_and(|value| value_exceeds(Some(value), 512))
        || tool_observations
            .iter()
            .any(|observation| observation.detail_truncated)
        || (!known && value_exceeds(Some(value), MAX_TEXT_EXCERPT));
    Ok(EvidenceRecord {
        session_thread_id: session_id.to_owned(),
        anchor,
        timestamp,
        kind,
        role,
        text_excerpt: text.map(|text| bounded_text(&text, MAX_TEXT_EXCERPT)),
        tool_name: tool
            .and_then(|item| item.get("name"))
            .and_then(Value::as_str)
            .map(|text| bounded_text(text, 128)),
        tool_input_excerpt: input.map(|value| bounded_value(value, 1024)),
        tool_output_excerpt: output.map(|value| bounded_value(value, 1024)),
        tool_status,
        tool_error,
        tool_observations,
        detail_truncated: truncated,
        unknown_payload_excerpt,
        turn_id: None,
        response_id: None,
        cwd: explicit_cwd,
        git_head: None,
        failure_reason,
        compacted_before_tokens: None,
        usage_total: None,
        usage_last: None,
        usage_record,
        transcript_id: None,
        provider_message_id: None,
        agent_id: value
            .get("agent")
            .and_then(Value::as_str)
            .map(str::to_owned),
        parent_agent_id: value
            .get("parent_agent_id")
            .and_then(Value::as_str)
            .map(str::to_owned),
        parent_native_id: None,
        tool_use_id: tool
            .and_then(|item| item.get("id"))
            .and_then(Value::as_str)
            .map(str::to_owned),
        parent_tool_use_id: None,
        is_sidechain: None,
        is_meta: None,
        is_compact_summary: None,
        timestamp_raw,
        session_location: None,
        location_provenance: None,
    })
}

fn inspect_export(path: &Path, bytes: &[u8]) -> Result<InspectionSnapshot, LearnError> {
    let value: Value = serde_json::from_slice(bytes).map_err(|cause| {
        error(
            "diagnose_source_invalid",
            format!("invalid OpenCode export JSON: {cause}"),
        )
    })?;
    let info = value
        .get("info")
        .filter(|value| value.is_object())
        .ok_or_else(|| {
            error(
                "diagnose_source_schema",
                "OpenCode export must contain an info object",
            )
        })?;
    let messages = value
        .get("messages")
        .and_then(Value::as_array)
        .ok_or_else(|| {
            error(
                "diagnose_source_schema",
                "OpenCode export must contain a messages array",
            )
        })?;
    if messages.len() > MAX_RECORDS {
        return Err(error(
            "diagnose_source_limit",
            "OpenCode export exceeds the record limit",
        ));
    }
    let session_id = info
        .get("id")
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty())
        .ok_or_else(|| {
            error(
                "diagnose_source_schema",
                "OpenCode export info is missing its session id",
            )
        })?;
    validate_id(session_id)?;
    let canonical = path.canonicalize().map_err(|cause| {
        error(
            "diagnose_source_invalid",
            format!("cannot resolve OpenCode export: {cause}"),
        )
    })?;
    let metadata = fs::metadata(&canonical).map_err(|cause| {
        error(
            "diagnose_source_invalid",
            format!("cannot stat OpenCode export: {cause}"),
        )
    })?;
    let (device, inode, modified_ns) = file_identity(&metadata);
    let path_text = canonical.to_string_lossy().into_owned();
    let source = SourceSnapshot {
        source_id: path_text.clone(),
        canonical_path: path_text.clone(),
        device,
        inode,
        initial_length: bytes.len() as u64,
        captured_length: bytes.len() as u64,
        modified_ns,
        prefix_digest: digest(bytes),
        harness: Some("opencode".into()),
        session_thread_id: Some(session_id.into()),
        transcript_id: None,
        agent_id: None,
        parent_agent_id: None,
        parent_tool_use_id: None,
        format: Some("opencode-export-json".into()),
        companions: Vec::new(),
    };
    let session = SessionMetadata {
        harness: "opencode".into(),
        thread_id: session_id.into(),
        session_id: Some(session_id.into()),
        parent_thread_id: info
            .get("parentID")
            .and_then(Value::as_str)
            .map(str::to_owned),
        parent_provenance: info
            .get("parentID")
            .and_then(Value::as_str)
            .map(|_| "OpenCode export info.parentID".into()),
        started_at: export_time(info.pointer("/time/created")),
        cwd: None,
        cli_version: None,
        history_mode: Some("sanitized_export".into()),
        git: None,
        source_id: path_text.clone(),
        transcript_id: None,
        project_namespace: info
            .get("projectID")
            .and_then(Value::as_str)
            .map(str::to_owned),
        agent_id: None,
        parent_agent_id: None,
        parent_tool_use_id: None,
        current_directory: info
            .pointer("/location/directory")
            .and_then(Value::as_str)
            .map(str::to_owned),
        fork_session_id: info
            .pointer("/fork/sessionID")
            .and_then(Value::as_str)
            .map(str::to_owned),
        fork_boundary: info.get("fork").cloned(),
    };
    let mut records = Vec::new();
    let mut malformed = 0usize;
    let mut omitted = 0usize;
    let mut truncated = false;
    let mut normalized_budget = NormalizedRecordBudget::new();
    for (index, message) in messages.iter().enumerate() {
        let Some(id) = message
            .get("id")
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty())
        else {
            malformed += 1;
            continue;
        };
        let raw = serde_json::to_vec(message).map_err(|cause| {
            error(
                "diagnose_record_invalid",
                format!("cannot serialize exported message: {cause}"),
            )
        })?;
        if raw.len() > MAX_RECORD_BYTES {
            malformed += 1;
            omitted += 1;
            truncated = true;
            continue;
        }
        let anchor = RecordAnchor {
            source_id: path_text.clone(),
            record_index: index as u64,
            byte_start: 0,
            byte_end: 0,
            record_digest: digest(&raw),
            native_id: Some(id.into()),
            session_id: Some(session_id.into()),
            storage_sequence: None,
            context_digest: None,
        };
        let record = normalize_message(message, anchor, session_id, TimestampFormat::Iso8601)?;
        if normalized_budget.try_add(&record) {
            records.push(record);
        } else {
            omitted = omitted.saturating_add(1);
            truncated = true;
        }
    }
    let mut warnings = vec![
        "OpenCode export omits or sanitizes source details and may exclude unfinished messages"
            .into(),
    ];
    if malformed > 0 {
        warnings.push("some OpenCode export messages lacked bounded stable identities".into());
    }
    if truncated {
        warnings.push(
            "OpenCode export normalized records were omitted at the shared snapshot byte budget"
                .into(),
        );
    }
    let record_count = records.len();
    build_snapshot(
        session,
        Vec::new(),
        vec![source],
        records,
        CurrentOverlap::Unknown,
        Coverage {
            complete: false,
            source_complete: false,
            analysis_ready: false,
            cutoff_verified: false,
            cutoff_anchor: None,
            incomplete_tail: false,
            truncated,
            record_count,
            malformed_records: malformed,
            omitted_records: omitted,
            warnings,
        },
    )
}

fn revalidate_database_record(
    source: &SourceSnapshot,
    anchor: &RecordAnchor,
) -> Result<super::RevalidatedRecord, LearnError> {
    let session_id = anchor.session_id.as_deref().ok_or_else(|| {
        error(
            "diagnose_anchor_invalid",
            "OpenCode database anchor has no session identity",
        )
    })?;
    let message_id = anchor.native_id.as_deref().ok_or_else(|| {
        error(
            "diagnose_anchor_invalid",
            "OpenCode database anchor has no message identity",
        )
    })?;
    let sequence = anchor.storage_sequence.ok_or_else(|| {
        error(
            "diagnose_anchor_invalid",
            "OpenCode database anchor has no sequence",
        )
    })?;
    let db_path = PathBuf::from(&source.canonical_path);
    let canonical = db_path.canonicalize().map_err(|cause| {
        error(
            "diagnose_source_changed",
            format!("cannot resolve OpenCode database: {cause}"),
        )
    })?;
    if canonical.to_string_lossy() != source.canonical_path {
        return Err(error(
            "diagnose_source_changed",
            "OpenCode database path identity changed",
        ));
    }
    let metadata = fs::metadata(&db_path).map_err(|cause| {
        error(
            "diagnose_source_changed",
            format!("cannot stat OpenCode database: {cause}"),
        )
    })?;
    let (device, inode, _) = file_identity(&metadata);
    if (device, inode) != (source.device, source.inode) {
        return Err(error(
            "diagnose_source_changed",
            "OpenCode database identity changed",
        ));
    }
    let copied = capture_database(&db_path)?;
    if (copied.source.device, copied.source.inode) != (source.device, source.inode) {
        return Err(error(
            "diagnose_source_changed",
            "OpenCode database identity changed while copying",
        ));
    }
    let connection = Connection::open_with_flags(
        &copied.path,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|cause| {
        error(
            "diagnose_source_changed",
            format!("cannot open current OpenCode snapshot: {cause}"),
        )
    })?;
    validate_schema(&connection)?;
    let rows = load_rows_through(&connection, session_id, sequence, message_id)?;
    if !rows
        .iter()
        .any(|row| row.sequence == sequence && row.id == message_id)
    {
        return Err(error(
            "diagnose_source_changed",
            "anchored OpenCode message no longer exists",
        ));
    }
    let root = load_session(&connection, session_id)?.ok_or_else(|| {
        error(
            "diagnose_source_changed",
            "anchored OpenCode session no longer exists",
        )
    })?;
    let mut normalized_budget = NormalizedRecordBudget::new();
    let normalized =
        normalize_messages(&copied.source, &root, &rows, &mut normalized_budget)?.records;
    let record = normalized
        .into_iter()
        .find(|record| {
            record.anchor.storage_sequence == Some(sequence)
                && record.anchor.native_id.as_deref() == Some(message_id)
        })
        .ok_or_else(|| {
            error(
                "diagnose_source_changed",
                "anchored OpenCode message could not be normalized",
            )
        })?;
    let native_facts = rows
        .iter()
        .find(|row| row.sequence == sequence && row.id == message_id)
        .map(|row| row.data.clone())
        .ok_or_else(|| {
            error(
                "diagnose_source_changed",
                "anchored OpenCode message no longer exists",
            )
        })?;
    if record.anchor.record_digest != anchor.record_digest
        || record.anchor.context_digest != anchor.context_digest
    {
        return Err(error(
            "diagnose_source_changed",
            "anchored OpenCode message or preceding location context changed",
        ));
    }
    if !verify_source_components(&db_path, &copied.source)? {
        return Err(error(
            "diagnose_source_changed",
            "OpenCode store changed during witness revalidation",
        ));
    }
    Ok(to_revalidated(
        record,
        native_facts,
        session_id.to_owned(),
        root.parent_id.clone(),
        root.parent_id.is_none().then(|| session_id.to_owned()),
        root.fork_session_id.is_some(),
    ))
}

fn load_rows_through(
    connection: &Connection,
    session_id: &str,
    sequence: i64,
    target_id: &str,
) -> Result<Vec<MessageRow>, LearnError> {
    let mut statement = connection.prepare("SELECT id,session_id,type,seq,time_created,length(data) FROM session_message WHERE session_id=?1 AND seq<=?2 ORDER BY seq LIMIT ?3")
        .map_err(|cause| error("diagnose_source_changed", format!("cannot query OpenCode context: {cause}")))?;
    let mut data_statement = connection
        .prepare("SELECT data FROM session_message WHERE session_id=?1 AND seq=?2 AND id=?3")
        .map_err(|cause| {
            error(
                "diagnose_source_changed",
                format!("cannot read OpenCode context: {cause}"),
            )
        })?;
    let mut rows = statement
        .query(params![session_id, sequence, MAX_RECORDS as i64])
        .map_err(|cause| {
            error(
                "diagnose_source_changed",
                format!("cannot query OpenCode context: {cause}"),
            )
        })?;
    let mut output = Vec::new();
    while let Some(row) = rows.next().map_err(|cause| {
        error(
            "diagnose_source_changed",
            format!("cannot read OpenCode context: {cause}"),
        )
    })? {
        let id: String = row.get(0).map_err(|cause| {
            error(
                "diagnose_source_changed",
                format!("invalid OpenCode context id: {cause}"),
            )
        })?;
        let row_session: String = row.get(1).map_err(|cause| {
            error(
                "diagnose_source_changed",
                format!("invalid OpenCode context session: {cause}"),
            )
        })?;
        let kind: String = row.get(2).map_err(|cause| {
            error(
                "diagnose_source_changed",
                format!("invalid OpenCode context type: {cause}"),
            )
        })?;
        let row_sequence: i64 = row.get(3).map_err(|cause| {
            error(
                "diagnose_source_changed",
                format!("invalid OpenCode context sequence: {cause}"),
            )
        })?;
        let created: i64 = row.get(4).map_err(|cause| {
            error(
                "diagnose_source_changed",
                format!("invalid OpenCode context time: {cause}"),
            )
        })?;
        let data_length: i64 = row.get(5).map_err(|cause| {
            error(
                "diagnose_source_changed",
                format!("invalid OpenCode context size: {cause}"),
            )
        })?;
        let needs_data =
            kind == "location-switched" || (row_sequence == sequence && id == target_id);
        let mut data = if needs_data {
            if data_length < 0 || data_length as usize > MAX_RECORD_BYTES {
                return Err(error(
                    "diagnose_source_changed",
                    "anchored message or location context exceeded its bound",
                ));
            }
            let raw: String = data_statement
                .query_row(params![&row_session, row_sequence, &id], |row| row.get(0))
                .map_err(|cause| {
                    error(
                        "diagnose_source_changed",
                        format!("cannot read OpenCode context data: {cause}"),
                    )
                })?;
            serde_json::from_str::<Value>(&raw).map_err(|cause| {
                error(
                    "diagnose_source_changed",
                    format!("OpenCode context JSON changed: {cause}"),
                )
            })?
        } else {
            json!({})
        };
        let object = data.as_object_mut().ok_or_else(|| {
            error(
                "diagnose_source_changed",
                "OpenCode context row is not an object",
            )
        })?;
        object.insert("id".into(), Value::String(id.clone()));
        object.insert("type".into(), Value::String(kind.clone()));
        match object.get_mut("time") {
            Some(Value::Object(time)) => {
                time.entry("created").or_insert_with(|| json!(created));
            }
            None => {
                object.insert("time".into(), json!({"created":created}));
            }
            _ => {}
        }
        output.push(MessageRow {
            id,
            session_id: row_session,
            kind,
            sequence: row_sequence,
            data,
        });
    }
    Ok(output)
}

fn revalidate_export_record(
    source: &SourceSnapshot,
    anchor: &RecordAnchor,
) -> Result<super::RevalidatedRecord, LearnError> {
    let path = Path::new(&source.canonical_path);
    let canonical = path.canonicalize().map_err(|cause| {
        error(
            "diagnose_source_changed",
            format!("cannot resolve OpenCode export: {cause}"),
        )
    })?;
    if canonical.to_string_lossy() != source.canonical_path {
        return Err(error(
            "diagnose_source_changed",
            "OpenCode export path identity changed",
        ));
    }
    let metadata = fs::metadata(&canonical).map_err(|cause| {
        error(
            "diagnose_source_changed",
            format!("cannot stat OpenCode export: {cause}"),
        )
    })?;
    let (device, inode, _) = file_identity(&metadata);
    if (device, inode) != (source.device, source.inode) {
        return Err(error(
            "diagnose_source_changed",
            "OpenCode export file identity changed",
        ));
    }
    let bytes = read_bounded_file(&canonical, MAX_SOURCE_BYTES)?;
    let value: Value = serde_json::from_slice(&bytes).map_err(|cause| {
        error(
            "diagnose_source_changed",
            format!("OpenCode export changed: {cause}"),
        )
    })?;
    let session_id = value
        .pointer("/info/id")
        .and_then(Value::as_str)
        .filter(|id| !id.trim().is_empty())
        .ok_or_else(|| {
            error(
                "diagnose_source_changed",
                "OpenCode export has no session ID",
            )
        })?;
    if anchor.session_id.as_deref() != Some(session_id) {
        return Err(error(
            "diagnose_source_changed",
            "OpenCode export session identity changed",
        ));
    }
    let messages = value
        .get("messages")
        .and_then(Value::as_array)
        .ok_or_else(|| {
            error(
                "diagnose_source_changed",
                "OpenCode export no longer has messages",
            )
        })?;
    let message = messages.get(anchor.record_index as usize).ok_or_else(|| {
        error(
            "diagnose_source_changed",
            "anchored OpenCode export message is missing",
        )
    })?;
    let raw = serde_json::to_vec(message).map_err(|cause| {
        error(
            "diagnose_source_changed",
            format!("cannot inspect OpenCode export message: {cause}"),
        )
    })?;
    if digest(&raw) != anchor.record_digest
        || message.get("id").and_then(Value::as_str) != anchor.native_id.as_deref()
    {
        return Err(error(
            "diagnose_source_changed",
            "anchored OpenCode export message changed",
        ));
    }
    let normalized = normalize_message(
        message,
        anchor.clone(),
        anchor.session_id.as_deref().unwrap_or("unknown"),
        TimestampFormat::Iso8601,
    )?;
    let parent_thread_id = value
        .pointer("/info/parentID")
        .and_then(Value::as_str)
        .filter(|id| !id.trim().is_empty())
        .map(str::to_owned);
    Ok(to_revalidated(
        normalized,
        message.clone(),
        session_id.to_owned(),
        parent_thread_id.clone(),
        parent_thread_id.is_none().then(|| session_id.to_owned()),
        value.pointer("/info/fork/sessionID").is_some(),
    ))
}

fn to_revalidated(
    record: EvidenceRecord,
    native_facts: Value,
    native_thread_id: String,
    native_parent_thread_id: Option<String>,
    native_root_thread_id: Option<String>,
    inherited_history: bool,
) -> super::RevalidatedRecord {
    super::RevalidatedRecord {
        anchor: record.anchor,
        native_facts,
        native_thread_id,
        native_parent_thread_id,
        native_root_thread_id,
        inherited_history,
        timestamp: record.timestamp,
        kind: record.kind,
        role: record.role,
        text_excerpt: record.text_excerpt,
        failure_reason: record.failure_reason,
        cwd: record.cwd,
        turn_id: None,
        response_id: None,
        usage_record: record.usage_record,
        transcript_id: None,
        provider_message_id: record.provider_message_id,
        agent_id: record.agent_id,
        parent_agent_id: record.parent_agent_id,
        parent_native_id: None,
        tool_use_id: record.tool_use_id,
        parent_tool_use_id: None,
        tool_name: record.tool_name,
        tool_input_excerpt: record.tool_input_excerpt,
        tool_output_excerpt: record.tool_output_excerpt,
        tool_status: record.tool_status,
        tool_error: record.tool_error,
        tool_observations: record.tool_observations,
        is_sidechain: None,
        is_meta: None,
        is_compact_summary: None,
        timestamp_raw: record.timestamp_raw,
        session_location: record.session_location,
        location_provenance: record.location_provenance,
    }
}

fn timestamp_from_ms(milliseconds: i64) -> Option<String> {
    let instant =
        OffsetDateTime::from_unix_timestamp_nanos(i128::from(milliseconds).checked_mul(1_000_000)?)
            .ok()?;
    instant.format(&Rfc3339).ok()
}

fn export_time(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .filter(|text| parse_rfc3339_nanos(text).is_some())
        .map(str::to_owned)
}

fn read_bounded_file(path: &Path, limit: usize) -> Result<Vec<u8>, LearnError> {
    let metadata = fs::symlink_metadata(path).map_err(|cause| {
        error(
            "diagnose_source_invalid",
            format!("cannot stat source: {cause}"),
        )
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() > limit as u64 {
        return Err(error(
            "diagnose_source_limit",
            "OpenCode source is not a bounded regular file",
        ));
    }
    let mut file = File::open(path).map_err(|cause| {
        error(
            "diagnose_source_read_failed",
            format!("cannot open source: {cause}"),
        )
    })?;
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take((limit + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|cause| {
            error(
                "diagnose_source_read_failed",
                format!("cannot read source: {cause}"),
            )
        })?;
    if bytes.len() > limit {
        return Err(error(
            "diagnose_source_limit",
            "OpenCode source exceeds the bounded read limit",
        ));
    }
    Ok(bytes)
}

fn error_excerpt(value: &Value) -> String {
    match (
        value.get("type").and_then(Value::as_str),
        value.get("message").and_then(Value::as_str),
    ) {
        (Some(kind), Some(message)) => bounded_text(&format!("{kind}: {message}"), 512),
        (_, Some(message)) => bounded_text(message, 512),
        _ => bounded_value(value, 512),
    }
}

fn bounded_text(value: &str, limit: usize) -> String {
    if value.len() <= limit {
        return value.to_owned();
    }
    let mut end = limit.saturating_sub(3).min(value.len());
    while !value.is_char_boundary(end) {
        end = end.saturating_sub(1);
    }
    format!("{}…", &value[..end])
}

fn bounded_value(value: &Value, limit: usize) -> String {
    serde_json::to_string(value)
        .map(|text| bounded_text(&text, limit))
        .unwrap_or_else(|_| "<unavailable>".into())
}

fn value_exceeds(value: Option<&Value>, limit: usize) -> bool {
    value.is_some_and(|value| {
        value
            .as_str()
            .map(str::len)
            .unwrap_or_else(|| serde_json::to_vec(value).map_or(limit + 1, |bytes| bytes.len()))
            > limit
    })
}

fn validate_id(id: &str) -> Result<(), LearnError> {
    if id.trim().is_empty() || id.len() > 512 || id.chars().any(char::is_control) {
        return Err(error(
            "diagnose_session_invalid",
            "OpenCode session ID is invalid or exceeds its bound",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn source_fixture() -> SourceSnapshot {
        SourceSnapshot {
            source_id: "/fixture/opencode.db".into(),
            canonical_path: "/fixture/opencode.db".into(),
            device: 1,
            inode: 2,
            initial_length: 1,
            captured_length: 1,
            modified_ns: 0,
            prefix_digest: "sha256:fixture".into(),
            harness: Some("opencode".into()),
            session_thread_id: Some("ses_fixture".into()),
            transcript_id: None,
            agent_id: None,
            parent_agent_id: None,
            parent_tool_use_id: None,
            format: Some("opencode-native-sqlite".into()),
            companions: Vec::new(),
        }
    }

    fn session_fixture() -> SessionRow {
        SessionRow {
            id: "ses_fixture".into(),
            project_id: "project_fixture".into(),
            parent_id: None,
            fork_session_id: None,
            fork_boundary: None,
            directory: "/fixture".into(),
            version: OPENCODE_VERSION.into(),
            time_created: 1_700_000_000_000,
        }
    }

    #[test]
    fn native_tool_content_preserves_each_block_under_the_message_anchor() {
        let anchor = RecordAnchor {
            source_id: "synthetic-native-db".into(),
            record_index: 1,
            byte_start: 0,
            byte_end: 0,
            record_digest: "sha256:synthetic".into(),
            native_id: Some("msg_fixture".into()),
            session_id: Some("ses_fixture".into()),
            storage_sequence: Some(2),
            context_digest: None,
        };
        let message = serde_json::json!({
            "id":"msg_fixture",
            "type":"assistant",
            "content":[
                {"type":"tool","id":"tool_first","name":"bash","state":{
                    "status":"completed","input":{"command":"true"},
                    "content":[{"type":"text","text":"synthetic successful output"}],"metadata":{}
                }},
                {"type":"tool","id":"tool_second","name":"bash","state":{
                    "status":"error","input":{"command":"false"},
                    "content":[{"type":"text","text":"synthetic failed output"}],
                    "error":{"type":"tool.execution","message":"synthetic second failure"}
                }}
            ],
            "time":{"created":1700000000000_i64,"completed":1700000000040_i64},
            "tokens":{"input":10,"output":3,"reasoning":2,"cache":{"read":7,"write":4}}
        });

        let record = normalize_message(
            &message,
            anchor.clone(),
            "ses_fixture",
            TimestampFormat::NativeMilliseconds,
        )
        .unwrap();

        assert_eq!(record.tool_observations.len(), 2);
        assert_eq!(
            record.tool_observations[0].tool_use_id.as_deref(),
            Some("tool_first")
        );
        assert!(
            record.tool_observations[0]
                .output_excerpt
                .as_deref()
                .unwrap()
                .contains("synthetic successful output")
        );
        assert_eq!(
            record.tool_observations[1].tool_use_id.as_deref(),
            Some("tool_second")
        );
        assert!(
            record.tool_observations[1]
                .error
                .as_deref()
                .unwrap()
                .contains("synthetic second failure")
        );
        assert_eq!(record.anchor, anchor);
        assert_eq!(record.usage_record.unwrap()["total_tokens"], 26);
    }

    #[test]
    fn native_location_backfill_recharges_the_shared_normalized_budget() {
        let source = source_fixture();
        let session = session_fixture();
        let mut messages = (0..25)
            .map(|index| MessageRow {
                id: format!("msg-{index}"),
                session_id: session.id.clone(),
                kind: "assistant".into(),
                sequence: index + 1,
                data: serde_json::json!({
                    "id":format!("msg-{index}"),"type":"assistant","content":[{"type":"text","text":"small"}],
                    "time":{"created":1_700_000_000_000_i64 + index}
                }),
            })
            .collect::<Vec<_>>();
        messages.push(MessageRow {
            id: "msg-location-switch".into(),
            session_id: session.id.clone(),
            kind: "location-switched".into(),
            sequence: 26,
            data: serde_json::json!({
                "id":"msg-location-switch","type":"location-switched",
                "previous":{"location":{"directory":"p".repeat(100_000)}},
                "location":{"directory":"/fixture/new"},
                "time":{"created":1_700_000_000_100_i64}
            }),
        });

        let mut budget = NormalizedRecordBudget::new();
        let batch = normalize_messages(&source, &session, &messages, &mut budget).unwrap();
        let records = batch.records;
        let normalized_bytes = records
            .iter()
            .map(|record| serde_json::to_vec(record).unwrap().len())
            .sum::<usize>();
        assert!(normalized_bytes <= super::super::NORMALIZED_RECORD_BUDGET_BYTES);
        assert_eq!(normalized_bytes, budget.used_bytes());
        assert_eq!(records.len(), messages.len());
        let backfilled = records
            .iter()
            .filter(|record| record.session_location.as_deref() == Some(&"p".repeat(100_000)))
            .count();
        assert!(backfilled > 0 && backfilled < 25);
        assert!(records[25].session_location.as_deref() == Some("/fixture/new"));
        assert!(
            records
                .iter()
                .enumerate()
                .all(|(index, record)| record.anchor.record_index == index as u64)
        );
    }

    #[test]
    fn conflicting_location_switch_history_warns_and_uses_latest_location() {
        let source = source_fixture();
        let session = session_fixture();
        let messages = [
            MessageRow {
                id: "first-switch".into(),
                session_id: session.id.clone(),
                kind: "location-switched".into(),
                sequence: 1,
                data: serde_json::json!({
                    "id":"first-switch","type":"location-switched",
                    "previous":{"location":{"directory":"/before"}},
                    "location":{"directory":"/current"},
                    "time":{"created":1_700_000_000_000_i64}
                }),
            },
            MessageRow {
                id: "conflicting-switch".into(),
                session_id: session.id.clone(),
                kind: "location-switched".into(),
                sequence: 2,
                data: serde_json::json!({
                    "id":"conflicting-switch","type":"location-switched",
                    "previous":{"location":{"directory":"/unexpected"}},
                    "location":{"directory":"/latest"},
                    "time":{"created":1_700_000_000_001_i64}
                }),
            },
            MessageRow {
                id: "after-switch".into(),
                session_id: session.id.clone(),
                kind: "assistant".into(),
                sequence: 3,
                data: serde_json::json!({
                    "id":"after-switch","type":"assistant","text":"after",
                    "time":{"created":1_700_000_000_002_i64}
                }),
            },
        ];
        let mut budget = NormalizedRecordBudget::new();
        let batch = normalize_messages(&source, &session, &messages, &mut budget).unwrap();
        assert!(batch.warnings.iter().any(|warning| {
            warning.contains("location-switch history has conflicting previous.location evidence")
        }));
        assert_eq!(
            batch.records[1].session_location.as_deref(),
            Some("/latest")
        );
        assert_eq!(
            batch.records[2].session_location.as_deref(),
            Some("/latest")
        );
    }

    #[test]
    fn export_inherited_session_identity_is_bounded_before_record_retention() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("export.json");
        let messages = (0..5_000)
            .map(|index| {
                serde_json::json!({
                    "id":format!("message-{index}"),"type":"assistant","text":"small",
                    "time":{"created":"2026-09-27T10:00:00Z"}
                })
            })
            .collect::<Vec<_>>();
        let bytes = serde_json::to_vec(&serde_json::json!({
            "info":{"id":"s".repeat(512),"projectID":"project_fixture","time":{"created":"2026-09-27T10:00:00Z"}},
            "messages":messages
        }))
        .unwrap();
        fs::write(&path, &bytes).unwrap();

        let snapshot = inspect_export(&path, &bytes).unwrap();
        let normalized_bytes = snapshot
            .records
            .iter()
            .map(|record| serde_json::to_vec(record).unwrap().len())
            .sum::<usize>();
        assert!(normalized_bytes <= super::super::NORMALIZED_RECORD_BUDGET_BYTES);
        assert!(snapshot.records.len() < messages.len());
        assert!(snapshot.coverage.truncated);
        assert!(snapshot.coverage.omitted_records > 0);
        assert!(snapshot.records.iter().all(|record| {
            record.session_thread_id.len() == 512
                && record.anchor.record_index < messages.len() as u64
        }));
        assert!(
            snapshot
                .records
                .windows(2)
                .all(|records| { records[1].anchor.record_index > records[0].anchor.record_index })
        );
    }
}
