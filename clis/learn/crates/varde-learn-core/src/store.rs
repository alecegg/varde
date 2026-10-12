//! The global SQLite store used by `varde-learn friction`.
//!
//! `friction.jsonl` is the source of truth; the SQLite database is a cache
//! rebuilt from the log. `Store::open` rebuilds the cache when it is absent or
//! when the log length or hash differs from `meta`, and migrates a database
//! that predates the log into it.

use std::collections::{HashMap, HashSet};
use std::ffi::OsStr;
use std::fs::{self, File, OpenOptions};
use std::io::ErrorKind;
use std::path::{Component, Path, PathBuf};
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant};

use fs2::FileExt;
use rusqlite::types::Value;
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params, params_from_iter};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::LearnError;
use crate::friction_log as flog;
use crate::friction_log::{Event, EventBody};
use crate::import::FrictionImportEntry;

const SCHEMA_VERSION: i64 = 4;

/// `meta` key holding the byte length of the log's complete lines.
const META_KEY_LOG_BYTES: &str = "log_bytes";
/// `meta` key holding the SHA-256 of the log's complete lines.
const META_KEY_LOG_HASH: &str = "log_hash";
/// `meta` key holding the persisted event-id to integer-id map.
const META_KEY_LOG_MAP: &str = "log_map";

/// Backup name suffix kept until one rebuild from the log succeeds.
const PRE_LOG_SUFFIX: &str = ".pre-log";

const DATABASE_FILE: &str = "learn.db";
const HISTORICAL_IDENTITY_VERSION: u32 = 1;
const MAX_HISTORICAL_FACTS_BYTES: usize = 1_048_576;
pub const DEFAULT_PAGE_LIMIT: usize = 100;
pub const MAX_PAGE_LIMIT: usize = 1_000;

const SCHEMA_V1: &str = r#"
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    repo_root TEXT,
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved', 'promoted', 'archived')),
    target TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS occurrences (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    cwd TEXT NOT NULL,
    repo_root TEXT,
    head_sha TEXT,
    evidence TEXT NOT NULL,
    cost TEXT
);

CREATE TABLE IF NOT EXISTS status_changes (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    from_status TEXT NOT NULL CHECK (from_status IN ('open', 'resolved', 'promoted', 'archived')),
    to_status TEXT NOT NULL CHECK (to_status IN ('open', 'resolved', 'promoted', 'archived')),
    reason TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS occurrences_item_id ON occurrences(item_id, id);
CREATE INDEX IF NOT EXISTS status_changes_item_id ON status_changes(item_id, id);
"#;

const SCHEMA_V2: &str = r#"
CREATE TABLE IF NOT EXISTS adoptions (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    summary TEXT NOT NULL,
    target_files TEXT NOT NULL,
    commit_sha TEXT,
    eval_before TEXT,
    eval_after TEXT
);

CREATE TABLE IF NOT EXISTS adoption_items (
    adoption_id INTEGER NOT NULL REFERENCES adoptions(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    PRIMARY KEY (adoption_id, item_id)
);
"#;

const SCHEMA_V3: &str = r#"
CREATE TABLE IF NOT EXISTS incident_provenance (
    incident_key TEXT PRIMARY KEY,
    occurrence_id INTEGER NOT NULL UNIQUE REFERENCES occurrences(id) ON DELETE CASCADE,
    identity_version INTEGER NOT NULL CHECK (identity_version = 1),
    harness TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    incident_kind TEXT NOT NULL,
    witness_id TEXT,
    source_id TEXT NOT NULL,
    record_index INTEGER NOT NULL CHECK (record_index >= 0),
    byte_start INTEGER NOT NULL CHECK (byte_start >= 0),
    byte_end INTEGER NOT NULL CHECK (byte_end >= byte_start),
    record_digest TEXT NOT NULL,
    payload_digest TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS incident_provenance_witness
    ON incident_provenance(harness, thread_id, witness_id);
"#;

const RECURRENCE_CTE: &str = r#"
WITH candidates AS (
    SELECT
        adoptions.id AS adoption_id,
        adoptions.at AS adoption_at,
        adoptions.summary AS adoption_summary,
        items.id AS item_id,
        items.slug AS item_slug,
        items.title AS item_title,
        items.source AS item_source,
        items.repo_root AS item_repo_root,
        items.status AS item_status,
        items.target AS item_target,
        items.created_at AS item_created_at,
        occurrences.id AS occurrence_id,
        occurrences.item_id AS occurrence_item_id,
        occurrences.at AS occurrence_at,
        occurrences.cwd AS occurrence_cwd,
        occurrences.repo_root AS occurrence_repo_root,
        occurrences.head_sha AS occurrence_head_sha,
        occurrences.evidence AS occurrence_evidence,
        occurrences.cost AS occurrence_cost,
        ROW_NUMBER() OVER (
            PARTITION BY occurrences.id
            ORDER BY {ADOPTION_JULIAN_DAY} DESC, adoptions.id DESC
        ) AS adoption_rank
    FROM occurrences
    JOIN items ON items.id = occurrences.item_id
    JOIN adoption_items ON adoption_items.item_id = items.id
    JOIN adoptions ON adoptions.id = adoption_items.adoption_id
    WHERE {OCCURRENCE_JULIAN_DAY} IS NOT NULL
      AND {ADOPTION_JULIAN_DAY} IS NOT NULL
      AND {OCCURRENCE_JULIAN_DAY} > {ADOPTION_JULIAN_DAY}
)
"#;

const OCCURRENCE_COLUMNS: &str =
    "o.id, o.item_id, o.at, o.cwd, o.repo_root, o.head_sha, o.evidence, o.cost,
    p.incident_key, p.identity_version, p.harness, p.thread_id, p.incident_kind, p.witness_id,
    p.source_id, p.record_index, p.byte_start, p.byte_end, p.record_digest, p.payload_digest";

const PROVENANCE_COLUMNS: &str =
    "incident_key, identity_version, harness, thread_id, incident_kind, witness_id,
     source_id, record_index, byte_start, byte_end, record_digest, payload_digest";

const FIXED_DATE_PREFIX_GLOB: &str = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*";

fn fixed_timestamp_julian_day(column: &str) -> String {
    format!("CASE WHEN {column} GLOB '{FIXED_DATE_PREFIX_GLOB}' THEN julianday({column}) END")
}

fn recurrence_cte() -> String {
    RECURRENCE_CTE
        .replace(
            "{OCCURRENCE_JULIAN_DAY}",
            &fixed_timestamp_julian_day("occurrences.at"),
        )
        .replace(
            "{ADOPTION_JULIAN_DAY}",
            &fixed_timestamp_julian_day("adoptions.at"),
        )
}

/// A friction item row exposed without giving callers direct SQL access.
#[derive(Debug, Clone, Serialize)]
pub struct FrictionItem {
    pub id: i64,
    pub slug: String,
    pub title: String,
    pub source: String,
    pub repo_root: Option<String>,
    pub status: String,
    pub target: Option<String>,
    pub created_at: String,
}

/// Valid statuses enforced by the store schema.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FrictionStatus {
    Open,
    Resolved,
    Promoted,
    Archived,
}

impl FrictionStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Resolved => "resolved",
            Self::Promoted => "promoted",
            Self::Archived => "archived",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value.to_ascii_lowercase().as_str() {
            "open" => Some(Self::Open),
            "resolved" => Some(Self::Resolved),
            "promoted" => Some(Self::Promoted),
            "archived" => Some(Self::Archived),
            _ => None,
        }
    }
}

/// Rows and pagination metadata returned by list operations.
#[derive(Debug, Clone, Serialize)]
pub struct StorePage<T> {
    pub items: Vec<T>,
    pub total: usize,
    pub offset: usize,
    pub limit: usize,
    pub truncated: bool,
    pub next_offset: Option<usize>,
}

impl<T> StorePage<T> {
    fn new(items: Vec<T>, total: usize, page: PageRequest) -> Self {
        let next_offset = page
            .offset
            .checked_add(items.len())
            .filter(|next| *next < total);
        Self {
            items,
            total,
            offset: page.offset,
            limit: page.limit,
            truncated: next_offset.is_some(),
            next_offset,
        }
    }
}

/// One bounded result window for collection reads.
#[derive(Debug, Clone, Copy)]
pub struct PageRequest {
    pub offset: usize,
    pub limit: usize,
}

impl Default for PageRequest {
    fn default() -> Self {
        Self {
            offset: 0,
            limit: DEFAULT_PAGE_LIMIT,
        }
    }
}

/// Item filters and page request for `friction list`.
#[derive(Debug, Clone)]
pub struct FrictionListRequest {
    pub status: Option<FrictionStatus>,
    pub source: Option<String>,
    pub repo_root: Option<PathBuf>,
    pub global: bool,
    pub text: Option<String>,
    pub cwd: PathBuf,
    pub page: PageRequest,
}

/// One persisted occurrence row.
#[derive(Debug, Clone, Serialize)]
pub struct FrictionOccurrence {
    pub id: i64,
    pub item_id: i64,
    pub at: String,
    pub cwd: String,
    pub repo_root: Option<String>,
    pub head_sha: Option<String>,
    pub evidence: String,
    pub cost: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provenance: Option<FrictionIncidentProvenance>,
}

/// Stable incident identity and the separate source anchor that supports it.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct FrictionIncidentProvenance {
    pub incident_key: String,
    pub identity_version: u32,
    pub harness: String,
    pub thread_id: String,
    pub incident_kind: String,
    pub witness_id: Option<String>,
    pub source_id: String,
    pub record_index: u64,
    pub byte_start: u64,
    pub byte_end: u64,
    pub record_digest: String,
    pub payload_digest: String,
}

/// Source-event identity and its physical verification anchor.
#[derive(Debug, Clone)]
pub struct HistoricalWitness {
    pub harness: String,
    pub thread_id: String,
    pub incident_kind: String,
    pub witness_id: Option<String>,
    pub source_id: String,
    pub record_index: u64,
    pub byte_start: u64,
    pub byte_end: u64,
    pub record_digest: String,
}

/// Item grouping selected for a historical incident.
#[derive(Debug, Clone)]
pub enum HistoricalItemMode {
    Append {
        item_id: i64,
    },
    Create {
        source: String,
        title: String,
        target: Option<String>,
        repo_root: Option<String>,
    },
}

/// Historical evidence supplied only after the source witness has been verified.
#[derive(Debug, Clone)]
pub struct HistoricalOccurrenceRequest {
    pub at: String,
    pub cwd: String,
    pub repo_root: Option<String>,
    pub head_sha: Option<String>,
    pub evidence: String,
    /// Parsed native event facts and relevant historical context only. Source anchors,
    /// generated report text, and item metadata are excluded from the payload digest.
    pub canonical_facts: serde_json::Value,
    pub witness: HistoricalWitness,
}

/// Create or append one verified historical occurrence.
#[derive(Debug, Clone)]
pub struct HistoricalCaptureRequest {
    pub mode: HistoricalItemMode,
    pub occurrence: HistoricalOccurrenceRequest,
}

/// Result of a historical capture, including whether it created a new occurrence.
#[derive(Debug, Clone, Serialize)]
pub struct HistoricalCaptureResult {
    pub item: FrictionItem,
    pub occurrence: FrictionOccurrence,
    pub created: bool,
}

/// One persisted status transition row.
#[derive(Debug, Clone, Serialize)]
pub struct FrictionStatusChange {
    pub id: i64,
    pub item_id: i64,
    pub at: String,
    pub from_status: String,
    pub to_status: String,
    pub reason: String,
}

/// One historical occurrence paired with the latest adoption that preceded it.
#[derive(Debug, Clone, Serialize)]
pub struct FrictionRecurrence {
    pub adoption_id: i64,
    pub adoption_at: String,
    pub summary: String,
    pub item: FrictionItem,
    pub occurrence: FrictionOccurrence,
}

/// A bounded recurrence page and the number of linked timestamps it could not compare.
#[derive(Debug, Clone, Serialize)]
pub struct FrictionRecurrenceReport {
    pub page: StorePage<FrictionRecurrence>,
    pub skipped_invalid_timestamps: usize,
}

/// Item details with bounded occurrence and status history pages.
#[derive(Debug, Clone, Serialize)]
pub struct FrictionShow {
    pub item: FrictionItem,
    pub occurrences: StorePage<FrictionOccurrence>,
    pub status_changes: StorePage<FrictionStatusChange>,
}

/// One item with its complete, unpaged export history from a consistent snapshot.
#[derive(Debug, Clone)]
pub struct FrictionExportItem {
    pub item: FrictionItem,
    pub occurrences: Vec<FrictionOccurrence>,
    pub status_changes: Vec<FrictionStatusChange>,
}

/// Whether an add operation creates a friction item or appends to one.
#[derive(Debug, Clone)]
pub enum FrictionAddMode {
    Create {
        source: String,
        title: String,
        target: Option<String>,
        global: bool,
    },
    Append {
        item_id: i64,
    },
}

/// An item operation and the occurrence evidence captured from the current process.
#[derive(Debug, Clone)]
pub struct FrictionAddRequest {
    pub mode: FrictionAddMode,
    pub evidence: String,
    pub cwd: PathBuf,
}

/// Validated input for recording an applied change against friction items.
#[derive(Debug, Clone)]
pub struct AdoptionRecordRequest {
    pub item_ids: Vec<i64>,
    pub summary: String,
    pub files: Vec<String>,
    pub commit_sha: Option<String>,
    pub eval_before: Option<String>,
    pub eval_after: Option<String>,
}

/// The adoption row and linked item identifiers written by one transaction.
#[derive(Debug, Clone, Serialize)]
pub struct AdoptionRecord {
    pub id: i64,
    pub at: String,
    pub summary: String,
    pub files: Vec<String>,
    pub commit_sha: Option<String>,
    pub eval_before: Option<String>,
    pub eval_after: Option<String>,
    pub item_ids: Vec<i64>,
}

/// Open one store directory, creating it, the friction log, and the database
/// cache rebuilt from it.
pub struct Store {
    connection: Connection,
    database_path: PathBuf,
    store_dir: PathBuf,
    log_handle: File,
}

impl Store {
    /// Resolve the global store directory from the process environment and config.
    pub fn open_global() -> Result<Self, LearnError> {
        Self::open(&resolve_store_dir()?)
    }

    /// Check the configured store location without creating its directory or database.
    pub fn validate_global_path() -> Result<(), LearnError> {
        let store_dir = resolve_directory(&resolve_store_dir()?, 0)?;
        let database_path = resolve_directory(&store_dir.join(DATABASE_FILE), 0)?;
        // `Store::open` writes a covering `.gitignore` into a store directory
        // that has none, so the dry run predicts that outcome.
        let bootstrapped = !store_dir.join(".gitignore").exists()
            && database_path.parent() == Some(store_dir.as_path());
        reject_git_path_with(&database_path, bootstrapped)
    }

    /// Open a store directory directly. The database filename is always `learn.db`.
    ///
    /// The `.gitignore` and `.gitattributes` are written first so a store inside
    /// a Git checkout opens when `learn.db*` is git-ignored there; otherwise the
    /// path is still refused.
    pub fn open(store_dir: &Path) -> Result<Self, LearnError> {
        let store_dir = resolve_directory(store_dir, 0)?;
        fs::create_dir_all(&store_dir).map_err(|source| LearnError::StoreIo {
            operation: "create",
            path: store_dir.clone(),
            source,
        })?;
        let first_open = !store_dir.join(".gitignore").exists();
        flog::ensure_git_files(&store_dir)?;

        // Resolve again after creation so an existing symlink cannot redirect the open.
        let store_dir = resolve_directory(&store_dir, 0)?;
        let database_path = resolve_directory(&store_dir.join(DATABASE_FILE), 0)?;
        reject_git_path(&database_path)?;
        let _init_lock = acquire_init_lock(&database_path)?;
        let database_path = resolve_directory(&database_path, 0)?;
        reject_git_path(&database_path)?;
        if first_open && let Some(repo_root) = work_tree_root(&store_dir) {
            eprintln!(
                "notice: new friction store {} is inside Git work tree {}; commit friction.jsonl only to a private repository",
                store_dir.display(),
                repo_root.display()
            );
        }

        prepare_store(&store_dir, &database_path)?;
        let log_handle = flog::open_log(&store_dir)?;
        let mut connection =
            Connection::open(&database_path).map_err(|source| LearnError::StoreDatabase {
                path: database_path.clone(),
                source,
            })?;
        varde_core::sqlite::configure_connection(&connection)
            .map_err(|source| db_error(&database_path, source))?;
        migrate(&mut connection, &database_path)?;
        lock_log(&log_handle, &store_dir)?;
        let refreshed = refresh_cache_if_stale(&mut connection, &store_dir, &database_path);
        let _ = FileExt::unlock(&log_handle);
        refreshed?;

        Ok(Self {
            connection,
            database_path,
            store_dir,
            log_handle,
        })
    }

    /// Run one mutation while holding the exclusive log lock, so the event
    /// append and the cache rebuild serialize with other writers and the
    /// appended event can never race a fold.
    fn mutate<T>(
        &mut self,
        operation: impl FnOnce(&mut Connection, &mut File) -> Result<T, LearnError>,
    ) -> Result<T, LearnError> {
        lock_log(&self.log_handle, &self.store_dir)?;
        // Another process may have appended since this store was opened or last
        // mutated; apply on top of a current cache, never a stale one.
        let result =
            refresh_cache_if_stale(&mut self.connection, &self.store_dir, &self.database_path)
                .and_then(|()| operation(&mut self.connection, &mut self.log_handle));
        let _ = FileExt::unlock(&self.log_handle);
        result
    }

    pub fn database_path(&self) -> &Path {
        &self.database_path
    }

    /// Return one bounded, filtered item page.
    pub fn list_items(
        &mut self,
        request: &FrictionListRequest,
    ) -> Result<StorePage<FrictionItem>, LearnError> {
        let (limit_value, offset_value) = validate_page(request.page)?;
        if request.global && request.repo_root.is_some() {
            return Err(invalid_store_input(
                "--repo and --global cannot be combined",
            ));
        }
        if let Some(source) = &request.source {
            require_nonblank(source, "source")?;
        }
        if let Some(text) = &request.text {
            require_nonblank(text, "text")?;
        }
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Deferred)
            .map_err(|source| db_error(&self.database_path, source))?;

        let mut conditions = Vec::new();
        let mut values = Vec::new();
        if let Some(status) = request.status {
            conditions.push(format!(
                "items.status = {}",
                push_value(&mut values, Value::Text(status.as_str().to_owned()))
            ));
        }
        if let Some(source) = &request.source {
            conditions.push(format!(
                "items.source = {}",
                push_value(&mut values, Value::Text(source.clone()))
            ));
        }
        if request.global {
            conditions.push("items.repo_root IS NULL".to_owned());
        } else if let Some(repo_root) = &request.repo_root {
            let repo_root = normalize_scope_path(repo_root, &request.cwd);
            conditions.push(format!(
                "items.repo_root = {}",
                push_value(
                    &mut values,
                    Value::Text(repo_root.to_string_lossy().into_owned())
                )
            ));
        }
        let where_clause = if conditions.is_empty() {
            "1 = 1".to_owned()
        } else {
            conditions.join(" AND ")
        };
        let page = if let Some(text) = &request.text {
            read_text_filtered_page(
                &transaction,
                &where_clause,
                &values,
                text,
                request.page,
                &self.database_path,
            )?
        } else {
            let count: i64 = transaction
                .query_row(
                    &format!("SELECT COUNT(*) FROM items WHERE {where_clause}"),
                    params_from_iter(values.iter()),
                    |row| row.get(0),
                )
                .map_err(|source| db_error(&self.database_path, source))?;
            let mut page_values = values;
            let limit = push_value(&mut page_values, Value::Integer(limit_value));
            let offset = push_value(&mut page_values, Value::Integer(offset_value));
            let items = {
                let mut statement = transaction
                    .prepare(&format!(
                        "SELECT id, slug, title, source, repo_root, status, target, created_at
                         FROM items WHERE {where_clause} ORDER BY id
                         LIMIT {limit} OFFSET {offset}"
                    ))
                    .map_err(|source| db_error(&self.database_path, source))?;
                let rows = statement
                    .query_map(params_from_iter(page_values.iter()), read_item)
                    .map_err(|source| db_error(&self.database_path, source))?;
                rows.collect::<Result<Vec<_>, _>>()
                    .map_err(|source| db_error(&self.database_path, source))?
            };
            StorePage::new(items, count as usize, request.page)
        };
        transaction
            .commit()
            .map_err(|source| db_error(&self.database_path, source))?;
        Ok(page)
    }

    /// Read an item by numeric ID or slug with bounded occurrence/history pages.
    pub fn show_friction(
        &mut self,
        identifier: &str,
        page: PageRequest,
    ) -> Result<FrictionShow, LearnError> {
        validate_page(page)?;
        require_nonblank(identifier, "identifier")?;
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Deferred)
            .map_err(|source| db_error(&self.database_path, source))?;
        let item = get_item_by_identifier(&transaction, identifier, &self.database_path)?;
        let occurrences = read_occurrences(&transaction, item.id, page, &self.database_path)?;
        let status_changes = read_status_changes(&transaction, item.id, page, &self.database_path)?;
        let result = FrictionShow {
            item,
            occurrences,
            status_changes,
        };
        transaction
            .commit()
            .map_err(|source| db_error(&self.database_path, source))?;
        Ok(result)
    }

    /// Read every item and its complete history from one consistent snapshot.
    pub fn export_items(&mut self) -> Result<Vec<FrictionExportItem>, LearnError> {
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Deferred)
            .map_err(|source| db_error(&self.database_path, source))?;
        let items = {
            let mut statement = transaction
                .prepare(
                    "SELECT id, slug, title, source, repo_root, status, target, created_at
                     FROM items ORDER BY id",
                )
                .map_err(|source| db_error(&self.database_path, source))?;
            let rows = statement
                .query_map([], read_item)
                .map_err(|source| db_error(&self.database_path, source))?;
            rows.collect::<Result<Vec<_>, _>>()
                .map_err(|source| db_error(&self.database_path, source))?
        };
        let mut exports = Vec::with_capacity(items.len());
        for item in items {
            exports.push(FrictionExportItem {
                occurrences: read_all_occurrences(&transaction, item.id, &self.database_path)?,
                status_changes: read_all_status_changes(
                    &transaction,
                    item.id,
                    &self.database_path,
                )?,
                item,
            });
        }
        transaction
            .commit()
            .map_err(|source| db_error(&self.database_path, source))?;
        Ok(exports)
    }

    /// Record a verified historical event without consulting the current clock or Git state.
    pub fn record_historical_occurrence(
        &mut self,
        request: HistoricalCaptureRequest,
    ) -> Result<HistoricalCaptureResult, LearnError> {
        let provenance = provenance_for(&request.occurrence)?;
        let occurrence = &request.occurrence;
        if occurrence.at.trim().is_empty()
            || occurrence.cwd.trim().is_empty()
            || occurrence.evidence.trim().is_empty()
        {
            return Err(invalid_store_input(
                "historical occurrence time, cwd, and evidence must not be blank",
            ));
        }
        if let HistoricalItemMode::Create {
            source,
            title,
            target,
            repo_root,
        } = &request.mode
        {
            require_nonblank(source, "source")?;
            require_nonblank(title, "title")?;
            if let Some(target) = target {
                require_nonblank(target, "target")?;
            }
            if let Some(repo_root) = repo_root {
                require_nonblank(repo_root, "repository root")?;
            }
        }
        let store_dir = self.store_dir.clone();
        let database_path = self.database_path.clone();
        self.mutate(|connection, log_handle| {
            if request.occurrence.witness.witness_id.is_none() {
                let matches = {
                    let mut statement = connection
                        .prepare(
                            "SELECT occurrence_id, incident_kind, record_index, record_digest, payload_digest
                             FROM incident_provenance
                             WHERE harness = ?1 AND thread_id = ?2 AND witness_id IS NULL
                               AND (record_index = ?3 OR record_digest = ?4)
                             ORDER BY record_index, record_digest, incident_kind",
                        )
                        .map_err(|source| db_error(&database_path, source))?;
                    let rows = statement
                        .query_map(
                            params![
                                request.occurrence.witness.harness,
                                request.occurrence.witness.thread_id,
                                request.occurrence.witness.record_index as i64,
                                request.occurrence.witness.record_digest,
                            ],
                            |row| {
                                Ok((
                                    row.get::<_, i64>(0)?,
                                    row.get::<_, String>(1)?,
                                    row.get::<_, i64>(2)? as u64,
                                    row.get::<_, String>(3)?,
                                    row.get::<_, String>(4)?,
                                ))
                            },
                        )
                        .map_err(|source| db_error(&database_path, source))?;
                    rows.collect::<Result<Vec<_>, _>>()
                        .map_err(|source| db_error(&database_path, source))?
                };
                if !matches.is_empty() {
                    let [(occurrence_id, incident_kind, record_index, record_digest, existing_digest)] =
                        matches.as_slice()
                    else {
                        return Err(incident_conflict(&provenance.incident_key));
                    };
                    let witness = &request.occurrence.witness;
                    if *record_index != witness.record_index
                        || record_digest != &witness.record_digest
                    {
                        return Err(incident_conflict(&provenance.incident_key));
                    }
                    if incident_kind != &witness.incident_kind {
                        return Err(LearnError::Diagnose {
                            code: "diagnose_incident_kind_conflict",
                            message: "the verified fallback event is already recorded under a different incident kind".into(),
                        });
                    }
                    let occurrence =
                        occurrence_from_id(connection, *occurrence_id, &database_path)?;
                    if existing_digest != &provenance.payload_digest
                        || occurrence.at != request.occurrence.at
                        || occurrence.cwd != request.occurrence.cwd
                        || occurrence.repo_root != request.occurrence.repo_root
                        || occurrence.head_sha != request.occurrence.head_sha
                    {
                        return Err(incident_conflict(&provenance.incident_key));
                    }
                    let item = get_item(connection, occurrence.item_id, &database_path)?;
                    return Ok(HistoricalCaptureResult {
                        item,
                        occurrence,
                        created: false,
                    });
                }
            }

            let existing = connection
                .query_row(
                    "SELECT occurrence_id, payload_digest FROM incident_provenance WHERE incident_key = ?1",
                    [&provenance.incident_key],
                    |row| Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?)),
                )
                .optional()
                .map_err(|source| db_error(&database_path, source))?;
            if let Some((occurrence_id, existing_digest)) = existing {
                let occurrence = occurrence_from_id(connection, occurrence_id, &database_path)?;
                if existing_digest != provenance.payload_digest
                    || occurrence.at != request.occurrence.at
                    || occurrence.cwd != request.occurrence.cwd
                    || occurrence.repo_root != request.occurrence.repo_root
                    || occurrence.head_sha != request.occurrence.head_sha
                {
                    return Err(incident_conflict(&provenance.incident_key));
                }
                let item = get_item(connection, occurrence.item_id, &database_path)?;
                return Ok(HistoricalCaptureResult {
                    item,
                    occurrence,
                    created: false,
                });
            }

            let mut events = Vec::new();
            let (item_event_id, occurrence_ts) = match &request.mode {
                HistoricalItemMode::Append { item_id } => {
                    if *item_id <= 0 {
                        return Err(invalid_store_input(
                            "item ID must be a positive integer",
                        ));
                    }
                    get_item(connection, *item_id, &database_path)?;
                    (
                        item_event_id(connection, *item_id, &database_path)?,
                        next_event_ts(&store_dir)?,
                    )
                }
                HistoricalItemMode::Create {
                    source,
                    title,
                    target,
                    repo_root,
                } => {
                    let created_at = next_event_ts(&store_dir)?;
                    let item_event = Event::at(
                        created_at.clone(),
                        repo_root.clone(),
                        EventBody::ItemAdded(flog::ItemAdded {
                            title: title.clone(),
                            source: source.clone(),
                            repo_root: repo_root.clone(),
                            target: target.clone(),
                        }),
                    );
                    let id = item_event.id.clone();
                    events.push(item_event);
                    (id, bump_timestamp(&created_at))
                }
            };
            let occurrence_event = Event::at(
                occurrence_ts,
                None,
                EventBody::OccurrenceAppended(Box::new(flog::OccurrenceAppended {
                    item: item_event_id.clone(),
                    at: request.occurrence.at.clone(),
                    cwd: request.occurrence.cwd.clone(),
                    repo_root: request.occurrence.repo_root.clone(),
                    head_sha: request.occurrence.head_sha.clone(),
                    evidence: request.occurrence.evidence.clone(),
                    cost: None,
                    provenance: Some(provenance.clone()),
                })),
            );
            let occurrence_event_id = occurrence_event.id.clone();
            events.push(occurrence_event);
            for event in &events {
                flog::append(&store_dir, log_handle, event)?;
            }
            apply_events(connection, &store_dir, &database_path, &events, None)?;
            let map = read_log_id_map(connection, &database_path)?;
            let item_id = map.items.get(&item_event_id).copied().ok_or_else(|| {
                invalid_store_input("rebuilt historical capture lost its item event")
            })?;
            let occurrence_id = map
                .occurrences
                .get(&occurrence_event_id)
                .copied()
                .ok_or_else(|| {
                    invalid_store_input("rebuilt historical capture lost its occurrence event")
                })?;
            let item = get_item(connection, item_id, &database_path)?;
            let occurrence = occurrence_from_id(connection, occurrence_id, &database_path)?;
            Ok(HistoricalCaptureResult {
                item,
                occurrence,
                created: true,
            })
        })
    }

    /// Find all incident kinds already attributed to one stable native witness.
    pub fn find_historical_witness(
        &self,
        harness: &str,
        thread_id: &str,
        witness_id: &str,
    ) -> Result<Vec<FrictionIncidentProvenance>, LearnError> {
        require_nonblank(harness, "harness")?;
        require_nonblank(thread_id, "thread ID")?;
        require_nonblank(witness_id, "witness ID")?;
        let mut statement = self
            .connection
            .prepare(
                "SELECT incident_key, identity_version, harness, thread_id, incident_kind,
                        witness_id, source_id, record_index, byte_start, byte_end,
                        record_digest, payload_digest
                 FROM incident_provenance
                 WHERE harness = ?1 AND thread_id = ?2 AND witness_id = ?3
                 ORDER BY incident_kind, incident_key",
            )
            .map_err(|source| db_error(&self.database_path, source))?;
        let rows = statement
            .query_map(params![harness, thread_id, witness_id], |row| {
                read_provenance(row, 0)
                    .map(|provenance| provenance.expect("witness query selects a provenance row"))
            })
            .map_err(|source| db_error(&self.database_path, source))?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|source| db_error(&self.database_path, source))
    }

    /// Find fallback witnesses whose logical position or digest overlaps an event.
    /// Callers must reject rewritten and repositioned matches instead of assigning
    /// them a new event identity.
    pub fn find_historical_fallback_witness(
        &self,
        harness: &str,
        thread_id: &str,
        record_index: u64,
        record_digest: &str,
    ) -> Result<Vec<FrictionIncidentProvenance>, LearnError> {
        require_nonblank(harness, "harness")?;
        require_nonblank(thread_id, "thread ID")?;
        if record_index > i64::MAX as u64 || !is_sha256_digest(record_digest) {
            return Err(invalid_store_input("fallback witness anchor is invalid"));
        }
        let mut statement = self
            .connection
            .prepare(
                "SELECT incident_key, identity_version, harness, thread_id, incident_kind,
                        witness_id, source_id, record_index, byte_start, byte_end,
                        record_digest, payload_digest
                 FROM incident_provenance
                 WHERE harness = ?1 AND thread_id = ?2 AND witness_id IS NULL
                   AND (record_index = ?3 OR record_digest = ?4)
                 ORDER BY record_index, record_digest, incident_kind",
            )
            .map_err(|source| db_error(&self.database_path, source))?;
        let rows = statement
            .query_map(
                params![harness, thread_id, record_index as i64, record_digest],
                |row| {
                    read_provenance(row, 0)
                        .map(|provenance| provenance.expect("fallback query selects provenance"))
                },
            )
            .map_err(|source| db_error(&self.database_path, source))?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|source| db_error(&self.database_path, source))
    }

    /// Append a status event and rebuild the cache under one log lock.
    pub fn set_friction_status(
        &mut self,
        item_id: i64,
        status: FrictionStatus,
        reason: &str,
    ) -> Result<FrictionItem, LearnError> {
        if item_id <= 0 {
            return Err(invalid_store_input("item ID must be a positive integer"));
        }
        require_nonblank(reason, "reason")?;
        let store_dir = self.store_dir.clone();
        let database_path = self.database_path.clone();
        self.mutate(|connection, log_handle| {
            let item = get_item(connection, item_id, &database_path)?;
            let item_event = item_event_id(connection, item_id, &database_path)?;
            let at = flog::now_timestamp();
            let ts = next_event_ts(&store_dir)?;
            let event = Event::at(
                ts,
                item.repo_root.clone(),
                EventBody::StatusChanged(flog::StatusChanged {
                    item: item_event,
                    at,
                    from: item.status,
                    to: status.as_str().to_owned(),
                    reason: reason.to_owned(),
                }),
            );
            flog::append(&store_dir, log_handle, &event)?;
            apply_events(
                connection,
                &store_dir,
                &database_path,
                std::slice::from_ref(&event),
                None,
            )
        })?;
        get_item(&self.connection, item_id, &self.database_path)
    }

    /// Record an adoption, link its source items, and promote them atomically.
    pub fn record_adoption(
        &mut self,
        request: AdoptionRecordRequest,
    ) -> Result<AdoptionRecord, LearnError> {
        self.record_adoption_at(request, flog::now_timestamp())
    }

    fn record_adoption_at(
        &mut self,
        request: AdoptionRecordRequest,
        at: String,
    ) -> Result<AdoptionRecord, LearnError> {
        if request.item_ids.is_empty() {
            return Err(invalid_store_input("at least one item ID is required"));
        }
        let mut seen = HashSet::with_capacity(request.item_ids.len());
        for item_id in &request.item_ids {
            if *item_id <= 0 {
                return Err(invalid_store_input("item IDs must be positive integers"));
            }
            if !seen.insert(*item_id) {
                return Err(invalid_store_input("item IDs must not contain duplicates"));
            }
        }
        require_nonblank(&request.summary, "summary")?;
        if request.files.is_empty() {
            return Err(invalid_store_input("at least one file path is required"));
        }
        for file in &request.files {
            require_nonblank(file, "file path")?;
        }
        if let Some(commit_sha) = &request.commit_sha {
            require_nonblank(commit_sha, "commit SHA")?;
        }
        for (field, contents) in [
            ("eval-before", request.eval_before.as_deref()),
            ("eval-after", request.eval_after.as_deref()),
        ] {
            if let Some(contents) = contents {
                serde_json::from_str::<serde_json::Value>(contents).map_err(|error| {
                    invalid_store_input(format!("{field} must contain valid JSON: {error}"))
                })?;
            }
        }

        let store_dir = self.store_dir.clone();
        let database_path = self.database_path.clone();
        self.mutate(|connection, log_handle| {
            let items = request
                .item_ids
                .iter()
                .map(|item_id| get_item(connection, *item_id, &database_path))
                .collect::<Result<Vec<_>, _>>()?;
            let item_event_ids = items
                .iter()
                .map(|item| item_event_id(connection, item.id, &database_path))
                .collect::<Result<Vec<_>, _>>()?;
            let adoption_id: i64 = connection
                .query_row("SELECT COALESCE(MAX(id), 0) + 1 FROM adoptions", [], |row| {
                    row.get(0)
                })
                .map_err(|source| db_error(&database_path, source))?;
            let mut ts = next_event_ts(&store_dir)?;
            let mut events = Vec::new();
            for (item, item_event) in items.iter().zip(&item_event_ids) {
                let event = Event::at(
                    ts.clone(),
                    item.repo_root.clone(),
                    EventBody::StatusChanged(flog::StatusChanged {
                        item: item_event.clone(),
                        at: at.clone(),
                        from: item.status.clone(),
                        to: "promoted".to_owned(),
                        reason: format!("Recorded adoption {adoption_id}"),
                    }),
                );
                flog::append(&store_dir, log_handle, &event)?;
                events.push(event);
                ts = bump_timestamp(&ts);
            }
            let adoption_event = Event::at(
                ts,
                None,
                EventBody::AdoptionRecorded(flog::AdoptionRecorded {
                    at: at.clone(),
                    summary: request.summary.clone(),
                    files: request.files.clone(),
                    commit_sha: request.commit_sha.clone(),
                    eval_before: request.eval_before.clone(),
                    eval_after: request.eval_after.clone(),
                    items: item_event_ids.clone(),
                }),
            );
            flog::append(&store_dir, log_handle, &adoption_event)?;
            events.push(adoption_event);
            apply_events(connection, &store_dir, &database_path, &events, None)?;
            let persisted = connection
                .query_row(
                    "SELECT id, at, summary, target_files, commit_sha, eval_before, eval_after
                     FROM adoptions WHERE id = ?1",
                    params![adoption_id],
                    |row| {
                        Ok((
                            row.get::<_, i64>(0)?,
                            row.get::<_, String>(1)?,
                            row.get::<_, String>(2)?,
                            row.get::<_, String>(3)?,
                            row.get::<_, Option<String>>(4)?,
                            row.get::<_, Option<String>>(5)?,
                            row.get::<_, Option<String>>(6)?,
                        ))
                    },
                )
                .map_err(|source| db_error(&database_path, source))?;
            let persisted_files = serde_json::from_str(&persisted.3).map_err(|error| {
                invalid_store_input(format!(
                    "could not read stored adoption file paths: {error}"
                ))
            })?;
            let linked_item_ids = {
                let mut statement = connection
                    .prepare(
                        "SELECT item_id FROM adoption_items WHERE adoption_id = ?1 ORDER BY item_id",
                    )
                    .map_err(|source| db_error(&database_path, source))?;
                let rows = statement
                    .query_map([adoption_id], |row| row.get::<_, i64>(0))
                    .map_err(|source| db_error(&database_path, source))?;
                rows.collect::<Result<Vec<_>, _>>()
                    .map_err(|source| db_error(&database_path, source))?
            };
            Ok(AdoptionRecord {
                id: persisted.0,
                at: persisted.1,
                summary: persisted.2,
                files: persisted_files,
                commit_sha: persisted.4,
                eval_before: persisted.5,
                eval_after: persisted.6,
                item_ids: linked_item_ids,
            })
        })
    }

    /// Report historical occurrences strictly after their most recent valid adoption.
    pub fn list_recurrences(
        &mut self,
        page: PageRequest,
    ) -> Result<FrictionRecurrenceReport, LearnError> {
        let (limit, offset) = validate_page(page)?;
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Deferred)
            .map_err(|source| db_error(&self.database_path, source))?;
        let recurrence_cte = recurrence_cte();
        let total: i64 = transaction
            .query_row(
                &format!(
                    "{recurrence_cte} SELECT COUNT(*) FROM candidates WHERE adoption_rank = 1"
                ),
                [],
                |row| row.get(0),
            )
            .map_err(|source| db_error(&self.database_path, source))?;
        let skipped_invalid_timestamps: i64 = transaction
            .query_row(
                &format!(
                    "SELECT
                    (SELECT COUNT(*) FROM occurrences
                     WHERE {} IS NULL
                       AND EXISTS (SELECT 1 FROM adoption_items WHERE item_id = occurrences.item_id))
                    +
                    (SELECT COUNT(*) FROM adoptions
                     WHERE {} IS NULL
                       AND EXISTS (SELECT 1 FROM adoption_items WHERE adoption_id = adoptions.id))",
                    fixed_timestamp_julian_day("occurrences.at"),
                    fixed_timestamp_julian_day("adoptions.at"),
                ),
                [],
                |row| row.get(0),
            )
            .map_err(|source| db_error(&self.database_path, source))?;
        let recurrences = {
            let mut statement = transaction
                .prepare(&format!(
                    "{recurrence_cte}
                     SELECT adoption_id, adoption_at, adoption_summary,
                            item_id, item_slug, item_title, item_source, item_repo_root,
                            item_status, item_target, item_created_at,
                            occurrence_id, occurrence_item_id, occurrence_at, occurrence_cwd,
                            occurrence_repo_root, occurrence_head_sha, occurrence_evidence,
                            occurrence_cost
                     FROM candidates WHERE adoption_rank = 1
                     ORDER BY julianday(occurrence_at), occurrence_id
                     LIMIT ?1 OFFSET ?2"
                ))
                .map_err(|source| db_error(&self.database_path, source))?;
            let rows = statement
                .query_map(params![limit, offset], read_recurrence)
                .map_err(|source| db_error(&self.database_path, source))?;
            rows.collect::<Result<Vec<_>, _>>()
                .map_err(|source| db_error(&self.database_path, source))?
        };
        transaction
            .commit()
            .map_err(|source| db_error(&self.database_path, source))?;
        Ok(FrictionRecurrenceReport {
            page: StorePage::new(recurrences, total as usize, page),
            skipped_invalid_timestamps: skipped_invalid_timestamps as usize,
        })
    }

    /// Create an item and its first occurrence, or append one occurrence atomically.
    pub fn add_friction(
        &mut self,
        request: FrictionAddRequest,
    ) -> Result<FrictionItem, LearnError> {
        require_nonblank(&request.evidence, "evidence")?;
        if request.cwd.as_os_str().is_empty() {
            return Err(invalid_store_input("cwd must not be blank"));
        }
        match &request.mode {
            FrictionAddMode::Create {
                source,
                title,
                target,
                ..
            } => {
                require_nonblank(source, "source")?;
                require_nonblank(title, "title")?;
                if let Some(target) = target {
                    require_nonblank(target, "target")?;
                }
            }
            FrictionAddMode::Append { item_id } if *item_id <= 0 => {
                return Err(invalid_store_input("item ID must be a positive integer"));
            }
            FrictionAddMode::Append { .. } => {}
        }
        let context = repository_context(&request.cwd)?;
        let store_dir = self.store_dir.clone();
        let database_path = self.database_path.clone();
        let item_id = self.mutate(|connection, log_handle| {
            let mut events = Vec::new();
            let (item_event_id, occurrence_ts) = match &request.mode {
                FrictionAddMode::Create {
                    source,
                    title,
                    target,
                    global,
                } => {
                    let redacted_title = crate::redact::apply(title);
                    let redacted_source = crate::redact::apply(source);
                    let redacted_target = target.as_deref().map(crate::redact::apply);
                    let redacted_count = redacted_title.count
                        + redacted_source.count
                        + redacted_target.as_ref().map_or(0, |value| value.count);
                    let created_at = next_event_ts(&store_dir)?;
                    let item_repo_root = if *global {
                        None
                    } else {
                        context.repo_root.clone()
                    };
                    let mut item_event = Event::at(
                        created_at.clone(),
                        item_repo_root.clone(),
                        EventBody::ItemAdded(flog::ItemAdded {
                            title: redacted_title.text,
                            source: redacted_source.text,
                            repo_root: item_repo_root,
                            target: redacted_target.map(|value| value.text),
                        }),
                    );
                    item_event.redacted = redacted_count;
                    let id = item_event.id.clone();
                    events.push(item_event);
                    (id, (bump_timestamp(&created_at), created_at))
                }
                FrictionAddMode::Append { item_id } => {
                    get_item(connection, *item_id, &database_path)?;
                    (
                        item_event_id(connection, *item_id, &database_path)?,
                        (next_event_ts(&store_dir)?, flog::now_timestamp()),
                    )
                }
            };
            let occurrence_event = Event::at(
                occurrence_ts.0,
                context.repo_root.clone(),
                EventBody::OccurrenceAppended(Box::new(flog::OccurrenceAppended {
                    item: item_event_id.clone(),
                    at: occurrence_ts.1,
                    cwd: request.cwd.to_string_lossy().into_owned(),
                    repo_root: context.repo_root.clone(),
                    head_sha: context.head_sha.clone(),
                    evidence: request.evidence.clone(),
                    cost: None,
                    provenance: None,
                })),
            );
            events.push(occurrence_event);
            for event in &events {
                flog::append(&store_dir, log_handle, event)?;
            }
            apply_events(connection, &store_dir, &database_path, &events, None)?;
            match &request.mode {
                FrictionAddMode::Create { .. } => {
                    find_item_id_by_event(connection, &item_event_id, &database_path)
                }
                FrictionAddMode::Append { item_id } => Ok(*item_id),
            }
        })?;
        get_item(&self.connection, item_id, &self.database_path)
    }

    /// Import one fully validated Markdown record, skipping an existing slug atomically.
    pub fn import_friction(
        &mut self,
        entry: &FrictionImportEntry,
    ) -> Result<Option<FrictionItem>, LearnError> {
        let store_dir = self.store_dir.clone();
        let database_path = self.database_path.clone();
        self.mutate(|connection, log_handle| {
            let duplicate: bool = connection
                .query_row(
                    "SELECT EXISTS(SELECT 1 FROM items WHERE slug = ?1)",
                    [&entry.slug],
                    |row| row.get(0),
                )
                .map_err(|source| db_error(&database_path, source))?;
            if duplicate {
                return Ok(None);
            }

            let mut imported_keys = HashSet::new();
            for occurrence in &entry.occurrences {
                let Some(provenance) = &occurrence.provenance else {
                    continue;
                };
                validate_provenance(provenance)?;
                if !imported_keys.insert(&provenance.incident_key) {
                    return Err(incident_conflict(&provenance.incident_key));
                }
                let already_stored: bool = connection
                    .query_row(
                        "SELECT EXISTS(SELECT 1 FROM incident_provenance WHERE incident_key = ?1)",
                        [&provenance.incident_key],
                        |row| row.get(0),
                    )
                    .map_err(|source| db_error(&database_path, source))?;
                if already_stored {
                    return Err(incident_conflict(&provenance.incident_key));
                }
            }

            let created_at = entry.created_at.clone().unwrap_or_else(flog::now_timestamp);
            let item_event = Event::at(
                created_at,
                entry.repo_root.clone(),
                EventBody::ItemAdded(flog::ItemAdded {
                    title: entry.title.clone(),
                    source: entry.source.clone(),
                    repo_root: entry.repo_root.clone(),
                    target: entry.target.clone(),
                }),
            );
            let mut preserved = LogIdMap::default();
            preserved
                .item_slugs
                .insert(item_event.id.clone(), entry.slug.clone());
            let preserved_item_id = match entry.id {
                Some(id) if !row_id_exists(connection, "items", id, &database_path)? => Some(id),
                _ => None,
            };
            if let Some(id) = preserved_item_id {
                preserved.items.insert(item_event.id.clone(), id);
            }

            let mut events = vec![item_event];
            let mut ts = bump_timestamp(&events[0].ts);
            for occurrence in &entry.occurrences {
                let event = Event::at(
                    ts.clone(),
                    None,
                    EventBody::OccurrenceAppended(Box::new(flog::OccurrenceAppended {
                        item: events[0].id.clone(),
                        at: occurrence.at.clone(),
                        cwd: occurrence.cwd.clone(),
                        repo_root: occurrence.repo_root.clone(),
                        head_sha: occurrence.head_sha.clone(),
                        evidence: occurrence.evidence.clone(),
                        cost: occurrence.cost.clone(),
                        provenance: occurrence.provenance.clone(),
                    })),
                );
                if occurrence.id > 0
                    && !row_id_exists(connection, "occurrences", occurrence.id, &database_path)?
                {
                    preserved
                        .occurrences
                        .insert(event.id.clone(), occurrence.id);
                }
                events.push(event);
                ts = bump_timestamp(&ts);
            }
            for change in &entry.status_changes {
                let event = Event::at(
                    ts.clone(),
                    None,
                    EventBody::StatusChanged(flog::StatusChanged {
                        item: events[0].id.clone(),
                        at: change.at.clone(),
                        from: change.from_status.clone(),
                        to: change.to_status.clone(),
                        reason: change.reason.clone(),
                    }),
                );
                if change.id > 0
                    && !row_id_exists(connection, "status_changes", change.id, &database_path)?
                {
                    preserved.status_changes.insert(event.id.clone(), change.id);
                }
                events.push(event);
                ts = bump_timestamp(&ts);
            }
            let folded_status = entry
                .status_changes
                .last()
                .map(|change| change.to_status.as_str())
                .unwrap_or("open");
            if folded_status != entry.status.as_str() {
                let event = Event::at(
                    ts,
                    None,
                    EventBody::StatusChanged(flog::StatusChanged {
                        item: events[0].id.clone(),
                        at: entry.created_at.clone().unwrap_or_else(flog::now_timestamp),
                        from: folded_status.to_owned(),
                        to: entry.status.as_str().to_owned(),
                        reason: "imported status".to_owned(),
                    }),
                );
                events.push(event);
            }
            for event in &events {
                flog::append(&store_dir, log_handle, event)?;
            }
            apply_events(
                connection,
                &store_dir,
                &database_path,
                &events,
                Some(&preserved),
            )?;
            let item_id = find_item_id_by_event(connection, &events[0].id, &database_path)?;
            Ok(Some(get_item(connection, item_id, &database_path)?))
        })
    }

    /// Read the validated schema version without exposing the connection.
    pub fn schema_version(&self) -> Result<i64, LearnError> {
        read_schema_version(&self.connection, &self.database_path)
    }
}

#[derive(Debug, Default)]
struct RepositoryContext {
    repo_root: Option<String>,
    head_sha: Option<String>,
}

fn repository_context(cwd: &Path) -> Result<RepositoryContext, LearnError> {
    let root_output = git_command()
        .arg("-C")
        .arg(cwd)
        .args(["rev-parse", "--show-toplevel"])
        .output()
        .map_err(|error| LearnError::StoreGitCheck {
            path: cwd.to_path_buf(),
            message: error.to_string(),
        })?;
    if !root_output.status.success() {
        let message = String::from_utf8_lossy(&root_output.stderr).into_owned();
        if message.contains("not a git repository") {
            return Ok(RepositoryContext::default());
        }
        return Err(LearnError::StoreGitCheck {
            path: cwd.to_path_buf(),
            message,
        });
    }
    let repo_root = String::from_utf8_lossy(&root_output.stdout)
        .trim()
        .to_owned();
    let head_output = git_command()
        .arg("-C")
        .arg(cwd)
        .args(["rev-parse", "--verify", "HEAD"])
        .output()
        .map_err(|error| LearnError::StoreGitCheck {
            path: cwd.to_path_buf(),
            message: error.to_string(),
        })?;
    let head_sha = head_output.status.success().then(|| {
        String::from_utf8_lossy(&head_output.stdout)
            .trim()
            .to_owned()
    });
    Ok(RepositoryContext {
        repo_root: Some(repo_root),
        head_sha,
    })
}

fn require_nonblank(value: &str, field: &str) -> Result<(), LearnError> {
    if value.trim().is_empty() {
        Err(invalid_store_input(format!("{field} must not be blank")))
    } else {
        Ok(())
    }
}

fn invalid_store_input(message: impl Into<String>) -> LearnError {
    LearnError::StoreInvalid {
        message: message.into(),
    }
}

fn incident_conflict(key: &str) -> LearnError {
    LearnError::Diagnose {
        code: "diagnose_incident_conflict",
        message: format!(
            "historical incident `{key}` already exists with different or imported evidence"
        ),
    }
}

fn provenance_for(
    occurrence: &HistoricalOccurrenceRequest,
) -> Result<FrictionIncidentProvenance, LearnError> {
    let witness = &occurrence.witness;
    validate_witness(witness)?;
    for (value, field) in [
        (occurrence.at.as_str(), "historical time"),
        (occurrence.cwd.as_str(), "historical cwd"),
        (occurrence.evidence.as_str(), "evidence"),
    ] {
        require_nonblank(value, field)?;
    }
    let Some(facts) = occurrence.canonical_facts.as_object() else {
        return Err(invalid_store_input(
            "canonical historical facts must be a JSON object",
        ));
    };
    if !facts.contains_key("event")
        || facts
            .keys()
            .any(|key| !matches!(key.as_str(), "event" | "context"))
        || !facts["event"].is_object()
        || facts
            .get("context")
            .is_some_and(|context| !context.is_object())
    {
        return Err(invalid_store_input(
            "canonical historical facts must contain only parsed event and historical context objects",
        ));
    }
    let payload = serde_json::json!({
        "version": HISTORICAL_IDENTITY_VERSION,
        "at": occurrence.at,
        "cwd": occurrence.cwd,
        "repo_root": occurrence.repo_root,
        "head_sha": occurrence.head_sha,
        "facts": occurrence.canonical_facts,
    });
    let payload_bytes = serde_json::to_vec(&payload)
        .map_err(|error| invalid_store_input(format!("cannot encode canonical facts: {error}")))?;
    if payload_bytes.len() > MAX_HISTORICAL_FACTS_BYTES {
        return Err(invalid_store_input(
            "canonical historical facts exceed the supported size",
        ));
    }
    let payload_digest = sha256_digest(&payload_bytes);
    let incident_key = incident_key(witness);
    Ok(FrictionIncidentProvenance {
        incident_key,
        identity_version: HISTORICAL_IDENTITY_VERSION,
        harness: witness.harness.clone(),
        thread_id: witness.thread_id.clone(),
        incident_kind: witness.incident_kind.clone(),
        witness_id: witness.witness_id.clone(),
        source_id: witness.source_id.clone(),
        record_index: witness.record_index,
        byte_start: witness.byte_start,
        byte_end: witness.byte_end,
        record_digest: witness.record_digest.clone(),
        payload_digest,
    })
}

fn validate_witness(witness: &HistoricalWitness) -> Result<(), LearnError> {
    for (value, field) in [
        (witness.harness.as_str(), "harness"),
        (witness.thread_id.as_str(), "thread ID"),
        (witness.incident_kind.as_str(), "incident kind"),
        (witness.source_id.as_str(), "source ID"),
    ] {
        require_nonblank(value, field)?;
        if value.len() > 4_096 || value.chars().any(char::is_control) {
            return Err(invalid_store_input(format!(
                "{field} exceeds its supported format"
            )));
        }
    }
    if !matches!(witness.harness.as_str(), "codex" | "claude" | "opencode") {
        return Err(invalid_store_input("unsupported historical harness"));
    }
    if !matches!(
        witness.incident_kind.as_str(),
        "failed-tool" | "repeated-work" | "workflow-deviation"
    ) {
        return Err(invalid_store_input("unsupported historical incident kind"));
    }
    if let Some(witness_id) = &witness.witness_id {
        require_nonblank(witness_id, "witness ID")?;
        if witness_id.len() > 4_096 || witness_id.chars().any(char::is_control) {
            return Err(invalid_store_input(
                "witness ID exceeds its supported format",
            ));
        }
    }
    if witness.byte_end < witness.byte_start
        || witness.record_index > i64::MAX as u64
        || witness.byte_start > i64::MAX as u64
        || witness.byte_end > i64::MAX as u64
        || !is_sha256_digest(&witness.record_digest)
    {
        return Err(invalid_store_input("historical source anchor is invalid"));
    }
    Ok(())
}

pub(crate) fn validate_provenance(
    provenance: &FrictionIncidentProvenance,
) -> Result<(), LearnError> {
    if provenance.identity_version != HISTORICAL_IDENTITY_VERSION {
        return Err(invalid_store_input(format!(
            "unsupported incident identity version `{}`",
            provenance.identity_version
        )));
    }
    let witness = HistoricalWitness {
        harness: provenance.harness.clone(),
        thread_id: provenance.thread_id.clone(),
        incident_kind: provenance.incident_kind.clone(),
        witness_id: provenance.witness_id.clone(),
        source_id: provenance.source_id.clone(),
        record_index: provenance.record_index,
        byte_start: provenance.byte_start,
        byte_end: provenance.byte_end,
        record_digest: provenance.record_digest.clone(),
    };
    validate_witness(&witness)?;
    if (provenance.incident_key != incident_key(&witness)
        && (witness.witness_id.is_some()
            || provenance.incident_key != legacy_incident_key(&witness)))
        || !is_sha256_digest(&provenance.payload_digest)
    {
        return Err(invalid_store_input(
            "incident provenance key or payload digest is invalid",
        ));
    }
    Ok(())
}

fn incident_key(witness: &HistoricalWitness) -> String {
    let event_identity = if let Some(witness_id) = &witness.witness_id {
        serde_json::json!({"native_id": witness_id})
    } else {
        serde_json::json!({
            "record_index": witness.record_index,
            "record_digest": witness.record_digest,
        })
    };
    let material = serde_json::json!({
        "identity_version": HISTORICAL_IDENTITY_VERSION,
        "harness": witness.harness,
        "thread_id": witness.thread_id,
        "incident_kind": witness.incident_kind,
        "event": event_identity,
    });
    let encoded = serde_json::to_vec(&material).expect("incident identity is JSON serializable");
    format!("incident-v1:{}", sha256_hex(&encoded))
}

fn legacy_incident_key(witness: &HistoricalWitness) -> String {
    let material = serde_json::json!({
        "identity_version": HISTORICAL_IDENTITY_VERSION,
        "harness": witness.harness,
        "thread_id": witness.thread_id,
        "incident_kind": witness.incident_kind,
        "event": {
            "record_index": witness.record_index,
            "byte_start": witness.byte_start,
            "byte_end": witness.byte_end,
            "record_digest": witness.record_digest,
        },
    });
    let encoded = serde_json::to_vec(&material).expect("incident identity is JSON serializable");
    format!("incident-v1:{}", sha256_hex(&encoded))
}

fn is_sha256_digest(value: &str) -> bool {
    value
        .strip_prefix("sha256:")
        .is_some_and(|hex| hex.len() == 64 && hex.bytes().all(|byte| byte.is_ascii_hexdigit()))
}

fn sha256_digest(bytes: &[u8]) -> String {
    format!("sha256:{}", sha256_hex(bytes))
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut output = String::with_capacity(64);
    for byte in Sha256::digest(bytes) {
        use std::fmt::Write as _;
        let _ = write!(output, "{byte:02x}");
    }
    output
}

fn insert_provenance(
    connection: &Connection,
    occurrence_id: i64,
    provenance: &FrictionIncidentProvenance,
    database_path: &Path,
) -> Result<(), LearnError> {
    validate_provenance(provenance)?;
    connection
        .execute(
            "INSERT INTO incident_provenance(
                incident_key, occurrence_id, identity_version, harness, thread_id,
                incident_kind, witness_id, source_id, record_index, byte_start,
                byte_end, record_digest, payload_digest
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13)",
            params![
                provenance.incident_key,
                occurrence_id,
                i64::from(provenance.identity_version),
                provenance.harness,
                provenance.thread_id,
                provenance.incident_kind,
                provenance.witness_id,
                provenance.source_id,
                i64::try_from(provenance.record_index)
                    .map_err(|_| invalid_store_input("record index exceeds its storage range"))?,
                i64::try_from(provenance.byte_start)
                    .map_err(|_| invalid_store_input("record offset exceeds its storage range"))?,
                i64::try_from(provenance.byte_end)
                    .map_err(|_| invalid_store_input("record offset exceeds its storage range"))?,
                provenance.record_digest,
                provenance.payload_digest,
            ],
        )
        .map_err(|source| db_error(database_path, source))?;
    Ok(())
}

fn get_item(
    connection: &Connection,
    item_id: i64,
    database_path: &Path,
) -> Result<FrictionItem, LearnError> {
    connection
        .query_row(
            "SELECT id, slug, title, source, repo_root, status, target, created_at
             FROM items WHERE id = ?1",
            [item_id],
            |row| {
                Ok(FrictionItem {
                    id: row.get(0)?,
                    slug: row.get(1)?,
                    title: row.get(2)?,
                    source: row.get(3)?,
                    repo_root: row.get(4)?,
                    status: row.get(5)?,
                    target: row.get(6)?,
                    created_at: row.get(7)?,
                })
            },
        )
        .map_err(|error| match error {
            rusqlite::Error::QueryReturnedNoRows => LearnError::StoreItemNotFound {
                identifier: item_id.to_string(),
            },
            source => db_error(database_path, source),
        })
}

fn get_item_by_identifier(
    connection: &Connection,
    identifier: &str,
    database_path: &Path,
) -> Result<FrictionItem, LearnError> {
    if let Ok(item_id) = identifier.parse::<i64>()
        && item_id > 0
    {
        return get_item(connection, item_id, database_path);
    }
    connection
        .query_row(
            "SELECT id, slug, title, source, repo_root, status, target, created_at
             FROM items WHERE slug = ?1",
            [identifier],
            read_item,
        )
        .map_err(|error| match error {
            rusqlite::Error::QueryReturnedNoRows => LearnError::StoreItemNotFound {
                identifier: identifier.to_owned(),
            },
            source => db_error(database_path, source),
        })
}

fn read_item(row: &rusqlite::Row<'_>) -> rusqlite::Result<FrictionItem> {
    Ok(FrictionItem {
        id: row.get(0)?,
        slug: row.get(1)?,
        title: row.get(2)?,
        source: row.get(3)?,
        repo_root: row.get(4)?,
        status: row.get(5)?,
        target: row.get(6)?,
        created_at: row.get(7)?,
    })
}

fn read_recurrence(row: &rusqlite::Row<'_>) -> rusqlite::Result<FrictionRecurrence> {
    Ok(FrictionRecurrence {
        adoption_id: row.get(0)?,
        adoption_at: row.get(1)?,
        summary: row.get(2)?,
        item: FrictionItem {
            id: row.get(3)?,
            slug: row.get(4)?,
            title: row.get(5)?,
            source: row.get(6)?,
            repo_root: row.get(7)?,
            status: row.get(8)?,
            target: row.get(9)?,
            created_at: row.get(10)?,
        },
        occurrence: FrictionOccurrence {
            id: row.get(11)?,
            item_id: row.get(12)?,
            at: row.get(13)?,
            cwd: row.get(14)?,
            repo_root: row.get(15)?,
            head_sha: row.get(16)?,
            evidence: row.get(17)?,
            cost: row.get(18)?,
            provenance: None,
        },
    })
}

fn read_occurrence(row: &rusqlite::Row<'_>) -> rusqlite::Result<FrictionOccurrence> {
    Ok(FrictionOccurrence {
        id: row.get(0)?,
        item_id: row.get(1)?,
        at: row.get(2)?,
        cwd: row.get(3)?,
        repo_root: row.get(4)?,
        head_sha: row.get(5)?,
        evidence: row.get(6)?,
        cost: row.get(7)?,
        provenance: read_provenance(row, 8)?,
    })
}

fn read_provenance(
    row: &rusqlite::Row<'_>,
    offset: usize,
) -> rusqlite::Result<Option<FrictionIncidentProvenance>> {
    let Some(incident_key) = row.get::<_, Option<String>>(offset)? else {
        return Ok(None);
    };
    let identity_version: i64 = row.get(offset + 1)?;
    let record_index: i64 = row.get(offset + 7)?;
    let byte_start: i64 = row.get(offset + 8)?;
    let byte_end: i64 = row.get(offset + 9)?;
    Ok(Some(FrictionIncidentProvenance {
        incident_key,
        identity_version: u32::try_from(identity_version)
            .map_err(|_| rusqlite::Error::IntegralValueOutOfRange(offset + 1, identity_version))?,
        harness: row.get(offset + 2)?,
        thread_id: row.get(offset + 3)?,
        incident_kind: row.get(offset + 4)?,
        witness_id: row.get(offset + 5)?,
        source_id: row.get(offset + 6)?,
        record_index: nonnegative_u64(offset + 7, record_index)?,
        byte_start: nonnegative_u64(offset + 8, byte_start)?,
        byte_end: nonnegative_u64(offset + 9, byte_end)?,
        record_digest: row.get(offset + 10)?,
        payload_digest: row.get(offset + 11)?,
    }))
}

fn nonnegative_u64(column: usize, value: i64) -> rusqlite::Result<u64> {
    u64::try_from(value).map_err(|_| rusqlite::Error::IntegralValueOutOfRange(column, value))
}

fn occurrence_from_id(
    connection: &Connection,
    occurrence_id: i64,
    database_path: &Path,
) -> Result<FrictionOccurrence, LearnError> {
    connection
        .query_row(
            &format!(
                "SELECT {OCCURRENCE_COLUMNS}
                 FROM occurrences o LEFT JOIN incident_provenance p ON p.occurrence_id = o.id
                 WHERE o.id = ?1"
            ),
            [occurrence_id],
            read_occurrence,
        )
        .map_err(|source| db_error(database_path, source))
}

fn read_occurrence_page(
    connection: &Connection,
    item_id: i64,
    page: PageRequest,
    database_path: &Path,
) -> Result<StorePage<FrictionOccurrence>, LearnError> {
    let (limit, offset) = validate_page(page)?;
    let total: i64 = connection
        .query_row(
            "SELECT COUNT(*) FROM occurrences WHERE item_id = ?1",
            [item_id],
            |row| row.get(0),
        )
        .map_err(|source| db_error(database_path, source))?;
    let mut statement = connection
        .prepare(&format!(
            "SELECT {OCCURRENCE_COLUMNS}
             FROM occurrences o LEFT JOIN incident_provenance p ON p.occurrence_id = o.id
             WHERE o.item_id = ?1 ORDER BY o.id LIMIT ?2 OFFSET ?3"
        ))
        .map_err(|source| db_error(database_path, source))?;
    let rows = statement
        .query_map(params![item_id, limit, offset], read_occurrence)
        .map_err(|source| db_error(database_path, source))?;
    let items = rows
        .collect::<Result<Vec<_>, _>>()
        .map_err(|source| db_error(database_path, source))?;
    Ok(StorePage::new(items, total as usize, page))
}

fn read_all_occurrences_with_provenance(
    connection: &Connection,
    item_id: i64,
    database_path: &Path,
) -> Result<Vec<FrictionOccurrence>, LearnError> {
    let mut statement = connection
        .prepare(&format!(
            "SELECT {OCCURRENCE_COLUMNS}
             FROM occurrences o LEFT JOIN incident_provenance p ON p.occurrence_id = o.id
             WHERE o.item_id = ?1 ORDER BY o.id"
        ))
        .map_err(|source| db_error(database_path, source))?;
    let rows = statement
        .query_map([item_id], read_occurrence)
        .map_err(|source| db_error(database_path, source))?;
    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|source| db_error(database_path, source))
}

fn read_occurrences(
    connection: &Connection,
    item_id: i64,
    page: PageRequest,
    database_path: &Path,
) -> Result<StorePage<FrictionOccurrence>, LearnError> {
    read_occurrence_page(connection, item_id, page, database_path)
}

fn read_status_changes(
    connection: &Connection,
    item_id: i64,
    page: PageRequest,
    database_path: &Path,
) -> Result<StorePage<FrictionStatusChange>, LearnError> {
    read_collection_page(
        connection,
        "status_changes",
        item_id,
        page,
        database_path,
        |row| {
            Ok(FrictionStatusChange {
                id: row.get(0)?,
                item_id: row.get(1)?,
                at: row.get(2)?,
                from_status: row.get(3)?,
                to_status: row.get(4)?,
                reason: row.get(5)?,
            })
        },
    )
}

fn read_all_occurrences(
    connection: &Connection,
    item_id: i64,
    database_path: &Path,
) -> Result<Vec<FrictionOccurrence>, LearnError> {
    read_all_occurrences_with_provenance(connection, item_id, database_path)
}

fn read_all_status_changes(
    connection: &Connection,
    item_id: i64,
    database_path: &Path,
) -> Result<Vec<FrictionStatusChange>, LearnError> {
    read_all_collection(
        connection,
        "status_changes",
        item_id,
        database_path,
        |row| {
            Ok(FrictionStatusChange {
                id: row.get(0)?,
                item_id: row.get(1)?,
                at: row.get(2)?,
                from_status: row.get(3)?,
                to_status: row.get(4)?,
                reason: row.get(5)?,
            })
        },
    )
}

fn read_all_collection<T>(
    connection: &Connection,
    table: &str,
    item_id: i64,
    database_path: &Path,
    mut read_row: impl FnMut(&rusqlite::Row<'_>) -> rusqlite::Result<T>,
) -> Result<Vec<T>, LearnError> {
    let mut statement = connection
        .prepare(&format!(
            "SELECT * FROM {table} WHERE item_id = ?1 ORDER BY id"
        ))
        .map_err(|source| db_error(database_path, source))?;
    let rows = statement
        .query_map([item_id], |row| read_row(row))
        .map_err(|source| db_error(database_path, source))?;
    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|source| db_error(database_path, source))
}

fn read_collection_page<T>(
    connection: &Connection,
    table: &str,
    item_id: i64,
    page: PageRequest,
    database_path: &Path,
    mut read_row: impl FnMut(&rusqlite::Row<'_>) -> rusqlite::Result<T>,
) -> Result<StorePage<T>, LearnError> {
    let count: i64 = connection
        .query_row(
            &format!("SELECT COUNT(*) FROM {table} WHERE item_id = ?1"),
            [item_id],
            |row| row.get(0),
        )
        .map_err(|source| db_error(database_path, source))?;
    let (limit, offset) = validate_page(page)?;
    let mut statement = connection
        .prepare(&format!(
            "SELECT * FROM {table} WHERE item_id = ?1 ORDER BY id LIMIT ?2 OFFSET ?3"
        ))
        .map_err(|source| db_error(database_path, source))?;
    let rows = statement
        .query_map(params![item_id, limit, offset], |row| read_row(row))
        .map_err(|source| db_error(database_path, source))?;
    let items = rows
        .collect::<Result<Vec<_>, _>>()
        .map_err(|source| db_error(database_path, source))?;
    Ok(StorePage::new(items, count as usize, page))
}

fn validate_page(page: PageRequest) -> Result<(i64, i64), LearnError> {
    if page.limit == 0 || page.limit > MAX_PAGE_LIMIT {
        return Err(invalid_store_input(format!(
            "page limit must be between 1 and {MAX_PAGE_LIMIT}"
        )));
    }
    let offset = i64::try_from(page.offset)
        .map_err(|_| invalid_store_input("page offset exceeds the supported range"))?;
    Ok((page.limit as i64, offset))
}

fn push_value(values: &mut Vec<Value>, value: Value) -> String {
    values.push(value);
    format!("?{}", values.len())
}

fn read_text_filtered_page(
    connection: &Connection,
    where_clause: &str,
    values: &[Value],
    text: &str,
    page: PageRequest,
    database_path: &Path,
) -> Result<StorePage<FrictionItem>, LearnError> {
    let needle = text.to_lowercase();
    let mut item_statement = connection
        .prepare(&format!(
            "SELECT id, slug, title, source, repo_root, status, target, created_at
             FROM items WHERE {where_clause} ORDER BY id"
        ))
        .map_err(|source| db_error(database_path, source))?;
    let mut occurrence_statement = connection
        .prepare("SELECT evidence FROM occurrences WHERE item_id = ?1 ORDER BY id")
        .map_err(|source| db_error(database_path, source))?;
    let mut rows = item_statement
        .query(params_from_iter(values.iter()))
        .map_err(|source| db_error(database_path, source))?;
    let mut items = Vec::with_capacity(page.limit.min(128));
    let mut total = 0;
    while let Some(row) = rows
        .next()
        .map_err(|source| db_error(database_path, source))?
    {
        let item = read_item(row).map_err(|source| db_error(database_path, source))?;
        let mut matches = item.title.to_lowercase().contains(&needle);
        if !matches {
            let mut evidence_rows = occurrence_statement
                .query([item.id])
                .map_err(|source| db_error(database_path, source))?;
            while let Some(evidence_row) = evidence_rows
                .next()
                .map_err(|source| db_error(database_path, source))?
            {
                let evidence: String = evidence_row
                    .get(0)
                    .map_err(|source| db_error(database_path, source))?;
                if evidence.to_lowercase().contains(&needle) {
                    matches = true;
                    break;
                }
            }
        }
        if matches {
            // String matching keeps `%`, `_`, and backslash literal and handles Unicode casing.
            if total >= page.offset && items.len() < page.limit {
                items.push(item);
            }
            total += 1;
        }
    }
    Ok(StorePage::new(items, total, page))
}

fn normalize_scope_path(path: &Path, cwd: &Path) -> PathBuf {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        cwd.join(path)
    };
    if let Ok(canonical) = absolute.canonicalize() {
        return canonical;
    }
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::Prefix(_) | Component::RootDir => {
                normalized.push(component.as_os_str());
            }
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            Component::Normal(part) => normalized.push(part),
        }
    }
    normalized
}

/// Resolve the selected store directory, applying environment and TOML precedence.
/// When `default.learn` is absent, the fallback is `learn/` under the resolved
/// varde config directory (`VARDE_CONFIG_DIR`, XDG, or `~/.config/varde`).
pub fn resolve_store_dir() -> Result<PathBuf, LearnError> {
    if let Some(value) = std::env::var_os("VARDE_LEARN_STORE").filter(|value| !value.is_empty()) {
        return expand_and_resolve(Path::new(&value));
    }

    let config_dir = varde_config_dir()?;
    let config_path = config_dir.join("config.toml");
    let configured = match fs::read_to_string(&config_path) {
        Ok(contents) => {
            let value: toml::Value =
                toml::from_str(&contents).map_err(|error| LearnError::StoreConfig {
                    path: config_path.clone(),
                    message: error.to_string(),
                })?;
            match value
                .get("default")
                .and_then(|section| section.get("learn"))
            {
                None => None,
                Some(value) => Some(
                    value
                        .as_str()
                        .filter(|value| !value.trim().is_empty())
                        .ok_or_else(|| LearnError::StoreConfig {
                            path: config_path.clone(),
                            message: "`default.learn` must be a non-empty path string".to_owned(),
                        })?
                        .to_owned(),
                ),
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(source) => {
            return Err(LearnError::StoreIo {
                operation: "read global config",
                path: config_path,
                source,
            });
        }
    };

    match configured {
        Some(path) => expand_and_resolve(Path::new(&path)),
        None => expand_and_resolve(&config_dir.join("learn")),
    }
}

fn varde_config_dir() -> Result<PathBuf, LearnError> {
    if let Some(path) = std::env::var_os("VARDE_CONFIG_DIR").filter(|value| !value.is_empty()) {
        return Ok(PathBuf::from(path));
    }
    if let Some(path) = std::env::var_os("XDG_CONFIG_HOME").filter(|value| !value.is_empty()) {
        return Ok(PathBuf::from(path).join("varde"));
    }
    match std::env::var_os("HOME").filter(|value| !value.is_empty()) {
        Some(home) => Ok(PathBuf::from(home).join(".config/varde")),
        None => Ok(PathBuf::from(".config/varde")),
    }
}

fn expand_and_resolve(path: &Path) -> Result<PathBuf, LearnError> {
    let expanded = expand_leading_tilde(path)?;
    let absolute = if expanded.is_absolute() {
        expanded
    } else {
        std::env::current_dir()
            .map_err(|source| LearnError::StoreIo {
                operation: "resolve relative store path from current directory",
                path: expanded.clone(),
                source,
            })?
            .join(expanded)
    };
    resolve_directory(&absolute, 0)
}

fn expand_leading_tilde(path: &Path) -> Result<PathBuf, LearnError> {
    let mut components = path.components();
    if components.next() != Some(Component::Normal(OsStr::new("~"))) {
        return Ok(path.to_path_buf());
    }
    let home = std::env::var_os("HOME")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .ok_or_else(|| LearnError::StoreConfig {
            path: path.to_path_buf(),
            message: "cannot expand `~` because HOME is unset".to_owned(),
        })?;
    Ok(home.join(components.as_path()))
}

fn resolve_directory(path: &Path, depth: usize) -> Result<PathBuf, LearnError> {
    if depth > 40 {
        return Err(LearnError::StoreIo {
            operation: "resolve symlinked store path",
            path: path.to_path_buf(),
            source: std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "too many symlink levels",
            ),
        });
    }
    let path = normalize_absolute(path)?;
    let mut probe = path.clone();
    let mut missing = Vec::new();
    loop {
        if let Some(resolved) = inspect_path_prefix(&probe, &mut missing, depth)? {
            return Ok(resolved);
        }
        if !probe.pop() {
            return Err(LearnError::StoreIo {
                operation: "resolve store path",
                path,
                source: std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    "no existing parent directory",
                ),
            });
        }
    }
}

fn inspect_path_prefix(
    probe: &Path,
    missing: &mut Vec<std::ffi::OsString>,
    depth: usize,
) -> Result<Option<PathBuf>, LearnError> {
    match fs::symlink_metadata(probe) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            let target = fs::read_link(probe).map_err(|source| LearnError::StoreIo {
                operation: "read store path symlink",
                path: probe.to_path_buf(),
                source,
            })?;
            let target = if target.is_absolute() {
                target
            } else {
                probe.parent().unwrap_or(Path::new("/")).join(target)
            };
            let mut destination = target;
            for component in missing.iter().rev() {
                destination.push(component);
            }
            resolve_directory(&destination, depth + 1).map(Some)
        }
        Ok(metadata) if metadata.is_dir() => {
            let mut resolved = probe.canonicalize().map_err(|source| LearnError::StoreIo {
                operation: "canonicalize store path",
                path: probe.to_path_buf(),
                source,
            })?;
            for component in missing.iter().rev() {
                resolved.push(component);
            }
            Ok(Some(resolved))
        }
        Ok(_) => remember_missing_component(probe, missing),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            remember_missing_component(probe, missing)
        }
        Err(source) => Err(LearnError::StoreIo {
            operation: "inspect store path",
            path: probe.to_path_buf(),
            source,
        }),
    }
}

fn remember_missing_component(
    probe: &Path,
    missing: &mut Vec<std::ffi::OsString>,
) -> Result<Option<PathBuf>, LearnError> {
    let name = probe.file_name().ok_or_else(|| LearnError::StoreIo {
        operation: "resolve store path",
        path: probe.to_path_buf(),
        source: std::io::Error::new(std::io::ErrorKind::NotFound, "no existing parent directory"),
    })?;
    missing.push(name.to_os_string());
    Ok(None)
}

fn normalize_absolute(path: &Path) -> Result<PathBuf, LearnError> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|source| LearnError::StoreIo {
                operation: "resolve store path from current directory",
                path: path.to_path_buf(),
                source,
            })?
            .join(path)
    };
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::Prefix(_) | Component::RootDir => normalized.push(component.as_os_str()),
            Component::CurDir => {}
            Component::ParentDir => {
                if normalized.exists()
                    && let Ok(canonical) = normalized.canonicalize()
                {
                    normalized = canonical;
                }
                normalized.pop();
            }
            Component::Normal(part) => normalized.push(part),
        }
    }
    Ok(normalized)
}

/// Refuse a store path inside a Git checkout unless the path itself is
/// git-ignored there (the store's `.gitignore` lists `learn.db*`).
///
/// Paths outside any repository, inside a bare repository, or inside the Git
/// directory itself are still refused.
fn reject_git_path(path: &Path) -> Result<(), LearnError> {
    reject_git_path_with(path, false)
}

/// [`reject_git_path`], optionally treating the path as ignored inside a work
/// tree because the store opener is about to write a covering `.gitignore`.
fn reject_git_path_with(path: &Path, will_be_ignored: bool) -> Result<(), LearnError> {
    let existing_dir = existing_directory(path)?;
    let output = git_command()
        .arg("-C")
        .arg(&existing_dir)
        .args([
            "rev-parse",
            "--is-inside-work-tree",
            "--is-inside-git-dir",
            "--is-bare-repository",
        ])
        .output()
        .map_err(|error| LearnError::StoreGitCheck {
            path: path.to_path_buf(),
            message: error.to_string(),
        })?;
    if !output.status.success() {
        let message = String::from_utf8_lossy(&output.stderr).into_owned();
        if message.contains("not a git repository") {
            return Ok(());
        }
        return Err(LearnError::StoreGitCheck {
            path: path.to_path_buf(),
            message,
        });
    }
    let flags_text = String::from_utf8_lossy(&output.stdout);
    let mut flags = flags_text.lines();
    let inside_work_tree = flags.next() == Some("true");
    let inside_git_dir = flags.next() == Some("true");
    let bare = flags.next() == Some("true");
    if !inside_work_tree && !inside_git_dir && !bare {
        return Ok(());
    }
    if bare || inside_git_dir {
        return Err(LearnError::StoreInsideGit {
            path: path.to_path_buf(),
            repo_root: existing_dir,
        });
    }
    if will_be_ignored {
        return Ok(());
    }
    let root_output = git_command()
        .arg("-C")
        .arg(&existing_dir)
        .args(["rev-parse", "--show-toplevel"])
        .output()
        .map_err(|error| LearnError::StoreGitCheck {
            path: path.to_path_buf(),
            message: error.to_string(),
        })?;
    let repo_root = if root_output.status.success() {
        PathBuf::from(String::from_utf8_lossy(&root_output.stdout).trim())
    } else {
        existing_dir
    };
    let relative = path.strip_prefix(&repo_root).unwrap_or(path);
    let mut check = git_command();
    check
        .arg("-C")
        .arg(&repo_root)
        .args(["check-ignore", "--quiet"])
        .arg(relative);
    let ignored = check.output().map_err(|error| LearnError::StoreGitCheck {
        path: path.to_path_buf(),
        message: error.to_string(),
    })?;
    match ignored.status.code() {
        Some(0) => Ok(()),
        Some(1) => Err(LearnError::StoreInsideGit {
            path: path.to_path_buf(),
            repo_root,
        }),
        _ => Err(LearnError::StoreGitCheck {
            path: path.to_path_buf(),
            message: String::from_utf8_lossy(&ignored.stderr).trim().to_owned(),
        }),
    }
}

/// The top level of the Git work tree containing `dir`, if any.
fn work_tree_root(dir: &Path) -> Option<PathBuf> {
    let output = git_command()
        .arg("-C")
        .arg(dir)
        .args(["rev-parse", "--show-toplevel"])
        .output()
        .ok()?;
    output
        .status
        .success()
        .then(|| PathBuf::from(String::from_utf8_lossy(&output.stdout).trim()))
}

fn git_command() -> Command {
    let mut command = Command::new("git");
    command
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_COMMON_DIR")
        .env_remove("GIT_CEILING_DIRECTORIES");
    command
}

/// Persisted event-id to integer-id mappings, kept in the `meta` table so a
/// rebuild preserves existing ids and only numbers previously unseen events.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
struct LogIdMap {
    items: HashMap<String, i64>,
    item_slugs: HashMap<String, String>,
    occurrences: HashMap<String, i64>,
    status_changes: HashMap<String, i64>,
    adoptions: HashMap<String, i64>,
}

/// Prepare a store whose database predates the log: migrate it into the log
/// under the init lock before any cache rebuild. A database below the current
/// schema beside a non-empty log was written by an older binary after the log
/// was cloned, so its rows are merged into the log instead of being rebuilt away.
fn prepare_store(store_dir: &Path, database_path: &Path) -> Result<(), LearnError> {
    recover_interrupted_migration(store_dir, database_path)?;
    if !database_path.is_file() {
        return Ok(());
    }
    let log_is_empty = flog::replay(store_dir)?.events.is_empty();
    let probe = Connection::open(database_path).map_err(|source| LearnError::StoreDatabase {
        path: database_path.to_path_buf(),
        source,
    })?;
    let current = read_schema_version(&probe, database_path)?;
    if current > SCHEMA_VERSION {
        return Err(LearnError::StoreSchemaTooNew {
            found: current,
            supported: SCHEMA_VERSION,
        });
    }
    let has_rows = database_has_rows(&probe, database_path)?;
    drop(probe);
    if current >= 1 && has_rows && (log_is_empty || current < SCHEMA_VERSION) {
        migrate_database_to_log(store_dir, database_path)?;
    }
    Ok(())
}

/// Sidecar holding the id map of a migration in progress.
fn migration_map_path(database_path: &Path) -> PathBuf {
    PathBuf::from(format!("{}{}.map", database_path.display(), PRE_LOG_SUFFIX))
}

/// Finish a migration that stopped after installing the log: rebuild the cache
/// with the saved id map so the ids already shown to users survive, then drop
/// the leftovers. A sidecar whose items are not all in the log belongs to a
/// migration that stopped earlier; the database is intact and migrates afresh.
fn recover_interrupted_migration(store_dir: &Path, database_path: &Path) -> Result<(), LearnError> {
    let map_path = migration_map_path(database_path);
    let text = match fs::read_to_string(&map_path) {
        Ok(text) => text,
        Err(source) if source.kind() == ErrorKind::NotFound => return Ok(()),
        Err(source) => {
            return Err(LearnError::StoreIo {
                operation: "read migration id map",
                path: map_path,
                source,
            });
        }
    };
    let Ok(map) = serde_json::from_str::<LogIdMap>(&text) else {
        return Ok(());
    };
    let logged: HashSet<String> = flog::replay(store_dir)?
        .events
        .into_iter()
        .map(|event| event.id)
        .collect();
    if map.items.is_empty() || !map.items.keys().all(|id| logged.contains(id)) {
        return Ok(());
    }
    let mut connection =
        Connection::open(database_path).map_err(|source| LearnError::StoreDatabase {
            path: database_path.to_path_buf(),
            source,
        })?;
    varde_core::sqlite::configure_connection(&connection)
        .map_err(|source| db_error(database_path, source))?;
    migrate(&mut connection, database_path)?;
    rebuild_cache(&mut connection, store_dir, database_path, Some(&map))?;
    drop(connection);
    finish_migration(database_path)
}

/// Remove the pre-log database and the id map once the rebuilt cache is in place.
fn finish_migration(database_path: &Path) -> Result<(), LearnError> {
    let pre_log = PathBuf::from(format!("{}{}", database_path.display(), PRE_LOG_SUFFIX));
    for path in [pre_log, migration_map_path(database_path)] {
        match fs::remove_file(&path) {
            Ok(()) => {}
            Err(source) if source.kind() == ErrorKind::NotFound => {}
            Err(source) => {
                return Err(LearnError::StoreIo {
                    operation: "remove migration leftovers",
                    path,
                    source,
                });
            }
        }
    }
    Ok(())
}

fn table_exists(
    connection: &Connection,
    table: &str,
    database_path: &Path,
) -> Result<bool, LearnError> {
    connection
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?1)",
            [table],
            |row| row.get(0),
        )
        .map_err(|source| db_error(database_path, source))
}

fn database_has_rows(connection: &Connection, database_path: &Path) -> Result<bool, LearnError> {
    for table in ["items", "occurrences", "status_changes", "adoptions"] {
        let present: bool = connection
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?1)",
                [table],
                |row| row.get(0),
            )
            .map_err(|source| db_error(database_path, source))?;
        if present {
            let count: i64 = connection
                .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
                    row.get(0)
                })
                .map_err(|source| db_error(database_path, source))?;
            if count > 0 {
                return Ok(true);
            }
        }
    }
    Ok(false)
}

/// Everything read out of a pre-log database so the log can be written and the
/// cache rebuilt with identical ids.
struct DumpedStore {
    events: Vec<Event>,
    map: LogIdMap,
}

/// Read a pre-log database, emitting one event per item, occurrence (with
/// incident provenance), status change and adoption, keeping every column.
///
/// Event timestamps are the data's own timestamps; a dependent event whose
/// timestamp is not strictly after the item's previous event is moved just past
/// it, so the fold keeps row order and never orphans it. An item whose status is
/// not backed by its status history (a legacy import) gets one closing
/// `status_changed` event so the fold reproduces the stored status.
fn dump_database(connection: &Connection, database_path: &Path) -> Result<DumpedStore, LearnError> {
    let mut events = Vec::new();
    let mut map = LogIdMap::default();
    let mut item_event_by_id = HashMap::new();
    let mut last_ts_by_id = HashMap::new();
    let mut stored_status_by_id = HashMap::new();
    let mut folded_status_by_id: HashMap<i64, String> = HashMap::new();
    let mut item_order = Vec::new();

    let mut statement = connection
        .prepare(
            "SELECT id, slug, title, source, repo_root, status, target, created_at
             FROM items ORDER BY id",
        )
        .map_err(|source| db_error(database_path, source))?;
    let rows = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, Option<String>>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, Option<String>>(6)?,
                row.get::<_, String>(7)?,
            ))
        })
        .map_err(|source| db_error(database_path, source))?;
    for row in rows {
        let (id, slug, title, source, repo_root, status, target, created_at) =
            row.map_err(|source| db_error(database_path, source))?;
        let event = Event::at(
            created_at.clone(),
            repo_root.clone(),
            EventBody::ItemAdded(flog::ItemAdded {
                title,
                source,
                repo_root,
                target,
            }),
        );
        item_event_by_id.insert(id, event.id.clone());
        last_ts_by_id.insert(id, created_at);
        stored_status_by_id.insert(id, status);
        item_order.push(id);
        map.items.insert(event.id.clone(), id);
        map.item_slugs.insert(event.id.clone(), slug);
        events.push(event);
    }

    struct DumpOccurrence {
        id: i64,
        item_id: i64,
        at: String,
        cwd: String,
        repo_root: Option<String>,
        head_sha: Option<String>,
        evidence: String,
        cost: Option<String>,
    }
    let mut statement = connection
        .prepare(
            "SELECT id, item_id, at, cwd, repo_root, head_sha, evidence, cost
             FROM occurrences ORDER BY id",
        )
        .map_err(|source| db_error(database_path, source))?;
    let rows = statement
        .query_map([], |row| {
            Ok(DumpOccurrence {
                id: row.get(0)?,
                item_id: row.get(1)?,
                at: row.get(2)?,
                cwd: row.get(3)?,
                repo_root: row.get(4)?,
                head_sha: row.get(5)?,
                evidence: row.get(6)?,
                cost: row.get(7)?,
            })
        })
        .map_err(|source| db_error(database_path, source))?;
    let occurrences = rows
        .collect::<Result<Vec<_>, _>>()
        .map_err(|source| db_error(database_path, source))?;
    let has_provenance = table_exists(connection, "incident_provenance", database_path)?;
    for occurrence in occurrences {
        let item_event = item_event_by_id.get(&occurrence.item_id).ok_or_else(|| {
            invalid_store_input(format!(
                "occurrence {} references missing item {}",
                occurrence.id, occurrence.item_id
            ))
        })?;
        let provenance: Option<crate::FrictionIncidentProvenance> = if has_provenance {
            connection
                .query_row(
                    &format!(
                        "SELECT {}
                         FROM incident_provenance WHERE occurrence_id = ?1",
                        PROVENANCE_COLUMNS
                    ),
                    [occurrence.id],
                    |row| read_provenance(row, 0),
                )
                .optional()
                .map_err(|source| db_error(database_path, source))?
                .flatten()
        } else {
            None
        };
        let ts = next_dump_ts(&last_ts_by_id[&occurrence.item_id], &occurrence.at);
        last_ts_by_id.insert(occurrence.item_id, ts.clone());
        let event = Event::at(
            ts,
            None,
            EventBody::OccurrenceAppended(Box::new(flog::OccurrenceAppended {
                item: item_event.clone(),
                at: occurrence.at,
                cwd: occurrence.cwd,
                repo_root: occurrence.repo_root,
                head_sha: occurrence.head_sha,
                evidence: occurrence.evidence,
                cost: occurrence.cost,
                provenance,
            })),
        );
        map.occurrences.insert(event.id.clone(), occurrence.id);
        events.push(event);
    }

    struct DumpStatus {
        id: i64,
        item_id: i64,
        at: String,
        from_status: String,
        to_status: String,
        reason: String,
    }
    let mut statement = connection
        .prepare(
            "SELECT id, item_id, at, from_status, to_status, reason
             FROM status_changes ORDER BY id",
        )
        .map_err(|source| db_error(database_path, source))?;
    let rows = statement
        .query_map([], |row| {
            Ok(DumpStatus {
                id: row.get(0)?,
                item_id: row.get(1)?,
                at: row.get(2)?,
                from_status: row.get(3)?,
                to_status: row.get(4)?,
                reason: row.get(5)?,
            })
        })
        .map_err(|source| db_error(database_path, source))?;
    let statuses = rows
        .collect::<Result<Vec<_>, _>>()
        .map_err(|source| db_error(database_path, source))?;
    for change in statuses {
        let item_event = item_event_by_id.get(&change.item_id).ok_or_else(|| {
            invalid_store_input(format!(
                "status change {} references missing item {}",
                change.id, change.item_id
            ))
        })?;
        let ts = next_dump_ts(&last_ts_by_id[&change.item_id], &change.at);
        last_ts_by_id.insert(change.item_id, ts.clone());
        folded_status_by_id.insert(change.item_id, change.to_status.clone());
        let event = Event::at(
            ts,
            None,
            EventBody::StatusChanged(flog::StatusChanged {
                item: item_event.clone(),
                at: change.at,
                from: change.from_status,
                to: change.to_status,
                reason: change.reason,
            }),
        );
        map.status_changes.insert(event.id.clone(), change.id);
        events.push(event);
    }
    for item_id in item_order {
        let folded = folded_status_by_id
            .get(&item_id)
            .map_or("open", String::as_str);
        let stored = &stored_status_by_id[&item_id];
        if folded == stored {
            continue;
        }
        let ts = bump_timestamp(&last_ts_by_id[&item_id]);
        let event = Event::at(
            ts.clone(),
            None,
            EventBody::StatusChanged(flog::StatusChanged {
                item: item_event_by_id[&item_id].clone(),
                at: ts.clone(),
                from: folded.to_owned(),
                to: stored.clone(),
                reason: "migrated status".to_owned(),
            }),
        );
        last_ts_by_id.insert(item_id, ts);
        events.push(event);
    }

    struct DumpAdoption {
        id: i64,
        at: String,
        summary: String,
        target_files: String,
        commit_sha: Option<String>,
        eval_before: Option<String>,
        eval_after: Option<String>,
    }
    let has_adoptions = table_exists(connection, "adoptions", database_path)?;
    let has_adoption_items = table_exists(connection, "adoption_items", database_path)?;
    let adoptions = if has_adoptions {
        let mut statement = connection
            .prepare(
                "SELECT id, at, summary, target_files, commit_sha, eval_before, eval_after
                 FROM adoptions ORDER BY id",
            )
            .map_err(|source| db_error(database_path, source))?;
        let rows = statement
            .query_map([], |row| {
                Ok(DumpAdoption {
                    id: row.get(0)?,
                    at: row.get(1)?,
                    summary: row.get(2)?,
                    target_files: row.get(3)?,
                    commit_sha: row.get(4)?,
                    eval_before: row.get(5)?,
                    eval_after: row.get(6)?,
                })
            })
            .map_err(|source| db_error(database_path, source))?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|source| db_error(database_path, source))?
    } else {
        Vec::new()
    };
    for adoption in adoptions {
        let item_ids = if has_adoption_items {
            {
                let mut statement = connection
                    .prepare(
                        "SELECT item_id FROM adoption_items WHERE adoption_id = ?1 ORDER BY item_id",
                    )
                    .map_err(|source| db_error(database_path, source))?;
                let rows = statement
                    .query_map([adoption.id], |row| row.get::<_, i64>(0))
                    .map_err(|source| db_error(database_path, source))?;
                rows.collect::<Result<Vec<_>, _>>()
                    .map_err(|source| db_error(database_path, source))?
            }
        } else {
            Vec::new()
        };
        let item_events = item_ids
            .iter()
            .map(|item_id| {
                item_event_by_id.get(item_id).cloned().ok_or_else(|| {
                    invalid_store_input(format!(
                        "adoption {} references missing item {item_id}",
                        adoption.id
                    ))
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        let latest_item_ts = item_ids
            .iter()
            .filter_map(|item_id| last_ts_by_id.get(item_id))
            .max();
        let ts = match latest_item_ts {
            Some(latest) if adoption.at.as_str() <= latest.as_str() => bump_timestamp(latest),
            _ => adoption.at.clone(),
        };
        let files = serde_json::from_str(&adoption.target_files).map_err(|error| {
            invalid_store_input(format!(
                "stored adoption file paths are not valid JSON: {error}"
            ))
        })?;
        let event = Event::at(
            ts,
            None,
            EventBody::AdoptionRecorded(flog::AdoptionRecorded {
                at: adoption.at,
                summary: adoption.summary,
                files,
                commit_sha: adoption.commit_sha,
                eval_before: adoption.eval_before,
                eval_after: adoption.eval_after,
                items: item_events,
            }),
        );
        map.adoptions.insert(event.id.clone(), adoption.id);
        events.push(event);
    }

    Ok(DumpedStore { events, map })
}

/// `at` when it sorts after `previous`, otherwise a timestamp just past it.
fn next_dump_ts(previous: &str, at: &str) -> String {
    if at > previous {
        at.to_owned()
    } else {
        bump_timestamp(previous)
    }
}

/// Migrate a pre-log database into the log: write the existing log lines plus
/// one event per row to a temporary file renamed into place, keep the database
/// as `learn.db.pre-log` and the id map beside it until one successful rebuild,
/// then remove both. [`recover_interrupted_migration`] finishes a stopped run.
fn migrate_database_to_log(store_dir: &Path, database_path: &Path) -> Result<(), LearnError> {
    let probe = Connection::open(database_path).map_err(|source| LearnError::StoreDatabase {
        path: database_path.to_path_buf(),
        source,
    })?;
    let dumped = dump_database(&probe, database_path)?;
    drop(probe);

    let log_file = flog::log_path(store_dir);
    let existing = match fs::read_to_string(&log_file) {
        Ok(text) => text,
        Err(source) if source.kind() == ErrorKind::NotFound => String::new(),
        Err(source) => {
            return Err(LearnError::StoreIo {
                operation: "read friction log",
                path: log_file,
                source,
            });
        }
    };
    let (kept_lines, _torn) = flog::split_torn_tail(&existing);
    let temporary = store_dir.join(format!(".friction.jsonl.tmp.{}", std::process::id()));
    let mut handle = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(&temporary)
        .map_err(|source| LearnError::StoreIo {
            operation: "create temporary friction log",
            path: temporary.clone(),
            source,
        })?;
    {
        use std::io::Write as _;
        let io = |source| LearnError::StoreIo {
            operation: "write temporary friction log",
            path: temporary.clone(),
            source,
        };
        handle.write_all(kept_lines.as_bytes()).map_err(io)?;
        for event in &dumped.events {
            let line = serde_json::to_string(event).map_err(|source| LearnError::StoreInvalid {
                message: format!("could not serialize friction event: {source}"),
            })?;
            handle.write_all(line.as_bytes()).map_err(io)?;
            handle.write_all(b"\n").map_err(io)?;
        }
        handle.flush().map_err(io)?;
        handle.sync_all().map_err(io)?;
    }
    drop(handle);

    let map_path = migration_map_path(database_path);
    let map_json = serde_json::to_string(&dumped.map).map_err(|error| {
        invalid_store_input(format!("could not encode the log id map: {error}"))
    })?;
    fs::write(&map_path, map_json)
        .and_then(|()| File::open(&map_path)?.sync_all())
        .map_err(|source| LearnError::StoreIo {
            operation: "write migration id map",
            path: map_path,
            source,
        })?;
    fs::rename(&temporary, &log_file).map_err(|source| LearnError::StoreIo {
        operation: "install friction log",
        path: temporary.clone(),
        source,
    })?;

    for suffix in ["-wal", "-shm"] {
        let _ = fs::remove_file(PathBuf::from(format!(
            "{}{}",
            database_path.display(),
            suffix
        )));
    }
    let pre_log = PathBuf::from(format!("{}{}", database_path.display(), PRE_LOG_SUFFIX));
    fs::rename(database_path, &pre_log).map_err(|source| LearnError::StoreIo {
        operation: "keep pre-log database",
        path: database_path.to_path_buf(),
        source,
    })?;

    let mut connection =
        Connection::open(database_path).map_err(|source| LearnError::StoreDatabase {
            path: database_path.to_path_buf(),
            source,
        })?;
    varde_core::sqlite::configure_connection(&connection)
        .map_err(|source| db_error(database_path, source))?;
    migrate(&mut connection, database_path)?;
    rebuild_cache(&mut connection, store_dir, database_path, Some(&dumped.map))?;
    drop(connection);
    finish_migration(database_path)
}

fn lock_log(log_handle: &File, store_dir: &Path) -> Result<(), LearnError> {
    log_handle
        .lock_exclusive()
        .map_err(|source| LearnError::StoreIo {
            operation: "lock friction log",
            path: store_dir.to_path_buf(),
            source,
        })
}

/// Rebuild the cache when the log length or hash differs from `meta`, so reads
/// always see the log's fold. The caller holds the exclusive log lock, so the
/// log cannot change between the replay and the digest it records.
fn refresh_cache_if_stale(
    connection: &mut Connection,
    store_dir: &Path,
    database_path: &Path,
) -> Result<(), LearnError> {
    let (log_bytes, log_hash) = log_digest(store_dir)?;
    let recorded: (Option<String>, Option<String>) = connection
        .query_row(
            "SELECT (SELECT value FROM meta WHERE key = ?1),
                    (SELECT value FROM meta WHERE key = ?2)",
            params![META_KEY_LOG_BYTES, META_KEY_LOG_HASH],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .map_err(|source| db_error(database_path, source))?;
    if recorded.0.as_deref() == Some(&log_bytes.to_string())
        && recorded.1.as_deref() == Some(&log_hash)
    {
        return Ok(());
    }
    rebuild_cache(connection, store_dir, database_path, None)
}

/// Write every folded row with ids preserved from [`LogIdMap`]; events without
/// a preserved id are numbered after the highest known id, in fold order. This
/// is the single cache write path shared by opens, migrations and mutations.
fn rebuild_cache(
    connection: &mut Connection,
    store_dir: &Path,
    database_path: &Path,
    preserved: Option<&LogIdMap>,
) -> Result<(), LearnError> {
    let replay = flog::replay(store_dir)?;
    let state = flog::fold(replay.events);
    let (log_bytes, log_hash) = log_digest(store_dir)?;
    let mut map = read_log_id_map(connection, database_path)?;
    if let Some(extra) = preserved {
        map.items.extend(extra.items.clone());
        map.item_slugs.extend(extra.item_slugs.clone());
        map.occurrences.extend(extra.occurrences.clone());
        map.status_changes.extend(extra.status_changes.clone());
        map.adoptions.extend(extra.adoptions.clone());
    }

    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|source| db_error(database_path, source))?;

    let mut item_ids = HashMap::new();
    let mut taken_slugs: HashSet<String> = map.item_slugs.values().cloned().collect();
    let mut next_item_id = map.items.values().copied().max().unwrap_or(0);
    for item in &state.items {
        let id = match map.items.get(&item.event_id) {
            Some(&id) => id,
            None => {
                next_item_id += 1;
                map.items.insert(item.event_id.clone(), next_item_id);
                next_item_id
            }
        };
        item_ids.insert(item.event_id.clone(), id);
        let slug = match map.item_slugs.get(&item.event_id) {
            Some(slug) => slug.clone(),
            None => {
                let slug = flog::unique_slug(&taken_slugs, &item.slug);
                map.item_slugs.insert(item.event_id.clone(), slug.clone());
                slug
            }
        };
        taken_slugs.insert(slug.clone());
    }
    let mut occurrence_ids = HashMap::new();
    let mut next_occurrence_id = map.occurrences.values().copied().max().unwrap_or(0);
    for occurrence in &state.occurrences {
        let id = match map.occurrences.get(&occurrence.event_id) {
            Some(&id) => id,
            None => {
                next_occurrence_id += 1;
                map.occurrences
                    .insert(occurrence.event_id.clone(), next_occurrence_id);
                next_occurrence_id
            }
        };
        occurrence_ids.insert(occurrence.event_id.clone(), id);
    }
    let mut status_ids = HashMap::new();
    let mut next_status_id = map.status_changes.values().copied().max().unwrap_or(0);
    for change in &state.status_changes {
        let id = match map.status_changes.get(&change.event_id) {
            Some(&id) => id,
            None => {
                next_status_id += 1;
                map.status_changes
                    .insert(change.event_id.clone(), next_status_id);
                next_status_id
            }
        };
        status_ids.insert(change.event_id.clone(), id);
    }
    let mut adoption_ids = HashMap::new();
    let mut next_adoption_id = map.adoptions.values().copied().max().unwrap_or(0);
    for adoption in &state.adoptions {
        let id = match map.adoptions.get(&adoption.event_id) {
            Some(&id) => id,
            None => {
                next_adoption_id += 1;
                map.adoptions
                    .insert(adoption.event_id.clone(), next_adoption_id);
                next_adoption_id
            }
        };
        adoption_ids.insert(adoption.event_id.clone(), id);
    }

    transaction
        .execute("DELETE FROM incident_provenance", [])
        .map_err(|source| db_error(database_path, source))?;
    transaction
        .execute("DELETE FROM adoptions", [])
        .map_err(|source| db_error(database_path, source))?;
    transaction
        .execute("DELETE FROM items", [])
        .map_err(|source| db_error(database_path, source))?;

    for item in &state.items {
        transaction
            .execute(
                "INSERT INTO items(id, slug, title, source, repo_root, status, target, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    item_ids[&item.event_id],
                    map.item_slugs[&item.event_id],
                    item.title,
                    item.source,
                    item.repo_root,
                    item.status,
                    item.target,
                    item.created_at,
                ],
            )
            .map_err(|source| db_error(database_path, source))?;
    }
    for occurrence in &state.occurrences {
        let item_id = item_ids
            .get(&occurrence.item_event_id)
            .copied()
            .ok_or_else(|| {
                invalid_store_input("occurrence event references an item with no assembled id")
            })?;
        let occurrence_id = occurrence_ids[&occurrence.event_id];
        let at = if occurrence.at.is_empty() {
            flog::now_timestamp()
        } else {
            occurrence.at.clone()
        };
        transaction
            .execute(
                "INSERT INTO occurrences(id, item_id, at, cwd, repo_root, head_sha, evidence, cost)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    occurrence_id,
                    item_id,
                    at,
                    occurrence.cwd,
                    occurrence.repo_root,
                    occurrence.head_sha,
                    occurrence.evidence,
                    occurrence.cost,
                ],
            )
            .map_err(|source| db_error(database_path, source))?;
        if let Some(provenance) = &occurrence.provenance {
            insert_provenance(&transaction, occurrence_id, provenance, database_path)?;
        }
    }
    for change in &state.status_changes {
        let item_id = item_ids
            .get(&change.item_event_id)
            .copied()
            .ok_or_else(|| {
                invalid_store_input("status event references an item with no assembled id")
            })?;
        transaction
            .execute(
                "INSERT INTO status_changes(id, item_id, at, from_status, to_status, reason)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![
                    status_ids[&change.event_id],
                    item_id,
                    change.at,
                    change.from,
                    change.to,
                    change.reason,
                ],
            )
            .map_err(|source| db_error(database_path, source))?;
    }
    for adoption in &state.adoptions {
        transaction
            .execute(
                "INSERT INTO adoptions(id, at, summary, target_files, commit_sha, eval_before, eval_after)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    adoption_ids[&adoption.event_id],
                    adoption.at,
                    adoption.summary,
                    serde_json::to_string(&adoption.files).map_err(|error| {
                        invalid_store_input(format!(
                            "could not encode adoption file paths: {error}"
                        ))
                    })?,
                    adoption.commit_sha,
                    adoption.eval_before,
                    adoption.eval_after,
                ],
            )
            .map_err(|source| db_error(database_path, source))?;
        for item_event_id in &adoption.item_event_ids {
            let Some(&item_id) = item_ids.get(item_event_id) else {
                continue;
            };
            transaction
                .execute(
                    "INSERT INTO adoption_items(adoption_id, item_id) VALUES (?1, ?2)",
                    params![adoption_ids[&adoption.event_id], item_id],
                )
                .map_err(|source| db_error(database_path, source))?;
        }
    }

    let map_json = serde_json::to_string(&map).map_err(|error| {
        invalid_store_input(format!("could not encode the log id map: {error}"))
    })?;
    for (key, value) in [
        ("schema_version", SCHEMA_VERSION.to_string()),
        (META_KEY_LOG_BYTES, log_bytes.to_string()),
        (META_KEY_LOG_HASH, log_hash),
        (META_KEY_LOG_MAP, map_json),
    ] {
        transaction
            .execute(
                "INSERT INTO meta(key, value) VALUES (?1, ?2)
                 ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                params![key, value],
            )
            .map_err(|source| db_error(database_path, source))?;
    }
    transaction
        .commit()
        .map_err(|source| db_error(database_path, source))
}

fn read_log_id_map(connection: &Connection, database_path: &Path) -> Result<LogIdMap, LearnError> {
    let stored: Option<String> = connection
        .query_row(
            "SELECT value FROM meta WHERE key = ?1",
            [META_KEY_LOG_MAP],
            |row| row.get(0),
        )
        .optional()
        .map_err(|source| db_error(database_path, source))?;
    match stored {
        None => Ok(LogIdMap::default()),
        Some(json) => serde_json::from_str(&json).map_err(|error| {
            invalid_store_input(format!("stored log id map is not valid JSON: {error}"))
        }),
    }
}

/// Byte length and SHA-256 of the log's complete lines (a torn tail is not
/// folded, so it is not part of the digest).
fn log_digest(store_dir: &Path) -> Result<(u64, String), LearnError> {
    let path = flog::log_path(store_dir);
    let text = match fs::read_to_string(&path) {
        Ok(text) => text,
        Err(source) if source.kind() == ErrorKind::NotFound => String::new(),
        Err(source) => {
            return Err(LearnError::StoreIo {
                operation: "read friction log",
                path,
                source,
            });
        }
    };
    let (body, _torn) = flog::split_torn_tail(&text);
    Ok((body.len() as u64, sha256_hex(body.as_bytes())))
}

/// A timestamp one millisecond after `value`, keeping the fixed-width RFC 3339
/// form so lexicographic order stays chronological; non-fixed-width values get
/// a `~` suffix that sorts after every RFC 3339 character.
fn bump_timestamp(value: &str) -> String {
    let bytes = value.as_bytes();
    let fixed = bytes.len() == 24
        && bytes[4] == b'-'
        && bytes[7] == b'-'
        && bytes[10] == b'T'
        && bytes[13] == b':'
        && bytes[16] == b':'
        && bytes[19] == b'.'
        && bytes[23] == b'Z'
        && bytes[..23]
            .iter()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'-' | b'T' | b':' | b'.'));
    if !fixed {
        return format!("{value}~");
    }
    let digit = |index: usize| u64::from(bytes[index] - b'0');
    let (mut year, mut month, mut day, mut hour, mut minute, mut second, mut millis) = (
        digit(0) * 1000 + digit(1) * 100 + digit(2) * 10 + digit(3),
        digit(5) * 10 + digit(6),
        digit(8) * 10 + digit(9),
        digit(11) * 10 + digit(12),
        digit(14) * 10 + digit(15),
        digit(17) * 10 + digit(18),
        digit(20) * 100 + digit(21) * 10 + digit(22),
    );
    millis += 1;
    if millis == 1000 {
        millis = 0;
        second += 1;
    }
    if second == 60 {
        second = 0;
        minute += 1;
    }
    if minute == 60 {
        minute = 0;
        hour += 1;
    }
    if hour == 24 {
        hour = 0;
        day += 1;
    }
    let days_in_month = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            if (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 {
                29
            } else {
                28
            }
        }
        _ => 30,
    };
    if day > days_in_month {
        day = 1;
        month += 1;
    }
    if month > 12 {
        month = 1;
        year += 1;
    }
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}.{millis:03}Z")
}

/// A timestamp strictly after every existing log event, or now when the log is
/// empty, so appended events always fold after what is already written.
fn next_event_ts(store_dir: &Path) -> Result<String, LearnError> {
    let replay = flog::replay(store_dir)?;
    let now = flog::now_timestamp();
    let Some(max_ts) = replay.events.iter().map(|event| event.ts.as_str()).max() else {
        return Ok(now);
    };
    let bumped = bump_timestamp(max_ts);
    Ok(if now > bumped { now } else { bumped })
}

/// Apply already-appended events incrementally to the cache under the log
/// lock, mirroring what the fold produces for a monotonically stamped log, and
/// record the new log digest and id map. This is the cache update shared by
/// every mutator; `Store::open` rebuilds the whole cache instead.
///
/// The events are already durable in the log, so a failed apply is repaired by
/// rebuilding the cache from the log instead of reporting a failed command.
fn apply_events(
    connection: &mut Connection,
    store_dir: &Path,
    database_path: &Path,
    events: &[Event],
    preserved: Option<&LogIdMap>,
) -> Result<(), LearnError> {
    if events.is_empty() {
        return Ok(());
    }
    match apply_events_in_transaction(connection, store_dir, database_path, events, preserved) {
        Ok(()) => Ok(()),
        Err(_) => rebuild_cache(connection, store_dir, database_path, preserved),
    }
}

fn apply_events_in_transaction(
    connection: &mut Connection,
    store_dir: &Path,
    database_path: &Path,
    events: &[Event],
    preserved: Option<&LogIdMap>,
) -> Result<(), LearnError> {
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|source| db_error(database_path, source))?;
    let connection: &Connection = &transaction;
    let (log_bytes, log_hash) = log_digest(store_dir)?;
    let mut map = read_log_id_map(connection, database_path)?;
    if let Some(extra) = preserved {
        map.items.extend(extra.items.clone());
        map.item_slugs.extend(extra.item_slugs.clone());
        map.occurrences.extend(extra.occurrences.clone());
        map.status_changes.extend(extra.status_changes.clone());
        map.adoptions.extend(extra.adoptions.clone());
    }

    for event in events {
        match &event.body {
            EventBody::ItemAdded(body) => {
                let id = match preserved.and_then(|preserved| preserved.items.get(&event.id)) {
                    Some(&id) => {
                        let slug = match preserved
                            .and_then(|preserved| preserved.item_slugs.get(&event.id))
                        {
                            Some(slug) => slug.clone(),
                            None => unique_slug(connection, &body.title, database_path)?,
                        };
                        connection
                            .execute(
                                "INSERT INTO items(id, slug, title, source, repo_root, status, target, created_at)
                                 VALUES (?1, ?2, ?3, ?4, ?5, 'open', ?6, ?7)",
                                params![
                                    id,
                                    slug,
                                    &body.title,
                                    &body.source,
                                    &body.repo_root,
                                    &body.target,
                                    &event.ts,
                                ],
                            )
                            .map_err(|source| db_error(database_path, source))?;
                        id
                    }
                    None => {
                        let slug = match preserved
                            .and_then(|preserved| preserved.item_slugs.get(&event.id))
                        {
                            Some(slug) => slug.clone(),
                            None => unique_slug(connection, &body.title, database_path)?,
                        };
                        connection
                            .execute(
                                "INSERT INTO items(slug, title, source, repo_root, status, target, created_at)
                                 VALUES (?1, ?2, ?3, ?4, 'open', ?5, ?6)",
                                params![
                                    slug,
                                    &body.title,
                                    &body.source,
                                    &body.repo_root,
                                    &body.target,
                                    &event.ts,
                                ],
                            )
                            .map_err(|source| db_error(database_path, source))?;
                        let id = connection.last_insert_rowid();
                        map.item_slugs.insert(event.id.clone(), slug);
                        id
                    }
                };
                map.items.insert(event.id.clone(), id);
            }
            EventBody::OccurrenceAppended(body) => {
                let item_id = map.items.get(body.item.as_str()).copied().ok_or_else(|| {
                    invalid_store_input("occurrence event references an item with no log event")
                })?;
                let at = if body.at.is_empty() {
                    flog::now_timestamp()
                } else {
                    body.at.clone()
                };
                let id = match preserved.and_then(|preserved| preserved.occurrences.get(&event.id))
                {
                    Some(&id) => {
                        connection
                            .execute(
                                "INSERT INTO occurrences(id, item_id, at, cwd, repo_root, head_sha, evidence, cost)
                                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                                params![
                                    id,
                                    item_id,
                                    &at,
                                    &body.cwd,
                                    &body.repo_root,
                                    &body.head_sha,
                                    &body.evidence,
                                    &body.cost,
                                ],
                            )
                            .map_err(|source| db_error(database_path, source))?;
                        id
                    }
                    None => {
                        connection
                            .execute(
                                "INSERT INTO occurrences(item_id, at, cwd, repo_root, head_sha, evidence, cost)
                                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                                params![
                                    item_id,
                                    &at,
                                    &body.cwd,
                                    &body.repo_root,
                                    &body.head_sha,
                                    &body.evidence,
                                    &body.cost,
                                ],
                            )
                            .map_err(|source| db_error(database_path, source))?;
                        connection.last_insert_rowid()
                    }
                };
                if let Some(provenance) = &body.provenance {
                    insert_provenance(connection, id, provenance, database_path)?;
                }
                map.occurrences.insert(event.id.clone(), id);
            }
            EventBody::StatusChanged(body) => {
                let item_id = map.items.get(body.item.as_str()).copied().ok_or_else(|| {
                    invalid_store_input("status event references an item with no log event")
                })?;
                connection
                    .execute(
                        "UPDATE items SET status = ?1 WHERE id = ?2",
                        params![&body.to, item_id],
                    )
                    .map_err(|source| db_error(database_path, source))?;
                let id = match preserved
                    .and_then(|preserved| preserved.status_changes.get(&event.id))
                {
                    Some(&id) => {
                        connection
                            .execute(
                                "INSERT INTO status_changes(id, item_id, at, from_status, to_status, reason)
                                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                                params![id, item_id, &body.at, &body.from, &body.to, &body.reason],
                            )
                            .map_err(|source| db_error(database_path, source))?;
                        id
                    }
                    None => {
                        connection
                            .execute(
                                "INSERT INTO status_changes(item_id, at, from_status, to_status, reason)
                                 VALUES (?1, ?2, ?3, ?4, ?5)",
                                params![item_id, &body.at, &body.from, &body.to, &body.reason],
                            )
                            .map_err(|source| db_error(database_path, source))?;
                        connection.last_insert_rowid()
                    }
                };
                map.status_changes.insert(event.id.clone(), id);
            }
            EventBody::AdoptionRecorded(body) => {
                let files_json = serde_json::to_string(&body.files).map_err(|error| {
                    invalid_store_input(format!("could not encode adoption file paths: {error}"))
                })?;
                let id = match preserved.and_then(|preserved| preserved.adoptions.get(&event.id)) {
                    Some(&id) => {
                        connection
                            .execute(
                                "INSERT INTO adoptions(id, at, summary, target_files, commit_sha, eval_before, eval_after)
                                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                                params![
                                    id,
                                    &body.at,
                                    &body.summary,
                                    &files_json,
                                    &body.commit_sha,
                                    &body.eval_before,
                                    &body.eval_after,
                                ],
                            )
                            .map_err(|source| db_error(database_path, source))?;
                        id
                    }
                    None => {
                        connection
                            .execute(
                                "INSERT INTO adoptions(at, summary, target_files, commit_sha, eval_before, eval_after)
                                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                                params![
                                    &body.at,
                                    &body.summary,
                                    &files_json,
                                    &body.commit_sha,
                                    &body.eval_before,
                                    &body.eval_after,
                                ],
                            )
                            .map_err(|source| db_error(database_path, source))?;
                        connection.last_insert_rowid()
                    }
                };
                for item_event_id in &body.items {
                    if let Some(&item_id) = map.items.get(item_event_id) {
                        connection
                            .execute(
                                "INSERT INTO adoption_items(adoption_id, item_id) VALUES (?1, ?2)",
                                params![id, item_id],
                            )
                            .map_err(|source| db_error(database_path, source))?;
                    }
                }
                map.adoptions.insert(event.id.clone(), id);
            }
        }
    }

    let map_json = serde_json::to_string(&map).map_err(|error| {
        invalid_store_input(format!("could not encode the log id map: {error}"))
    })?;
    for (key, value) in [
        (META_KEY_LOG_BYTES, log_bytes.to_string()),
        (META_KEY_LOG_HASH, log_hash),
        (META_KEY_LOG_MAP, map_json),
    ] {
        connection
            .execute(
                "INSERT INTO meta(key, value) VALUES (?1, ?2)
                 ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                params![key, value],
            )
            .map_err(|source| db_error(database_path, source))?;
    }
    transaction
        .commit()
        .map_err(|source| db_error(database_path, source))
}

/// Lowest free slug in the cache, using the fold's own `-N` numbering.
fn unique_slug(
    connection: &Connection,
    title: &str,
    database_path: &Path,
) -> Result<String, LearnError> {
    let mut statement = connection
        .prepare("SELECT slug FROM items")
        .map_err(|source| db_error(database_path, source))?;
    let taken = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(|source| db_error(database_path, source))?
        .collect::<Result<HashSet<_>, _>>()
        .map_err(|source| db_error(database_path, source))?;
    Ok(flog::unique_slug(&taken, &flog::safe_slug(title)))
}

/// Whether a pre-existing row id is already taken in the cache, so an import
/// keeps its own ids only when they are free.
fn row_id_exists(
    connection: &Connection,
    table: &str,
    id: i64,
    database_path: &Path,
) -> Result<bool, LearnError> {
    connection
        .query_row(
            &format!("SELECT EXISTS(SELECT 1 FROM {table} WHERE id = ?1)"),
            [id],
            |row| row.get(0),
        )
        .map_err(|source| db_error(database_path, source))
}

/// The integer id assembled for an item event, from the persisted map.
fn find_item_id_by_event(
    connection: &Connection,
    event_id: &str,
    database_path: &Path,
) -> Result<i64, LearnError> {
    let map = read_log_id_map(connection, database_path)?;
    map.items.get(event_id).copied().ok_or_else(|| {
        invalid_store_input(format!(
            "friction item event `{event_id}` was not assembled"
        ))
    })
}

/// The event id of an existing item, inverting the persisted map.
fn item_event_id(
    connection: &Connection,
    item_id: i64,
    database_path: &Path,
) -> Result<String, LearnError> {
    let map = read_log_id_map(connection, database_path)?;
    map.items
        .iter()
        .find(|(_, id)| **id == item_id)
        .map(|(event_id, _)| event_id.clone())
        .ok_or_else(|| invalid_store_input(format!("friction item {item_id} has no log event")))
}

fn acquire_init_lock(database_path: &Path) -> Result<File, LearnError> {
    let lock_path = resolve_directory(&database_path.with_extension("db.init.lock"), 0)?;
    reject_git_path(&lock_path)?;
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(&lock_path)
        .map_err(|source| LearnError::StoreIo {
            operation: "open initialization lock",
            path: lock_path.clone(),
            source,
        })?;
    let deadline = Instant::now() + Duration::from_secs(30);
    loop {
        match file.try_lock_exclusive() {
            Ok(()) => return Ok(file),
            Err(source)
                if source.kind() == std::io::ErrorKind::WouldBlock && Instant::now() < deadline =>
            {
                thread::sleep(Duration::from_millis(25));
            }
            Err(source) if source.kind() == std::io::ErrorKind::WouldBlock => {
                return Err(LearnError::StoreIo {
                    operation: "wait for store initialization lock",
                    path: lock_path,
                    source: std::io::Error::new(
                        std::io::ErrorKind::TimedOut,
                        "timed out after 30 seconds",
                    ),
                });
            }
            Err(source) => {
                return Err(LearnError::StoreIo {
                    operation: "lock store initialization",
                    path: lock_path,
                    source,
                });
            }
        }
    }
}

fn existing_directory(path: &Path) -> Result<PathBuf, LearnError> {
    let mut probe = path.to_path_buf();
    loop {
        match fs::metadata(&probe) {
            Ok(metadata) if metadata.is_dir() => {
                return probe.canonicalize().map_err(|source| LearnError::StoreIo {
                    operation: "canonicalize existing store parent",
                    path: probe,
                    source,
                });
            }
            Ok(_) | Err(_) => {
                if !probe.pop() {
                    return Err(LearnError::StoreIo {
                        operation: "find an existing store parent",
                        path: path.to_path_buf(),
                        source: std::io::Error::new(
                            std::io::ErrorKind::NotFound,
                            "no existing parent directory",
                        ),
                    });
                }
            }
        }
    }
}

fn migrate(connection: &mut Connection, database_path: &Path) -> Result<(), LearnError> {
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|source| db_error(database_path, source))?;
    let current = read_schema_version(&tx, database_path)?;
    if current > SCHEMA_VERSION {
        return Err(LearnError::StoreSchemaTooNew {
            found: current,
            supported: SCHEMA_VERSION,
        });
    }
    if current < 1 {
        tx.execute_batch(SCHEMA_V1)
            .map_err(|source| db_error(database_path, source))?;
        tx.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?1)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            params!["1"],
        )
        .map_err(|source| db_error(database_path, source))?;
    }
    if current < 2 {
        tx.execute_batch(SCHEMA_V2)
            .map_err(|source| db_error(database_path, source))?;
        tx.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?1)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            params!["2"],
        )
        .map_err(|source| db_error(database_path, source))?;
    }
    if current < SCHEMA_VERSION {
        tx.execute_batch(SCHEMA_V3)
            .map_err(|source| db_error(database_path, source))?;
        tx.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?1)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            params![SCHEMA_VERSION.to_string()],
        )
        .map_err(|source| db_error(database_path, source))?;
    }
    tx.commit()
        .map_err(|source| db_error(database_path, source))
}

fn read_schema_version(connection: &Connection, database_path: &Path) -> Result<i64, LearnError> {
    let has_meta: bool = connection
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta')",
            [],
            |row| row.get(0),
        )
        .map_err(|source| db_error(database_path, source))?;
    if !has_meta {
        return Ok(0);
    }
    let version: Option<String> = connection
        .query_row(
            "SELECT value FROM meta WHERE key = 'schema_version'",
            [],
            |row| row.get(0),
        )
        .optional()
        .map_err(|source| db_error(database_path, source))?;
    match version {
        None => Ok(0),
        Some(value) => value
            .parse::<i64>()
            .map_err(|_| LearnError::StoreSchemaVersion { value }),
    }
}

fn db_error(path: &Path, source: rusqlite::Error) -> LearnError {
    LearnError::StoreDatabase {
        path: path.to_path_buf(),
        source,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Append fixture events through the log and apply them, as every mutator
    /// does, so a cache rebuild reproduces what a test asserts.
    fn append_fixture(store: &mut Store, events: &[Event]) {
        let store_dir = store.store_dir.clone();
        let database_path = store.database_path.clone();
        store
            .mutate(|connection, log_handle| {
                for event in events {
                    flog::append(&store_dir, log_handle, event)?;
                }
                apply_events(connection, &store_dir, &database_path, events, None)
            })
            .expect("append fixture events");
    }

    /// Strictly increasing fixture timestamps, all before any real clock reading.
    fn fixture_ts(index: usize) -> String {
        format!(
            "2026-01-01T{:02}:{:02}:{:02}.000Z",
            index / 3600,
            (index / 60) % 60,
            index % 60
        )
    }

    fn fixture_item(index: usize, title: &str, repo_root: Option<String>) -> Event {
        Event::at(
            fixture_ts(index),
            repo_root.clone(),
            EventBody::ItemAdded(flog::ItemAdded {
                title: title.to_owned(),
                source: "varde learn test".to_owned(),
                repo_root,
                target: None,
            }),
        )
    }

    fn fixture_occurrence(index: usize, item: &Event, at: &str, evidence: &str) -> Event {
        Event::at(
            fixture_ts(index),
            None,
            EventBody::OccurrenceAppended(Box::new(flog::OccurrenceAppended {
                item: item.id.clone(),
                at: at.to_owned(),
                cwd: "/tmp".to_owned(),
                repo_root: None,
                head_sha: None,
                evidence: evidence.to_owned(),
                cost: None,
                provenance: None,
            })),
        )
    }

    fn fixture_status(
        index: usize,
        item: &Event,
        at: &str,
        (from, to): (&str, &str),
        reason: &str,
    ) -> Event {
        Event::at(
            fixture_ts(index),
            None,
            EventBody::StatusChanged(flog::StatusChanged {
                item: item.id.clone(),
                at: at.to_owned(),
                from: from.to_owned(),
                to: to.to_owned(),
                reason: reason.to_owned(),
            }),
        )
    }

    fn fixture_item_id(store: &Store, item: &Event) -> i64 {
        find_item_id_by_event(&store.connection, &item.id, &store.database_path)
            .expect("fixture item id")
    }

    fn adoption_request(item_id: i64, summary: &str, file: &str) -> AdoptionRecordRequest {
        AdoptionRecordRequest {
            item_ids: vec![item_id],
            summary: summary.to_owned(),
            files: vec![file.to_owned()],
            commit_sha: None,
            eval_before: None,
            eval_after: None,
        }
    }

    fn create_committed_repository(path: &Path) -> (PathBuf, String) {
        fs::create_dir_all(path).expect("create repository directory");
        let run_git = |args: &[&str]| {
            let status = Command::new("git")
                .args(args)
                .current_dir(path)
                .env_remove("GIT_DIR")
                .env_remove("GIT_WORK_TREE")
                .env_remove("GIT_COMMON_DIR")
                .status()
                .expect("run git");
            assert!(status.success(), "git {args:?} failed");
        };
        run_git(&["init", "--quiet"]);
        run_git(&["config", "user.name", "Varde Test"]);
        run_git(&["config", "user.email", "varde-test@example.invalid"]);
        fs::write(path.join("README.md"), "friction fixture\n").expect("write fixture");
        run_git(&["add", "README.md"]);
        run_git(&["commit", "--quiet", "-m", "fixture"]);
        let head = Command::new("git")
            .args(["rev-parse", "HEAD"])
            .current_dir(path)
            .env_remove("GIT_DIR")
            .env_remove("GIT_WORK_TREE")
            .env_remove("GIT_COMMON_DIR")
            .output()
            .expect("read Git HEAD");
        assert!(head.status.success(), "git rev-parse HEAD failed");
        (
            path.canonicalize().expect("canonical repository path"),
            String::from_utf8_lossy(&head.stdout).trim().to_owned(),
        )
    }

    fn historical_request(title: &str, facts: serde_json::Value) -> HistoricalCaptureRequest {
        HistoricalCaptureRequest {
            mode: HistoricalItemMode::Create {
                source: "varde-learn".to_owned(),
                title: title.to_owned(),
                target: Some("skills/varde-learn/SKILL.md".to_owned()),
                repo_root: Some("/historical/project".to_owned()),
            },
            occurrence: HistoricalOccurrenceRequest {
                at: "2026-09-12T09:45:00Z".to_owned(),
                cwd: "/historical/project/subdir".to_owned(),
                repo_root: Some("/historical/project".to_owned()),
                head_sha: Some("historical-head".to_owned()),
                evidence: "generated incident summary".to_owned(),
                canonical_facts: facts,
                witness: HistoricalWitness {
                    harness: "codex".to_owned(),
                    thread_id: "thread-41".to_owned(),
                    incident_kind: "failed-tool".to_owned(),
                    witness_id: Some("event-17".to_owned()),
                    source_id: "/old/capture/session.jsonl".to_owned(),
                    record_index: 17,
                    byte_start: 512,
                    byte_end: 900,
                    record_digest: format!("sha256:{}", "a".repeat(64)),
                },
            },
        }
    }

    #[test]
    fn initializes_schema_and_rejects_future_versions_transactionally() {
        let temp = tempfile::tempdir().expect("tempdir");
        let store = Store::open(temp.path()).expect("initialize store");
        assert_eq!(
            store.schema_version().expect("schema version"),
            SCHEMA_VERSION
        );
        let foreign_keys: i64 = store
            .connection
            .pragma_query_value(None, "foreign_keys", |row| row.get(0))
            .expect("foreign keys pragma");
        let busy_timeout: i64 = store
            .connection
            .pragma_query_value(None, "busy_timeout", |row| row.get(0))
            .expect("busy timeout pragma");
        let journal_mode: String = store
            .connection
            .pragma_query_value(None, "journal_mode", |row| row.get(0))
            .expect("journal mode pragma");
        assert_eq!(foreign_keys, 1);
        assert_eq!(busy_timeout, 30_000);
        assert_eq!(journal_mode.to_lowercase(), "wal");
        let foreign_key_error = store
            .connection
            .execute(
                "INSERT INTO occurrences(item_id, at, cwd, evidence) VALUES (999, 'now', '/tmp', 'evidence')",
                [],
            )
            .expect_err("foreign key should reject a missing item");
        assert!(matches!(
            foreign_key_error,
            rusqlite::Error::SqliteFailure(_, _)
        ));
        drop(store);

        let database = temp.path().join(DATABASE_FILE);
        let connection = Connection::open(&database).expect("open existing database");
        connection
            .execute(
                "UPDATE meta SET value = '999' WHERE key = 'schema_version'",
                [],
            )
            .expect("write future version");
        drop(connection);

        let error = match Store::open(temp.path()) {
            Ok(_) => panic!("future schema is rejected"),
            Err(error) => error,
        };
        assert!(matches!(
            error,
            LearnError::StoreSchemaTooNew { found: 999, .. }
        ));
        let connection = Connection::open(database).expect("reopen database");
        let version: String = connection
            .query_row(
                "SELECT value FROM meta WHERE key = 'schema_version'",
                [],
                |row| row.get(0),
            )
            .expect("read unchanged version");
        assert_eq!(version, "999");
    }

    #[test]
    fn migrates_v1_records_to_schema4_without_data_loss_or_fabricated_provenance() {
        let temp = tempfile::tempdir().expect("tempdir");
        let database = temp.path().join(DATABASE_FILE);
        let connection = Connection::open(&database).expect("create v1 database");
        connection
            .execute_batch(SCHEMA_V1)
            .expect("create schema v1 tables");
        connection
            .execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', '1')",
                [],
            )
            .expect("record schema v1");
        connection
            .execute(
                "INSERT INTO items(slug, title, source, repo_root, status, target, created_at)
                 VALUES ('legacy-item', 'Legacy item', 'varde-change', NULL, 'resolved', NULL, '2026-09-01T00:00:00.000Z')",
                [],
            )
            .expect("insert v1 friction item");
        connection
            .execute(
                "INSERT INTO occurrences(item_id, at, cwd, evidence)
                 VALUES (1, '2026-09-01T00:01:00.000Z', '/legacy/project', 'legacy evidence')",
                [],
            )
            .expect("insert v1 occurrence");
        connection
            .execute(
                "INSERT INTO status_changes(item_id, at, from_status, to_status, reason)
                 VALUES (1, '2026-09-01T00:02:00.000Z', 'open', 'resolved', 'legacy resolution')",
                [],
            )
            .expect("insert v1 status history");
        drop(connection);

        let mut store = Store::open(temp.path()).expect("migrate v1 database");
        assert_eq!(
            store.schema_version().expect("schema version"),
            SCHEMA_VERSION
        );
        let show = store
            .show_friction("1", PageRequest::default())
            .expect("read preserved friction item");
        assert_eq!(show.item.title, "Legacy item");
        assert_eq!(show.item.status, "resolved");
        assert_eq!(show.occurrences.items.len(), 1);
        assert_eq!(show.occurrences.items[0].evidence, "legacy evidence");
        assert!(show.occurrences.items[0].provenance.is_none());
        assert_eq!(show.status_changes.items.len(), 1);
        assert_eq!(show.status_changes.items[0].reason, "legacy resolution");
        let adoption_table: bool = store
            .connection
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'adoptions')",
                [],
                |row| row.get(0),
            )
            .expect("check adoption table");
        assert!(adoption_table);
    }

    #[test]
    fn migrates_v2_store_to_schema4_without_inventing_legacy_provenance() {
        let temp = tempfile::tempdir().expect("tempdir");
        let database = temp.path().join(DATABASE_FILE);
        let connection = Connection::open(&database).expect("create v2 database");
        connection
            .execute_batch(SCHEMA_V1)
            .expect("create schema v1 tables");
        connection
            .execute_batch(SCHEMA_V2)
            .expect("create schema v2 tables");
        connection
            .execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', '2')",
                [],
            )
            .expect("record schema v2");
        connection
            .execute(
                "INSERT INTO items(slug, title, source, status, created_at)
                 VALUES ('legacy-v2', 'Legacy v2', 'varde-change', 'resolved', '2026-09-10')",
                [],
            )
            .expect("insert legacy v2 item");
        connection
            .execute(
                "INSERT INTO occurrences(item_id, at, cwd, evidence)
                 VALUES (1, '2026-09-10T12:00:00Z', '/old/repo', 'old evidence')",
                [],
            )
            .expect("insert legacy v2 occurrence");
        connection
            .execute(
                "INSERT INTO adoptions(at, summary, target_files) VALUES ('2026-09-11', 'old adoption', '[]')",
                [],
            )
            .expect("insert v2 adoption");
        drop(connection);

        let mut store = Store::open(temp.path()).expect("migrate schema v2");
        assert_eq!(
            store.schema_version().expect("schema version"),
            SCHEMA_VERSION
        );
        let show = store
            .show_friction("1", PageRequest::default())
            .expect("read migrated item");
        assert_eq!(show.occurrences.items[0].at, "2026-09-10T12:00:00Z");
        assert_eq!(show.occurrences.items[0].cwd, "/old/repo");
        assert_eq!(show.occurrences.items[0].evidence, "old evidence");
        let provenance_rows: i64 = store
            .connection
            .query_row("SELECT COUNT(*) FROM incident_provenance", [], |row| {
                row.get(0)
            })
            .expect("count provenance rows");
        let adoption_rows: i64 = store
            .connection
            .query_row("SELECT COUNT(*) FROM adoptions", [], |row| row.get(0))
            .expect("count preserved adoptions");
        assert_eq!(provenance_rows, 0);
        assert_eq!(adoption_rows, 1);
    }

    #[test]
    fn historical_capture_is_canonical_idempotent_and_conflicts_atomically() {
        let temp = tempfile::tempdir().expect("tempdir");
        let mut store = Store::open(&temp.path().join("store")).expect("open store");
        let facts_a = serde_json::from_str(
            r#"{"event":{"text":"permission denied","tool":"exec"},"context":{"turn":3}}"#,
        )
        .expect("parse first fact representation");
        let first = store
            .record_historical_occurrence(historical_request("Original title", facts_a))
            .expect("record first historical incident");
        assert!(first.created);
        assert_eq!(first.occurrence.at, "2026-09-12T09:45:00Z");
        assert_eq!(first.occurrence.cwd, "/historical/project/subdir");
        assert_eq!(
            first.occurrence.repo_root.as_deref(),
            Some("/historical/project")
        );
        assert_eq!(
            first.occurrence.head_sha.as_deref(),
            Some("historical-head")
        );
        let provenance = first
            .occurrence
            .provenance
            .as_ref()
            .expect("new occurrence provenance");

        let facts_b = serde_json::from_str(
            "{ \"context\" : { \"turn\" : 3 }, \"event\" : { \"tool\" : \"exec\", \"text\" : \"permission denied\" } }",
        )
        .expect("parse copied fact representation");
        let mut retry = historical_request("Edited generated title", facts_b);
        retry.occurrence.evidence = "edited generated report text".to_owned();
        retry.occurrence.witness.source_id = "/relocated/copy/session.jsonl".to_owned();
        retry.occurrence.witness.record_index = 88;
        retry.occurrence.witness.byte_start = 2_000;
        retry.occurrence.witness.byte_end = 2_400;
        retry.occurrence.witness.record_digest = format!("sha256:{}", "b".repeat(64));
        let repeated = store
            .record_historical_occurrence(retry)
            .expect("identical parsed event should deduplicate after relocation");
        assert!(!repeated.created);
        assert_eq!(repeated.item.id, first.item.id);
        assert_eq!(repeated.occurrence.id, first.occurrence.id);
        assert_eq!(repeated.item.title, "Original title");
        assert_eq!(
            repeated
                .occurrence
                .provenance
                .as_ref()
                .unwrap()
                .incident_key,
            provenance.incident_key
        );

        for changed_facts in [
            serde_json::json!({
                "event": {"text": "permission denied after retry", "tool": "exec"},
                "context": {"turn": 3}
            }),
            serde_json::json!({
                "event": {"text": "permission denied", "tool": "exec"},
                "context": {"turn": 4}
            }),
        ] {
            let mut conflict = historical_request("Must not create a second item", changed_facts);
            conflict.mode = HistoricalItemMode::Create {
                source: "varde-learn".to_owned(),
                title: "Must not create a second item".to_owned(),
                target: None,
                repo_root: None,
            };
            let error = store
                .record_historical_occurrence(conflict)
                .expect_err("changed native facts under the same key must conflict");
            assert!(matches!(
                error,
                LearnError::Diagnose {
                    code: "diagnose_incident_conflict",
                    ..
                }
            ));
        }
        let item_count: i64 = store
            .connection
            .query_row("SELECT COUNT(*) FROM items", [], |row| row.get(0))
            .expect("count items after conflict");
        let occurrence_count: i64 = store
            .connection
            .query_row("SELECT COUNT(*) FROM occurrences", [], |row| row.get(0))
            .expect("count occurrences after conflict");
        assert_eq!(item_count, 1);
        assert_eq!(occurrence_count, 1);

        let mut second_kind = historical_request(
            "A second classification of the same witness",
            serde_json::json!({"event":{"text":"permission denied","tool":"exec"}}),
        );
        second_kind.mode = HistoricalItemMode::Append {
            item_id: first.item.id,
        };
        second_kind.occurrence.witness.incident_kind = "workflow-deviation".to_owned();
        let second_kind = store
            .record_historical_occurrence(second_kind)
            .expect("allow a separate incident kind for the same witness");
        assert!(second_kind.created);

        let across_kinds = store
            .find_historical_witness("codex", "thread-41", "event-17")
            .expect("find witness regardless of kind");
        assert_eq!(across_kinds.len(), 2);
        assert_eq!(across_kinds[0].incident_kind, "failed-tool");
        assert_eq!(across_kinds[1].incident_kind, "workflow-deviation");
    }

    #[test]
    fn concurrent_historical_retries_return_the_same_item_and_occurrence() {
        let temp = tempfile::tempdir().expect("tempdir");
        let store_path = temp.path().join("store");
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
        let mut workers = Vec::new();
        for _ in 0..2 {
            let path = store_path.clone();
            let barrier = barrier.clone();
            workers.push(std::thread::spawn(move || {
                let mut store = Store::open(&path).expect("open shared store");
                barrier.wait();
                store
                    .record_historical_occurrence(historical_request(
                        "Concurrent item",
                        serde_json::json!({"event":{"text":"same"}}),
                    ))
                    .expect("record or find incident")
            }));
        }
        let first = workers.remove(0).join().expect("first worker");
        let second = workers.remove(0).join().expect("second worker");
        assert_ne!(first.created, second.created);
        assert_eq!(first.item.id, second.item.id);
        assert_eq!(first.occurrence.id, second.occurrence.id);
        let store = Store::open(&store_path).expect("reopen store");
        let item_count: i64 = store
            .connection
            .query_row("SELECT COUNT(*) FROM items", [], |row| row.get(0))
            .expect("count concurrent items");
        let occurrence_count: i64 = store
            .connection
            .query_row("SELECT COUNT(*) FROM occurrences", [], |row| row.get(0))
            .expect("count concurrent occurrences");
        assert_eq!(item_count, 1);
        assert_eq!(occurrence_count, 1);
    }

    #[test]
    fn imported_provenance_round_trips_and_new_slug_collisions_roll_back() {
        let temp = tempfile::tempdir().expect("tempdir");
        let mut source = Store::open(&temp.path().join("source")).expect("open source store");
        let captured = source
            .record_historical_occurrence(historical_request(
                "Imported historical incident",
                serde_json::json!({"event":{"text":"failure"}}),
            ))
            .expect("capture source incident");
        let exported = source.export_items().expect("export source item").remove(0);
        let entry = FrictionImportEntry {
            id: Some(exported.item.id),
            slug: exported.item.slug.clone(),
            title: exported.item.title.clone(),
            source: exported.item.source.clone(),
            repo_root: exported.item.repo_root.clone(),
            status: FrictionStatus::parse(&exported.item.status).unwrap(),
            target: exported.item.target.clone(),
            created_at: Some(exported.item.created_at.clone()),
            occurrences: exported.occurrences.clone(),
            status_changes: exported.status_changes.clone(),
        };

        let mut restored = Store::open(&temp.path().join("restored")).expect("open restore store");
        let imported = restored
            .import_friction(&entry)
            .expect("import provenance")
            .expect("new slug imported");
        let restored_show = restored
            .show_friction(&imported.id.to_string(), PageRequest::default())
            .expect("show imported provenance");
        assert_eq!(
            restored_show.occurrences.items[0].provenance,
            captured.occurrence.provenance
        );
        assert!(restored.import_friction(&entry).unwrap().is_none());

        let mut conflicting_copy = entry.clone();
        conflicting_copy.slug = "second-copy-of-same-event".to_owned();
        conflicting_copy.id = None;
        let error = restored
            .import_friction(&conflicting_copy)
            .expect_err("a new slug cannot duplicate an incident key");
        assert!(matches!(
            error,
            LearnError::Diagnose {
                code: "diagnose_incident_conflict",
                ..
            }
        ));
        let item_count: i64 = restored
            .connection
            .query_row("SELECT COUNT(*) FROM items", [], |row| row.get(0))
            .expect("count items after rejected import");
        let occurrence_count: i64 = restored
            .connection
            .query_row("SELECT COUNT(*) FROM occurrences", [], |row| row.get(0))
            .expect("count occurrences after rejected import");
        assert_eq!(item_count, 1);
        assert_eq!(occurrence_count, 1);
    }

    #[test]
    fn verified_fallback_identity_ignores_physical_source_relocation() {
        let temp = tempfile::tempdir().expect("tempdir");
        let mut store = Store::open(&temp.path().join("store")).expect("open store");
        let facts = serde_json::json!({"event":{"text":"same parsed row"}});
        let mut first_request = historical_request("Fallback identity", facts.clone());
        first_request.occurrence.witness.witness_id = None;
        let first = store
            .record_historical_occurrence(first_request)
            .expect("capture fallback identity");
        let mut copied_request = historical_request("Moved fallback identity", facts);
        copied_request.occurrence.witness.witness_id = None;
        copied_request.occurrence.witness.source_id = "/moved/copy/session.jsonl".to_owned();
        copied_request.occurrence.witness.byte_start = 9_000;
        copied_request.occurrence.witness.byte_end = 9_500;
        copied_request.occurrence.evidence = "different generated prose".to_owned();
        let copied = store
            .record_historical_occurrence(copied_request)
            .expect("logical record anchor remains stable after relocation");
        assert!(!copied.created);
        assert_eq!(copied.item.id, first.item.id);
        assert_eq!(copied.occurrence.id, first.occurrence.id);

        let first_provenance = first.occurrence.provenance.as_ref().unwrap();
        let fallback = store
            .find_historical_fallback_witness(
                "codex",
                "thread-41",
                first_provenance.record_index,
                &first_provenance.record_digest,
            )
            .expect("find fallback witness across incident kinds");
        assert_eq!(fallback.len(), 1);
        assert_eq!(fallback[0].incident_kind, "failed-tool");

        let mut other_kind = historical_request(
            "A second classification must be rejected",
            serde_json::json!({"event":{"text":"same parsed row"}}),
        );
        other_kind.occurrence.witness.witness_id = None;
        other_kind.occurrence.witness.incident_kind = "workflow-deviation".to_owned();
        assert!(matches!(
            store.record_historical_occurrence(other_kind),
            Err(LearnError::Diagnose {
                code: "diagnose_incident_kind_conflict",
                ..
            })
        ));

        for (record_index, record_digest) in [
            (18, first_provenance.record_digest.clone()),
            (17, format!("sha256:{}", "c".repeat(64))),
        ] {
            let mut conflicting = historical_request(
                "Do not duplicate an uncertain fallback witness",
                serde_json::json!({"event":{"text":"same parsed row"}}),
            );
            conflicting.occurrence.witness.witness_id = None;
            conflicting.occurrence.witness.record_index = record_index;
            conflicting.occurrence.witness.record_digest = record_digest;
            let error = store
                .record_historical_occurrence(conflicting)
                .expect_err("repositioned or rewritten fallback witnesses conflict");
            assert!(matches!(
                error,
                LearnError::Diagnose {
                    code: "diagnose_incident_conflict",
                    ..
                }
            ));
        }
    }

    #[test]
    fn older_historical_capture_does_not_appear_as_post_adoption_recurrence() {
        let temp = tempfile::tempdir().expect("tempdir");
        let mut store = Store::open(&temp.path().join("store")).expect("open store");
        let first = store
            .record_historical_occurrence(historical_request(
                "Old incident",
                serde_json::json!({"event":{"text":"old failure"}}),
            ))
            .expect("capture old incident");
        store
            .record_adoption_at(
                AdoptionRecordRequest {
                    files: vec!["skills/varde-learn/SKILL.md".to_owned()],
                    ..adoption_request(first.item.id, "Fix old failure", "")
                },
                "2026-09-13T00:00:00Z".to_owned(),
            )
            .expect("record adoption");

        let mut later = historical_request(
            "Later incident",
            serde_json::json!({"event":{"text":"new failure"}}),
        );
        later.mode = HistoricalItemMode::Append {
            item_id: first.item.id,
        };
        later.occurrence.at = "2026-09-14T00:00:00Z".to_owned();
        later.occurrence.witness.witness_id = Some("event-18".to_owned());
        later.occurrence.witness.record_index += 1;
        let later = store
            .record_historical_occurrence(later)
            .expect("capture later incident after adoption");
        assert_eq!(later.occurrence.at, "2026-09-14T00:00:00Z");

        let recurrence = store
            .list_recurrences(PageRequest::default())
            .expect("read recurrence report");
        assert_eq!(recurrence.page.total, 1);
        assert_eq!(recurrence.page.items[0].occurrence.id, later.occurrence.id);
        assert_eq!(
            recurrence.page.items[0].occurrence.at,
            "2026-09-14T00:00:00Z"
        );
        assert_eq!(later.item.status, "promoted");
    }

    #[test]
    fn adoption_round_trips_benchmarks_and_rolls_back_when_an_item_is_missing() {
        let temp = tempfile::tempdir().expect("tempdir");
        let cwd = temp.path().join("outside-git");
        fs::create_dir(&cwd).expect("create outside-Git cwd");
        let mut store = Store::open(&temp.path().join("store")).expect("open store");
        let item = store
            .add_friction(FrictionAddRequest {
                mode: FrictionAddMode::Create {
                    source: "varde-change test".to_owned(),
                    title: "Adoption source".to_owned(),
                    target: None,
                    global: true,
                },
                evidence: "evidence".to_owned(),
                cwd,
            })
            .expect("create friction item");
        let before = "{\n  \"score\": 0.5\n}\n".to_owned();
        let after = "{\"score\":0.9}".to_owned();
        let record = store
            .record_adoption(AdoptionRecordRequest {
                item_ids: vec![item.id],
                summary: "Adopt configured global storage".to_owned(),
                files: vec!["learn-cli/src/friction.rs".to_owned()],
                commit_sha: Some("0123456789abcdef".to_owned()),
                eval_before: Some(before.clone()),
                eval_after: Some(after.clone()),
            })
            .expect("record adoption");
        assert_eq!(record.eval_before.as_deref(), Some(before.as_str()));
        assert_eq!(record.eval_after.as_deref(), Some(after.as_str()));
        assert_eq!(record.files, ["learn-cli/src/friction.rs"]);
        assert_eq!(record.item_ids, [item.id]);

        let error = store
            .record_adoption(AdoptionRecordRequest {
                item_ids: vec![item.id, 999_999],
                summary: "Must be atomic".to_owned(),
                files: vec!["skills/varde-learn/SKILL.md".to_owned()],
                commit_sha: None,
                eval_before: None,
                eval_after: None,
            })
            .expect_err("missing item rejects adoption");
        assert!(matches!(error, LearnError::StoreItemNotFound { .. }));
        let show = store
            .show_friction(&item.id.to_string(), PageRequest::default())
            .expect("read unchanged promoted item");
        assert_eq!(show.item.status, "promoted");
        assert_eq!(show.status_changes.items.len(), 1);
        let adoption_count: i64 = store
            .connection
            .query_row("SELECT COUNT(*) FROM adoptions", [], |row| row.get(0))
            .expect("count persisted adoptions");
        assert_eq!(adoption_count, 1);
    }

    #[test]
    fn recurrence_compares_offsets_dates_and_equal_instants_and_pairs_latest_adoption() {
        let temp = tempfile::tempdir().expect("tempdir");
        let cwd = temp.path().join("outside-git");
        fs::create_dir(&cwd).expect("create outside-Git cwd");
        let mut store = Store::open(&temp.path().join("store")).expect("open store");
        let item_event = fixture_item(0, "Timestamp comparisons", None);
        append_fixture(
            &mut store,
            &[
                item_event.clone(),
                fixture_occurrence(1, &item_event, "2026-09-01T09:59:59Z", "initial occurrence"),
                fixture_occurrence(2, &item_event, "2026-09-01T10:00:00Z", "equal instant"),
                fixture_occurrence(3, &item_event, "2026-09-02", "date-only legacy occurrence"),
                fixture_occurrence(
                    4,
                    &item_event,
                    "2026-09-02T10:00:00Z",
                    "equal to second adoption",
                ),
                fixture_occurrence(
                    5,
                    &item_event,
                    "2026-09-02T10:00:01Z",
                    "after second adoption",
                ),
                fixture_occurrence(6, &item_event, "not-a-date", "invalid timestamp"),
            ],
        );
        let item_id = fixture_item_id(&store, &item_event);
        let first = store
            .record_adoption_at(
                adoption_request(item_id, "First applied change", "src/first.rs"),
                "2026-09-01T12:00:00+02:00".to_owned(),
            )
            .expect("record first adoption");
        let second = store
            .record_adoption_at(
                adoption_request(item_id, "Second applied change", "src/second.rs"),
                "2026-09-02T12:00:00+02:00".to_owned(),
            )
            .expect("record second adoption");

        let invalid_event = fixture_item(7, "Invalid adoption timestamp", None);
        append_fixture(
            &mut store,
            &[
                invalid_event.clone(),
                fixture_occurrence(8, &invalid_event, "2099-01-01", "no timestamp inference"),
            ],
        );
        let invalid_item_id = fixture_item_id(&store, &invalid_event);
        store
            .record_adoption_at(
                adoption_request(
                    invalid_item_id,
                    "Invalid timestamp fixture",
                    "src/invalid.rs",
                ),
                "not-a-date".to_owned(),
            )
            .expect("record third adoption");

        let first_page = store
            .list_recurrences(PageRequest {
                offset: 0,
                limit: 1,
            })
            .expect("read first recurrence page");
        assert_eq!(first_page.page.total, 3);
        assert!(first_page.page.truncated);
        assert_eq!(first_page.page.next_offset, Some(1));
        assert_eq!(first_page.skipped_invalid_timestamps, 2);
        let first_row = &first_page.page.items[0];
        assert_eq!(first_row.adoption_id, first.id);
        assert_eq!(first_row.summary, "First applied change");
        assert_eq!(first_row.occurrence.at, "2026-09-02");
        assert_eq!(first_row.occurrence.evidence, "date-only legacy occurrence");

        let second_page = store
            .list_recurrences(PageRequest {
                offset: 1,
                limit: 1,
            })
            .expect("read second recurrence page");
        assert_eq!(second_page.page.total, 3);
        assert!(second_page.page.truncated);
        assert_eq!(second_page.page.items[0].adoption_id, first.id);
        assert_eq!(
            second_page.page.items[0].occurrence.evidence,
            "equal to second adoption"
        );
        assert_eq!(second_page.skipped_invalid_timestamps, 2);

        let third_page = store
            .list_recurrences(PageRequest {
                offset: 2,
                limit: 1,
            })
            .expect("read third recurrence page");
        assert_eq!(third_page.page.total, 3);
        assert!(!third_page.page.truncated);
        assert_eq!(third_page.page.items[0].adoption_id, second.id);
        assert_eq!(
            third_page.page.items[0].occurrence.evidence,
            "after second adoption"
        );
        assert_eq!(third_page.skipped_invalid_timestamps, 2);
    }

    #[test]
    fn add_and_append_capture_cwd_git_context_and_global_scope() {
        let temp = tempfile::tempdir().expect("tempdir");
        let store_dir = temp.path().join("global-store");
        let outside_cwd = temp.path().join("outside-cwd");
        fs::create_dir(&outside_cwd).expect("create outside cwd");
        let (repo_root, head_sha) = create_committed_repository(&temp.path().join("repo"));
        let mut store = Store::open(&store_dir).expect("open store");

        let outside = store
            .add_friction(FrictionAddRequest {
                mode: FrictionAddMode::Create {
                    source: "varde-change orchestrate".to_owned(),
                    title: "Outside Git context".to_owned(),
                    target: None,
                    global: false,
                },
                evidence: "the store default surprised me".to_owned(),
                cwd: outside_cwd.clone(),
            })
            .expect("create outside-Git item");
        assert_eq!(outside.repo_root, None);

        let appended = store
            .add_friction(FrictionAddRequest {
                mode: FrictionAddMode::Append {
                    item_id: outside.id,
                },
                evidence: "the same friction occurred in the repository".to_owned(),
                cwd: repo_root.clone(),
            })
            .expect("append occurrence");
        assert_eq!(appended.id, outside.id);
        assert_eq!(appended.repo_root, None);

        let local = store
            .add_friction(FrictionAddRequest {
                mode: FrictionAddMode::Create {
                    source: "tool".to_owned(),
                    title: "Repository scoped friction".to_owned(),
                    target: Some("learn-cli/src/store.rs".to_owned()),
                    global: false,
                },
                evidence: "local evidence".to_owned(),
                cwd: repo_root.clone(),
            })
            .expect("create repository item");
        assert_eq!(
            local.repo_root.as_deref(),
            Some(repo_root.to_str().unwrap())
        );

        let global = store
            .add_friction(FrictionAddRequest {
                mode: FrictionAddMode::Create {
                    source: "skill".to_owned(),
                    title: "Global item with local occurrence".to_owned(),
                    target: None,
                    global: true,
                },
                evidence: "global evidence".to_owned(),
                cwd: repo_root.clone(),
            })
            .expect("create global item");
        assert_eq!(global.repo_root, None);

        let item_count: i64 = store
            .connection
            .query_row("SELECT COUNT(*) FROM items", [], |row| row.get(0))
            .expect("count items");
        let occurrence_count: i64 = store
            .connection
            .query_row("SELECT COUNT(*) FROM occurrences", [], |row| row.get(0))
            .expect("count occurrences");
        assert_eq!(item_count, 3);
        assert_eq!(occurrence_count, 4);

        let rows = {
            let mut statement = store
                .connection
                .prepare(
                    "SELECT cwd, repo_root, head_sha, evidence
                     FROM occurrences WHERE item_id = ?1 ORDER BY id",
                )
                .expect("prepare occurrence query");
            statement
                .query_map([outside.id], |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, Option<String>>(1)?,
                        row.get::<_, Option<String>>(2)?,
                        row.get::<_, String>(3)?,
                    ))
                })
                .expect("query occurrences")
                .collect::<Result<Vec<_>, _>>()
                .expect("collect occurrences")
        };
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].0, outside_cwd.to_string_lossy());
        assert_eq!(rows[0].1, None);
        assert_eq!(rows[0].2, None);
        assert_eq!(rows[1].0, repo_root.to_string_lossy());
        assert_eq!(rows[1].1.as_deref(), Some(repo_root.to_str().unwrap()));
        assert_eq!(rows[1].2.as_deref(), Some(head_sha.as_str()));

        let global_context: (Option<String>, Option<String>) = store
            .connection
            .query_row(
                "SELECT repo_root, head_sha FROM occurrences WHERE item_id = ?1",
                [global.id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .expect("read global occurrence context");
        assert_eq!(
            global_context.0.as_deref(),
            Some(repo_root.to_str().unwrap())
        );
        assert_eq!(global_context.1.as_deref(), Some(head_sha.as_str()));
    }

    #[test]
    fn show_and_list_page_history_and_preserve_removed_repository_scopes() {
        let temp = tempfile::tempdir().expect("tempdir");
        let cwd = temp.path().join("cwd");
        fs::create_dir(&cwd).expect("create cwd");
        let removed_repo = temp.path().join("deleted-project");
        fs::create_dir(&removed_repo).expect("create repository before removal");
        let removed_repo = removed_repo.canonicalize().expect("canonical removed path");
        fs::remove_dir(&removed_repo).expect("remove historical repository");
        let mut store = Store::open(&temp.path().join("store")).expect("open store");
        let item_event = fixture_item(
            0,
            "Search fallback",
            Some(removed_repo.to_string_lossy().into_owned()),
        );
        append_fixture(
            &mut store,
            &[
                item_event.clone(),
                fixture_occurrence(
                    1,
                    &item_event,
                    "2026-01-01T00:00:00Z",
                    "First matching evidence",
                ),
                fixture_occurrence(
                    2,
                    &item_event,
                    "2026-01-01T00:00:01Z",
                    "Second matching evidence",
                ),
                fixture_status(
                    3,
                    &item_event,
                    "2026-01-01T00:00:00Z",
                    ("open", "resolved"),
                    "first reason",
                ),
                fixture_status(
                    4,
                    &item_event,
                    "2026-01-02T00:00:00Z",
                    ("resolved", "open"),
                    "second reason",
                ),
            ],
        );
        let item = get_item(
            &store.connection,
            fixture_item_id(&store, &item_event),
            &store.database_path,
        )
        .expect("read fixture item");
        let stored_scope: String = store
            .connection
            .query_row(
                "SELECT repo_root FROM items WHERE id = ?1",
                [item.id],
                |row| row.get(0),
            )
            .expect("read historical scope");
        assert_eq!(stored_scope, removed_repo.to_string_lossy());
        assert_eq!(normalize_scope_path(&removed_repo, &cwd), removed_repo);

        let first = store
            .show_friction(
                &item.id.to_string(),
                PageRequest {
                    offset: 0,
                    limit: 1,
                },
            )
            .expect("read first show page");
        assert_eq!(first.item.status, "open");
        assert_eq!(first.occurrences.total, 2);
        assert_eq!(first.status_changes.total, 2);
        assert_eq!(first.occurrences.items.len(), 1);
        assert_eq!(first.status_changes.items[0].reason, "first reason");
        assert!(first.occurrences.truncated);
        assert!(first.status_changes.truncated);
        assert_eq!(first.occurrences.next_offset, Some(1));
        assert_eq!(first.status_changes.next_offset, Some(1));

        let second = store
            .show_friction(
                &item.slug,
                PageRequest {
                    offset: 1,
                    limit: 1,
                },
            )
            .expect("read second show page by slug");
        assert_eq!(
            second.occurrences.items[0].evidence,
            "Second matching evidence"
        );
        assert_eq!(second.status_changes.items[0].reason, "second reason");
        assert!(!second.occurrences.truncated);
        assert!(!second.status_changes.truncated);

        let filtered = store
            .list_items(&FrictionListRequest {
                status: Some(FrictionStatus::Open),
                source: Some("varde learn test".to_owned()),
                repo_root: Some(removed_repo.clone()),
                global: false,
                text: Some("FIRST MATCHING".to_owned()),
                cwd,
                page: PageRequest::default(),
            })
            .expect("filter historical repository item");
        assert_eq!(filtered.total, 1);
        assert_eq!(filtered.items[0].id, item.id);
    }

    #[test]
    fn export_snapshot_includes_history_beyond_page_limits() {
        let temp = tempfile::tempdir().expect("tempdir");
        let cwd = temp.path().join("cwd");
        fs::create_dir(&cwd).expect("create cwd");
        let mut store = Store::open(&temp.path().join("store")).expect("open store");
        let item_event = fixture_item(0, "Large history", None);
        let mut events = vec![
            item_event.clone(),
            fixture_occurrence(1, &item_event, "2026-01-01T00:00:00Z", "initial evidence"),
        ];
        for index in 0..=MAX_PAGE_LIMIT {
            let at = format!("2026-01-01T00:00:{index:04}Z");
            events.push(fixture_occurrence(
                2 + 2 * index,
                &item_event,
                &at,
                &format!("evidence-{index}"),
            ));
            events.push(fixture_status(
                3 + 2 * index,
                &item_event,
                &at,
                ("open", "resolved"),
                &format!("reason-{index}"),
            ));
        }
        append_fixture(&mut store, &events);

        let exports = store.export_items().expect("read export snapshot");
        assert_eq!(exports.len(), 1);
        assert_eq!(exports[0].occurrences.len(), MAX_PAGE_LIMIT + 2);
        assert_eq!(exports[0].status_changes.len(), MAX_PAGE_LIMIT + 1);
        assert_eq!(
            exports[0].occurrences.last().unwrap().evidence,
            "evidence-1000"
        );
        assert_eq!(
            exports[0].status_changes.last().unwrap().reason,
            "reason-1000"
        );
    }
}
