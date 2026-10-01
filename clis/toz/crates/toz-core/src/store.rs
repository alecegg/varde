//! SQLite store: captures, chunks, two FTS5 indexes, stats log, retention.

use crate::chunk::Chunk;
use crate::config::Retention;
use crate::redact::Redactor;
use anyhow::{Context, Result};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const SCHEMA_VERSION: i64 = 4;

const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS captures (
  id INTEGER PRIMARY KEY,
  handle TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  kind TEXT NOT NULL,
  source TEXT NOT NULL,
  source_key TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  exit_code INTEGER,
  created_at INTEGER NOT NULL,
  session TEXT,
  superseded_by INTEGER REFERENCES captures(id) ON DELETE SET NULL,
  file_mtime INTEGER,
  file_hash BLOB,
  redactions INTEGER NOT NULL DEFAULT 0,
  binary INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'completed',
  indexed INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS captures_source_key ON captures(source_key, created_at);
CREATE INDEX IF NOT EXISTS captures_created ON captures(created_at);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  stream TEXT NOT NULL DEFAULT 'stdout',
  title TEXT NOT NULL,
  line_start INTEGER NOT NULL,
  line_end INTEGER NOT NULL,
  content_type TEXT NOT NULL,
  body TEXT NOT NULL,
  indexed INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS chunks_capture ON chunks(capture_id, ordinal);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_porter USING fts5(
  title, body, content='chunks', content_rowid='id', tokenize='porter unicode61'
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_trigram USING fts5(
  title, body, content='chunks', content_rowid='id', tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks
WHEN new.indexed = 1 BEGIN
  INSERT INTO chunks_porter(rowid, title, body) VALUES (new.id, new.title, new.body);
  INSERT INTO chunks_trigram(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks
WHEN old.indexed = 1 BEGIN
  INSERT INTO chunks_porter(chunks_porter, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
  INSERT INTO chunks_trigram(chunks_trigram, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
END;

CREATE TABLE IF NOT EXISTS stats_log (
  id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL,
  kind TEXT NOT NULL,
  bytes_in INTEGER NOT NULL,
  bytes_out INTEGER NOT NULL,
  session TEXT
);
CREATE INDEX IF NOT EXISTS stats_ts ON stats_log(ts);

CREATE TABLE IF NOT EXISTS query_log (
  id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL,
  kind TEXT NOT NULL,
  bytes_out INTEGER NOT NULL,
  session TEXT,
  outcome TEXT NOT NULL DEFAULT 'ok',
  details_json TEXT
);
CREATE INDEX IF NOT EXISTS query_ts ON query_log(ts);

CREATE TABLE IF NOT EXISTS capture_records (
  id INTEGER PRIMARY KEY,
  capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  seq INTEGER NOT NULL,
  json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS capture_records_lookup ON capture_records(capture_id, kind, seq);

CREATE TABLE IF NOT EXISTS profile_diagnostics (
  id INTEGER PRIMARY KEY,
  capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
  profile_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS profile_diagnostics_created ON profile_diagnostics(created_at);
"#;

// varde-ignore-next-line fat-interface -- internal SQLite facade keeps one connection and transaction owner; callers use focused methods
pub struct Store {
    conn: Connection,
    path: PathBuf,
    live_locks: HashMap<String, File>,
}

impl Store {
    /// Path of this project's open database, including a selected fallback location.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Rewrite old plaintext capture metadata without changing capture data or handles.
    pub fn migrate_legacy_metadata(&mut self, redactor: &Redactor) -> Result<usize> {
        let key_dir = self.path.parent().unwrap_or_else(|| Path::new("."));
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let rows = {
            let mut stmt = tx.prepare("SELECT id, label, source, source_key FROM captures")?;
            let found = stmt
                .query_map([], |row| {
                    Ok((
                        row.get::<_, i64>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                    ))
                })?
                .collect::<std::result::Result<Vec<_>, _>>()?;
            found
        };
        let mut changed = 0;
        for (id, label, source, source_key) in rows {
            // A legacy plaintext key can itself be 64 lowercase hex characters. Check
            // the unsanitized display fields for its origin before treating it as keyed.
            let hex_key = source_key.len() == 64
                && source_key
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b));
            let safe_key = if source_key.is_empty() {
                source_key.clone()
            } else if hex_key {
                let label_candidate = label.trim();
                let source_candidate = crate::capture::source_key(&source);
                let candidates = [label_candidate, source_candidate.as_str()];
                let mut already_keyed = false;
                for candidate in candidates {
                    if !candidate.is_empty()
                        && crate::metadata::identity_at(key_dir, candidate)? == source_key
                    {
                        already_keyed = true;
                        break;
                    }
                }
                if already_keyed || !candidates.contains(&source_key.as_str()) {
                    source_key.clone()
                } else {
                    crate::metadata::identity_at(key_dir, &source_key)?
                }
            } else {
                crate::metadata::identity_at(key_dir, &source_key)?
            };
            let safe_label = crate::metadata::sanitize_text(redactor, &label);
            let safe_source = crate::metadata::sanitize_text(redactor, &source);
            if safe_key != source_key || safe_label != label || safe_source != source {
                tx.execute(
                    "UPDATE captures SET label = ?1, source = ?2, source_key = ?3 WHERE id = ?4",
                    params![safe_label, safe_source, safe_key, id],
                )?;
                changed += 1;
            }
        }
        tx.commit()?;

        // UPDATE leaves prior values in database pages and WAL frames. Compact outside the
        // transaction, then require a complete checkpoint so the WAL retains no old frames.
        self.conn.execute_batch("VACUUM")?;
        let (busy, _, _): (i64, i64, i64) =
            self.conn
                .query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |row| {
                    Ok((row.get(0)?, row.get(1)?, row.get(2)?))
                })?;
        anyhow::ensure!(busy == 0, "metadata migration WAL checkpoint was busy");
        Ok(changed)
    }
}

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct KindStats {
    pub kind: String,
    pub captures: i64,
    pub bytes_in: i64,
    pub bytes_out: i64,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct QueryKindStats {
    pub kind: String,
    pub queries: i64,
    pub bytes_out: i64,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct QueryEvent {
    pub id: i64,
    pub ts: i64,
    pub kind: String,
    pub bytes_out: i64,
    pub session: Option<String>,
    pub outcome: String,
    pub details: serde_json::Value,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Stats {
    pub captures: i64,
    /// Bytes that would have entered the context window.
    pub bytes_in: i64,
    /// Bytes of preview actually emitted.
    pub bytes_out: i64,
    pub by_kind: Vec<KindStats>,
    pub queries: i64,
    pub query_bytes: i64,
    pub by_query_kind: Vec<QueryKindStats>,
    pub net_saved_bytes: i64,
    /// Captures currently in the store (not just the window).
    pub stored_captures: i64,
    pub db_bytes: i64,
}

#[derive(Debug, Clone)]
pub struct NewCapture<'a> {
    pub label: &'a str,
    pub kind: &'a str,
    pub source: &'a str,
    pub source_key: &'a str,
    /// Previous plaintext key, used only to supersede captures written before metadata hashing.
    pub legacy_source_key: Option<&'a str>,
    pub bytes: usize,
    pub exit_code: Option<i32>,
    pub session: Option<&'a str>,
    pub redactions: usize,
    pub binary: bool,
    pub file_mtime: Option<i64>,
    pub file_hash: Option<&'a [u8]>,
}

#[derive(Debug, Clone)]
pub struct CaptureRow {
    pub id: i64,
    pub handle: String,
    pub label: String,
    pub kind: String,
    pub source: String,
    pub bytes: i64,
    pub exit_code: Option<i32>,
    pub created_at: i64,
    pub session: Option<String>,
    pub superseded_by: Option<i64>,
    pub redactions: i64,
    pub binary: bool,
    pub chunk_count: i64,
    pub file_mtime: Option<i64>,
    pub file_hash: Option<Vec<u8>>,
    pub state: String,
}

#[derive(Debug, Clone)]
pub struct ChunkRow {
    pub id: i64,
    pub ordinal: i64,
    pub stream: String,
    pub title: String,
    pub line_start: i64,
    pub line_end: i64,
    pub content_type: String,
    pub body: String,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct ProfileDiagnosticRow {
    pub profile_id: String,
    pub reason: String,
    pub created_at: i64,
}

/// Best-effort chmod; the store still works if it fails (e.g. exotic filesystems).
fn restrict_perms(path: &Path, mode: u32) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode));
    }
    #[cfg(not(unix))]
    let _ = (path, mode);
}

pub fn now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn open_initialized_connection(path: &Path) -> Result<Connection> {
    let conn = Connection::open(path).with_context(|| format!("opening {}", path.display()))?;
    conn.busy_timeout(Duration::from_secs(30))?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "synchronous", "NORMAL")?;
    conn.pragma_update(None, "foreign_keys", "ON")?;
    conn.execute_batch(SCHEMA).context("applying schema")?;
    if !has_column(&conn, "captures", "state")? {
        conn.execute(
            "ALTER TABLE captures ADD COLUMN state TEXT NOT NULL DEFAULT 'completed'",
            [],
        )?;
    }
    if !has_column(&conn, "query_log", "outcome")? {
        conn.execute(
            "ALTER TABLE query_log ADD COLUMN outcome TEXT NOT NULL DEFAULT 'ok'",
            [],
        )?;
    }
    if !has_column(&conn, "query_log", "details_json")? {
        conn.execute("ALTER TABLE query_log ADD COLUMN details_json TEXT", [])?;
    }
    ensure_conditional_fts_triggers(&conn)?;
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?1)",
        params![SCHEMA_VERSION.to_string()],
    )?;
    conn.execute(
        "UPDATE meta SET value = ?1 WHERE key = 'schema_version'",
        params![SCHEMA_VERSION.to_string()],
    )?;
    Ok(conn)
}

fn has_column(conn: &Connection, table: &str, column: &str) -> Result<bool> {
    let sql = format!("SELECT EXISTS(SELECT 1 FROM pragma_table_info('{table}') WHERE name = ?1)");
    Ok(conn.query_row(&sql, [column], |row| row.get(0))?)
}

fn trigger_is_current(conn: &Connection, name: &str, condition: &str) -> Result<bool> {
    let sql: Option<String> = conn
        .query_row(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?1",
            [name],
            |row| row.get(0),
        )
        .optional()?;
    Ok(sql.as_deref().is_some_and(|sql| sql.contains(condition)))
}

fn ensure_conditional_fts_triggers(conn: &Connection) -> Result<()> {
    let has_indexed = has_column(conn, "captures", "indexed")?;
    let has_chunk_indexed = has_column(conn, "chunks", "indexed")?;
    let insert_trigger_current = trigger_is_current(conn, "chunks_ai", "WHEN new.indexed = 1")?;
    let delete_trigger_current = trigger_is_current(conn, "chunks_ad", "WHEN old.indexed = 1")?;
    let triggers_current = insert_trigger_current && delete_trigger_current;
    if has_indexed && has_chunk_indexed && triggers_current {
        return Ok(());
    }
    conn.execute_batch("BEGIN IMMEDIATE")?;
    if !has_indexed {
        conn.execute(
            "ALTER TABLE captures ADD COLUMN indexed INTEGER NOT NULL DEFAULT 1",
            [],
        )?;
    }
    if !has_chunk_indexed {
        conn.execute(
            "ALTER TABLE chunks ADD COLUMN indexed INTEGER NOT NULL DEFAULT 1",
            [],
        )?;
    }
    conn.execute_batch("DROP TRIGGER IF EXISTS chunks_ai; DROP TRIGGER IF EXISTS chunks_ad;")?;
    conn.execute_batch(
        "CREATE TRIGGER chunks_ai AFTER INSERT ON chunks
         WHEN new.indexed = 1 BEGIN
           INSERT INTO chunks_porter(rowid, title, body) VALUES (new.id, new.title, new.body);
           INSERT INTO chunks_trigram(rowid, title, body) VALUES (new.id, new.title, new.body);
         END;
         CREATE TRIGGER chunks_ad AFTER DELETE ON chunks
         WHEN old.indexed = 1 BEGIN
           INSERT INTO chunks_porter(chunks_porter, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
           INSERT INTO chunks_trigram(chunks_trigram, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
         END;",
    )?;
    conn.execute_batch("COMMIT")?;
    Ok(())
}

fn insert_capture_row(
    tx: &rusqlite::Transaction<'_>,
    handle: &str,
    cap: &NewCapture<'_>,
    indexed: bool,
) -> Result<()> {
    tx.execute(
        "INSERT INTO captures(handle, label, kind, source, source_key, bytes, exit_code, created_at,
                              session, redactions, binary, file_mtime, file_hash, indexed)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)",
        params![
            handle,
            cap.label,
            cap.kind,
            cap.source,
            cap.source_key,
            cap.bytes as i64,
            cap.exit_code,
            now(),
            cap.session,
            cap.redactions as i64,
            cap.binary as i64,
            cap.file_mtime,
            cap.file_hash,
            indexed as i64,
        ],
    )?;
    Ok(())
}

fn insert_capture_chunks(
    tx: &rusqlite::Transaction<'_>,
    id: i64,
    indexed: bool,
    produce: impl FnOnce(&mut dyn FnMut(&str, &Chunk) -> Result<()>) -> Result<usize>,
) -> Result<usize> {
    let mut stmt = tx.prepare(
        "INSERT INTO chunks(capture_id, ordinal, stream, title, line_start, line_end, content_type, body, indexed)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
    )?;
    let mut i = 0;
    produce(&mut |stream, c| {
        stmt.execute(params![
            id,
            i as i64,
            stream,
            c.title,
            c.line_start as i64,
            c.line_end as i64,
            c.content_type.as_str(),
            c.body,
            indexed as i64,
        ])?;
        i += 1;
        Ok(())
    })
}

impl Store {
    pub fn access_error(error: &anyhow::Error) -> bool {
        error.chain().any(|cause| {
            if let Some(e) = cause.downcast_ref::<std::io::Error>() {
                return matches!(e.kind(), std::io::ErrorKind::PermissionDenied | std::io::ErrorKind::NotADirectory | std::io::ErrorKind::ReadOnlyFilesystem);
            }
            matches!(cause.downcast_ref::<rusqlite::Error>(),
                Some(rusqlite::Error::SqliteFailure(e, _)) if matches!(e.code,
                    rusqlite::ErrorCode::CannotOpen | rusqlite::ErrorCode::ReadOnly | rusqlite::ErrorCode::PermissionDenied))
        })
    }

    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("creating {}", parent.display()))?;
            restrict_perms(parent, 0o700);
        }
        let existed = path.exists();
        let init_lock_path = path.with_extension("db.init.lock");
        let init_lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&init_lock_path)
            .with_context(|| format!("opening {}", init_lock_path.display()))?;
        restrict_perms(&init_lock_path, 0o600);
        init_lock
            .lock()
            .with_context(|| format!("locking {}", init_lock_path.display()))?;
        let conn = retry_busy(|| open_initialized_connection(path))?;
        if !existed {
            // The store holds raw command output; keep it private to the user.
            restrict_perms(path, 0o600);
        }
        let mut store = Self {
            conn,
            path: path.to_path_buf(),
            live_locks: HashMap::new(),
        };
        store.recover_stale_live_captures()?;
        Ok(store)
    }

    pub fn open_readonly(path: &Path) -> Result<Self> {
        let conn = Connection::open_with_flags(
            path,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .with_context(|| format!("opening {}", path.display()))?;
        conn.busy_timeout(Duration::from_secs(30))?;
        Ok(Self {
            conn,
            path: path.to_path_buf(),
            live_locks: HashMap::new(),
        })
    }

    pub fn conn(&self) -> &Connection {
        &self.conn
    }

    /// Populate both search indexes for captures that deliberately skipped indexing at insert.
    /// Chunk bodies remain the canonical data; this work is paid only by a term search.
    pub fn index_deferred(&mut self, handle: Option<&str>) -> Result<usize> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let mut ids = Vec::new();
        {
            let mut stmt = tx.prepare(
                "SELECT id FROM captures WHERE indexed = 0 AND (?1 IS NULL OR handle = ?1)",
            )?;
            let rows = stmt.query_map([handle], |r| r.get::<_, i64>(0))?;
            for row in rows {
                ids.push(row?);
            }
        }
        for id in &ids {
            tx.execute(
                "INSERT INTO chunks_porter(rowid, title, body)
                 SELECT id, title, body FROM chunks WHERE capture_id = ?1",
                params![id],
            )?;
            tx.execute(
                "INSERT INTO chunks_trigram(rowid, title, body)
                 SELECT id, title, body FROM chunks WHERE capture_id = ?1",
                params![id],
            )?;
            tx.execute(
                "UPDATE chunks SET indexed = 1 WHERE capture_id = ?1",
                params![id],
            )?;
            tx.execute("UPDATE captures SET indexed = 1 WHERE id = ?1", params![id])?;
        }
        tx.commit()?;
        Ok(ids.len())
    }

    /// Whether a read-only search would omit captures awaiting indexing.
    pub fn has_deferred(&self, handle: Option<&str>) -> Result<bool> {
        let has_column: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM pragma_table_info('captures') WHERE name = 'indexed')",
            [],
            |row| row.get(0),
        )?;
        if !has_column {
            return Ok(false);
        }
        Ok(self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM captures WHERE indexed = 0 AND (?1 IS NULL OR handle = ?1))",
            [handle],
            |row| row.get(0),
        )?)
    }

    /// Insert a capture with its chunks; supersede older captures with the same source key.
    /// Returns the new handle.
    pub fn insert_capture(
        &mut self,
        cap: &NewCapture,
        chunks: &[(String, Chunk)],
    ) -> Result<String> {
        self.insert_capture_indexed(cap, chunks, true)
    }

    pub fn insert_capture_indexed(
        &mut self,
        cap: &NewCapture,
        chunks: &[(String, Chunk)],
        indexed: bool,
    ) -> Result<String> {
        self.insert_capture_with_indexed(cap, indexed, |append| {
            for (stream, chunk) in chunks {
                append(stream, chunk)?;
            }
            Ok(cap.redactions)
        })
    }

    /// Ingest bounded chunks in one transaction. Errors roll back supersession too.
    pub fn insert_capture_with(
        &mut self,
        cap: &NewCapture,
        produce: impl FnOnce(&mut dyn FnMut(&str, &Chunk) -> Result<()>) -> Result<usize>,
    ) -> Result<String> {
        self.insert_capture_with_indexed(cap, true, produce)
    }

    fn insert_capture_with_indexed(
        &mut self,
        cap: &NewCapture,
        indexed: bool,
        produce: impl FnOnce(&mut dyn FnMut(&str, &Chunk) -> Result<()>) -> Result<usize>,
    ) -> Result<String> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let handle = fresh_handle(&tx)?;
        insert_capture_row(&tx, &handle, cap, indexed)?;
        let id = tx.last_insert_rowid();
        let redactions = insert_capture_chunks(&tx, id, indexed, produce)?;
        tx.execute(
            "UPDATE captures SET redactions = ?1 WHERE id = ?2",
            params![redactions as i64, id],
        )?;
        if !cap.source_key.is_empty() {
            tx.execute(
                "UPDATE captures SET superseded_by = ?1
                 WHERE (source_key = ?2 OR source_key = ?3)
                   AND id != ?1 AND superseded_by IS NULL",
                params![id, cap.source_key, cap.legacy_source_key],
            )?;
        }
        tx.commit()?;
        Ok(handle)
    }

    /// Reserve a capture handle before a live command starts producing output.
    pub fn reserve_live_capture(&mut self, cap: &NewCapture) -> Result<String> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let handle = fresh_handle(&tx)?;
        let lock_path = live_lock_path(&self.path, &handle);
        let live_lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
            .with_context(|| format!("opening {}", lock_path.display()))?;
        restrict_perms(&lock_path, 0o600);
        live_lock
            .lock()
            .with_context(|| format!("locking {}", lock_path.display()))?;
        tx.execute(
            "INSERT INTO captures(handle, label, kind, source, source_key, bytes, exit_code, created_at,
                                  session, redactions, binary, file_mtime, file_hash, state)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, 'running')",
            params![
                handle,
                cap.label,
                cap.kind,
                cap.source,
                cap.source_key,
                cap.bytes as i64,
                cap.exit_code,
                now(),
                cap.session,
                cap.redactions as i64,
                cap.binary as i64,
                cap.file_mtime,
                cap.file_hash,
            ],
        )?;
        tx.commit()?;
        self.live_locks.insert(handle.clone(), live_lock);
        Ok(handle)
    }

    /// Append one already chunked live-output section and commit it immediately.
    pub fn append_live_chunk(
        &mut self,
        handle: &str,
        stream: &str,
        chunk: &Chunk,
        bytes: usize,
        redactions: usize,
    ) -> Result<()> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let capture_id: i64 = tx.query_row(
            "SELECT id FROM captures WHERE handle = ?1 AND state = 'running'",
            params![handle],
            |r| r.get(0),
        )?;
        let ordinal: i64 = tx.query_row(
            "SELECT COALESCE(MAX(ordinal) + 1, 0) FROM chunks WHERE capture_id = ?1",
            params![capture_id],
            |r| r.get(0),
        )?;
        tx.execute(
            "INSERT INTO chunks(capture_id, ordinal, stream, title, line_start, line_end, content_type, body)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                capture_id,
                ordinal,
                stream,
                chunk.title,
                chunk.line_start as i64,
                chunk.line_end as i64,
                chunk.content_type.as_str(),
                chunk.body,
            ],
        )?;
        tx.execute(
            "UPDATE captures SET bytes = bytes + ?1, redactions = redactions + ?2 WHERE id = ?3",
            params![bytes as i64, redactions as i64, capture_id],
        )?;
        tx.commit()?;
        Ok(())
    }

    /// Mark an incremental capture complete and publish its final status.
    pub fn finish_live_capture(
        &mut self,
        handle: &str,
        bytes: usize,
        exit_code: i32,
        redactions: usize,
    ) -> Result<()> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let (id, source_key): (i64, String) = tx.query_row(
            "SELECT id, source_key FROM captures WHERE handle = ?1 AND state = 'running'",
            params![handle],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )?;
        let changed = tx.execute(
            "UPDATE captures
             SET state = 'completed', bytes = ?1, exit_code = ?2, redactions = ?3
             WHERE handle = ?4 AND state = 'running'",
            params![bytes as i64, exit_code, redactions as i64, handle],
        )?;
        anyhow::ensure!(changed == 1, "live capture {handle} is not running");
        if !source_key.is_empty() {
            tx.execute(
                "UPDATE captures SET superseded_by = ?1
                 WHERE source_key = ?2 AND id != ?1 AND superseded_by IS NULL
                   AND state != 'running'",
                params![id, source_key],
            )?;
        }
        tx.commit()?;
        self.release_live_lock(handle);
        Ok(())
    }

    /// Remove a live reservation after startup or ingestion fails.
    pub fn cancel_live_capture(&mut self, handle: &str) -> Result<()> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let id: Option<i64> = tx
            .query_row(
                "SELECT id FROM captures WHERE handle = ?1 AND state = 'running'",
                params![handle],
                |row| row.get(0),
            )
            .optional()?;
        if let Some(id) = id {
            tx.execute(
                "UPDATE captures SET superseded_by = NULL WHERE superseded_by = ?1",
                params![id],
            )?;
        }
        tx.execute(
            "DELETE FROM captures WHERE handle = ?1 AND state = 'running'",
            params![handle],
        )?;
        tx.commit()?;
        self.release_live_lock(handle);
        Ok(())
    }

    pub fn log_stats(
        &self,
        kind: &str,
        bytes_in: usize,
        bytes_out: usize,
        session: Option<&str>,
    ) -> Result<()> {
        self.conn.execute(
            "INSERT INTO stats_log(ts, kind, bytes_in, bytes_out, session) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![now(), kind, bytes_in as i64, bytes_out as i64, session],
        )?;
        Ok(())
    }

    pub fn log_query(
        &self,
        kind: &str,
        bytes_out: usize,
        session: Option<&str>,
        outcome: &str,
        details: &serde_json::Value,
    ) -> Result<()> {
        self.conn.execute(
            "INSERT INTO query_log(ts, kind, bytes_out, session, outcome, details_json) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![now(), kind, bytes_out as i64, session, outcome, serde_json::to_string(details)?],
        )?;
        Ok(())
    }

    pub fn query_events(
        &self,
        session: Option<&str>,
        since: Option<i64>,
        limit: usize,
    ) -> Result<Vec<QueryEvent>> {
        let exists: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'query_log')",
            [],
            |r| r.get(0),
        )?;
        if !exists {
            return Ok(Vec::new());
        }
        let outcome = if has_column(&self.conn, "query_log", "outcome")? {
            "outcome"
        } else {
            "'ok'"
        };
        let details = if has_column(&self.conn, "query_log", "details_json")? {
            "details_json"
        } else {
            "NULL"
        };
        let mut stmt = self.conn.prepare(&format!(
            "SELECT id, ts, kind, bytes_out, session, {outcome}, {details}
             FROM query_log WHERE (?1 IS NULL OR session = ?1) AND (?2 IS NULL OR ts >= ?2)
             ORDER BY ts DESC, id DESC LIMIT ?3"
        ))?;
        let rows = stmt.query_map(params![session, since, limit as i64], |r| {
            let details: Option<String> = r.get(6)?;
            let details = details
                .as_deref()
                .and_then(|s| serde_json::from_str(s).ok())
                .unwrap_or(serde_json::Value::Null);
            Ok(QueryEvent {
                id: r.get(0)?,
                ts: r.get(1)?,
                kind: r.get(2)?,
                bytes_out: r.get(3)?,
                session: r.get(4)?,
                outcome: r.get(5)?,
                details,
            })
        })?;
        Ok(rows.collect::<std::result::Result<Vec<_>, _>>()?)
    }

    pub fn get_by_handle(&self, handle: &str) -> Result<Option<CaptureRow>> {
        self.conn
            .query_row(
                &format!("{CAPTURE_SELECT} WHERE c.handle = ?1"),
                params![handle],
                map_capture,
            )
            .optional()
            .map_err(Into::into)
    }

    pub fn list(&self, limit: usize, include_superseded: bool) -> Result<Vec<CaptureRow>> {
        let filter = if include_superseded {
            ""
        } else {
            "WHERE c.superseded_by IS NULL"
        };
        let sql =
            format!("{CAPTURE_SELECT} {filter} ORDER BY c.created_at DESC, c.id DESC LIMIT ?1");
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt.query_map(params![limit as i64], map_capture)?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(Into::into)
    }

    pub fn chunks_for(&self, capture_id: i64) -> Result<Vec<ChunkRow>> {
        let mut stmt = self.conn.prepare(
            "SELECT id, ordinal, stream, title, line_start, line_end, content_type, body
             FROM chunks WHERE capture_id = ?1 ORDER BY ordinal",
        )?;
        let rows = stmt.query_map(params![capture_id], |r| {
            Ok(ChunkRow {
                id: r.get(0)?,
                ordinal: r.get(1)?,
                stream: r.get(2)?,
                title: r.get(3)?,
                line_start: r.get(4)?,
                line_end: r.get(5)?,
                content_type: r.get(6)?,
                body: r.get(7)?,
            })
        })?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(Into::into)
    }

    /// Reassemble the full text of one stream from its chunks (overlap-aware).
    pub fn full_text(&self, capture_id: i64, stream: &str) -> Result<String> {
        let chunks = self.chunks_for(capture_id)?;
        let mut lines: Vec<String> = Vec::new();
        for c in chunks.iter().filter(|c| c.stream == stream) {
            let start = (c.line_start - 1) as usize;
            // Bodies join logical lines without a terminator. A trailing empty
            // segment is therefore a real blank line, not a removable newline.
            for (i, line) in c.body.split('\n').enumerate() {
                let idx = start + i;
                if idx < lines.len() {
                    continue; // overlap already present
                }
                lines.push(line.to_string());
            }
        }
        Ok(lines.join("\n"))
    }

    /// Highest line number recorded for a stream. Cheap metadata; does not read bodies.
    pub fn line_count(&self, capture_id: i64, stream: &str) -> Result<i64> {
        Ok(self.conn.query_row(
            "SELECT COALESCE(MAX(line_end), 0) FROM chunks WHERE capture_id = ?1 AND stream = ?2",
            params![capture_id, stream],
            |r| r.get(0),
        )?)
    }

    /// Persist a profile script's `toz.record()` calls for one capture, grouped by kind with
    /// `seq` numbering call order within each kind. Deleted with the capture (`ON DELETE CASCADE`).
    pub fn insert_records(&mut self, capture_id: i64, records: &[(String, String)]) -> Result<()> {
        let tx = self.conn.transaction()?;
        {
            let mut stmt = tx.prepare(
                "INSERT INTO capture_records(capture_id, kind, seq, json) VALUES (?1, ?2, ?3, ?4)",
            )?;
            let mut seq_by_kind: HashMap<&str, i64> = HashMap::new();
            for (kind, json) in records {
                let seq = seq_by_kind.entry(kind.as_str()).or_insert(0);
                stmt.execute(params![capture_id, kind, *seq, json])?;
                *seq += 1;
            }
        }
        tx.commit()?;
        Ok(())
    }

    /// One kind's records for a capture, in call order, as JSON strings (one `toz.record()` call
    /// each — the body of `toz query --records`).
    pub fn records_for(&self, capture_id: i64, kind: &str) -> Result<Vec<String>> {
        let mut stmt = self.conn.prepare(
            "SELECT json FROM capture_records WHERE capture_id = ?1 AND kind = ?2 ORDER BY seq",
        )?;
        let rows = stmt.query_map(params![capture_id, kind], |r| r.get::<_, String>(0))?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Persist a profile script failure (error, timeout, or a limit hit) so `toz doctor` can
    /// surface it; the capture itself already succeeded with its non-script preview.
    pub fn insert_profile_diagnostic(
        &mut self,
        capture_id: i64,
        profile_id: &str,
        reason: &str,
    ) -> Result<()> {
        self.conn.execute(
            "INSERT INTO profile_diagnostics(capture_id, profile_id, reason, created_at) VALUES (?1, ?2, ?3, ?4)",
            params![capture_id, profile_id, reason, now()],
        )?;
        Ok(())
    }

    /// Most recent profile script diagnostics across all captures, newest first.
    pub fn recent_profile_diagnostics(&self, limit: usize) -> Result<Vec<ProfileDiagnosticRow>> {
        let mut stmt = self.conn.prepare(
            "SELECT profile_id, reason, created_at FROM profile_diagnostics ORDER BY created_at DESC, id DESC LIMIT ?1",
        )?;
        let rows = stmt.query_map(params![limit as i64], |r| {
            Ok(ProfileDiagnosticRow {
                profile_id: r.get(0)?,
                reason: r.get(1)?,
                created_at: r.get(2)?,
            })
        })?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Stream one stream's logical lines without materialising the capture.
    ///
    /// `full_text` collects every chunk body, then every line, then joins: roughly 3x the capture
    /// resident at once. This walks the rusqlite cursor one chunk at a time instead, so peak
    /// memory is a single chunk body. The overlap rule is `full_text`'s, with a running counter
    /// standing in for `lines.len()`.
    pub fn for_each_line(
        &self,
        capture_id: i64,
        stream: &str,
        mut f: impl FnMut(&str) -> Result<()>,
    ) -> Result<()> {
        let mut stmt = self.conn.prepare(
            "SELECT line_start, body FROM chunks
             WHERE capture_id = ?1 AND stream = ?2 ORDER BY ordinal",
        )?;
        let mut rows = stmt.query(params![capture_id, stream])?;
        let mut emitted: usize = 0;
        while let Some(row) = rows.next()? {
            let line_start: i64 = row.get(0)?;
            let body: String = row.get(1)?;
            let start = (line_start - 1) as usize;
            for (i, line) in body.split('\n').enumerate() {
                if start + i < emitted {
                    continue; // overlap already emitted
                }
                f(line)?;
                emitted += 1;
            }
        }
        Ok(())
    }

    /// Hourly-gated prune per the retention policy. Returns number of captures removed.
    pub fn maybe_prune(&mut self, policy: &Retention) -> Result<usize> {
        let last: Option<String> = self
            .conn
            .query_row("SELECT value FROM meta WHERE key = 'last_prune'", [], |r| {
                r.get(0)
            })
            .optional()?;
        let last: i64 = last.and_then(|s| s.parse().ok()).unwrap_or(0);
        if now() - last < 3600 {
            return Ok(0);
        }
        let removed = self.prune(policy)?;
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('last_prune', ?1)",
            params![now().to_string()],
        )?;
        Ok(removed)
    }

    pub fn prune(&mut self, policy: &Retention) -> Result<usize> {
        let t = now();
        let mut removed = 0usize;
        removed += self.conn.execute(
            "DELETE FROM captures WHERE created_at < ?1 AND state != 'running'",
            params![t - (policy.days as i64) * 86400],
        )?;
        removed += self.conn.execute(
            "DELETE FROM captures
             WHERE superseded_by IS NOT NULL AND created_at < ?1 AND state != 'running'",
            params![t - (policy.superseded_days as i64) * 86400],
        )?;
        // Size backstop: evict oldest (superseded first) until under the cap.
        let cap_bytes = policy.max_mb.saturating_mul(1024 * 1024) as i64;
        loop {
            let size = self.db_used_size_bytes()?;
            if size <= cap_bytes {
                break;
            }
            let victim: Option<i64> = self
                .conn
                .query_row(
                    "SELECT id FROM captures
                     WHERE state != 'running'
                     ORDER BY (superseded_by IS NULL) ASC, created_at ASC LIMIT 1",
                    [],
                    |r| r.get(0),
                )
                .optional()?;
            match victim {
                Some(id) => {
                    self.conn
                        .execute("DELETE FROM captures WHERE id = ?1", params![id])?;
                    removed += 1;
                }
                None => break,
            }
        }
        let (page_size, page_count, freelist) = self.db_page_stats()?;
        let exceeds_cap = page_size.saturating_mul(page_count) > cap_bytes;
        let heavily_fragmented = page_count > 0 && freelist * 4 > page_count;
        if freelist > 0 && (exceeds_cap || heavily_fragmented) {
            self.conn.execute_batch("VACUUM")?;
        }
        Ok(removed)
    }

    /// Aggregate `stats_log`. `session` restricts to rows tagged with that session; otherwise
    /// `since` (unix secs) restricts by time; both `None` means all time.
    pub fn stats(&self, session: Option<&str>, since: Option<i64>) -> Result<Stats> {
        let (filter, arg): (&str, Box<dyn rusqlite::ToSql>) = match (session, since) {
            (Some(s), _) => ("session = ?1", Box::new(s.to_string())),
            (None, Some(t)) => ("ts >= ?1", Box::new(t)),
            (None, None) => ("?1 IS NULL", Box::new(rusqlite::types::Null)),
        };
        let mut stmt = self.conn.prepare(&format!(
            "SELECT kind, COUNT(*), COALESCE(SUM(bytes_in),0), COALESCE(SUM(bytes_out),0)
             FROM stats_log WHERE {filter} GROUP BY kind ORDER BY SUM(bytes_in) DESC"
        ))?;
        let by_kind: Vec<KindStats> = stmt
            .query_map([arg.as_ref()], |r| {
                Ok(KindStats {
                    kind: r.get(0)?,
                    captures: r.get(1)?,
                    bytes_in: r.get(2)?,
                    bytes_out: r.get(3)?,
                })
            })?
            .collect::<std::result::Result<_, _>>()?;
        let by_query_kind = if self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'query_log')",
            [],
            |r| r.get::<_, bool>(0),
        )? {
            let outcome_filter = if has_column(&self.conn, "query_log", "outcome")? {
                "AND outcome IN ('ok', 'partial', 'no_store')"
            } else {
                ""
            };
            let mut stmt = self.conn.prepare(&format!(
                "SELECT kind, COUNT(*), COALESCE(SUM(bytes_out),0)
                 FROM query_log WHERE {filter} {outcome_filter} GROUP BY kind ORDER BY SUM(bytes_out) DESC"
            ))?;
            let rows = stmt.query_map([arg.as_ref()], |r| {
                Ok(QueryKindStats {
                    kind: r.get(0)?,
                    queries: r.get(1)?,
                    bytes_out: r.get(2)?,
                })
            })?;
            rows.collect::<std::result::Result<Vec<_>, _>>()?
        } else {
            Vec::new()
        };
        let queries = by_query_kind.iter().map(|k| k.queries).sum();
        let query_bytes = by_query_kind.iter().map(|k| k.bytes_out).sum();
        let total = by_kind.iter().fold(KindStats::default(), |mut acc, k| {
            acc.captures += k.captures;
            acc.bytes_in += k.bytes_in;
            acc.bytes_out += k.bytes_out;
            acc
        });
        let stored: i64 = self
            .conn
            .query_row("SELECT COUNT(*) FROM captures", [], |r| r.get(0))?;
        Ok(Stats {
            captures: total.captures,
            bytes_in: total.bytes_in,
            bytes_out: total.bytes_out,
            by_kind,
            queries,
            query_bytes,
            by_query_kind,
            net_saved_bytes: total.bytes_in - total.bytes_out - query_bytes,
            stored_captures: stored,
            db_bytes: self.db_size_bytes()?,
        })
    }

    pub fn db_size_bytes(&self) -> Result<i64> {
        let page_size: i64 = self.conn.query_row("PRAGMA page_size", [], |r| r.get(0))?;
        let page_count: i64 = self.conn.query_row("PRAGMA page_count", [], |r| r.get(0))?;
        Ok(page_size * page_count)
    }

    fn db_used_size_bytes(&self) -> Result<i64> {
        let (page_size, page_count, freelist) = self.db_page_stats()?;
        Ok(page_size.saturating_mul(page_count.saturating_sub(freelist)))
    }

    fn db_page_stats(&self) -> Result<(i64, i64, i64)> {
        let page_size: i64 = self.conn.query_row("PRAGMA page_size", [], |r| r.get(0))?;
        let page_count: i64 = self.conn.query_row("PRAGMA page_count", [], |r| r.get(0))?;
        let freelist: i64 = self
            .conn
            .query_row("PRAGMA freelist_count", [], |r| r.get(0))?;
        Ok((page_size, page_count, freelist))
    }

    pub fn vacuum(&mut self) -> Result<()> {
        self.conn.execute_batch("VACUUM")?;
        Ok(())
    }

    pub fn delete_older_than(&mut self, seconds: i64) -> Result<usize> {
        Ok(self.conn.execute(
            "DELETE FROM captures WHERE created_at <= ?1 AND state != 'running'",
            params![now() - seconds],
        )?)
    }

    fn recover_stale_live_captures(&mut self) -> Result<()> {
        let handles = {
            let mut stmt = self
                .conn
                .prepare("SELECT id, handle FROM captures WHERE state = 'running'")?;
            let rows = stmt
                .query_map([], |row| {
                    Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?))
                })?
                .collect::<std::result::Result<Vec<_>, _>>()?;
            rows
        };
        for (id, handle) in handles {
            let lock_path = live_lock_path(&self.path, &handle);
            let lock = OpenOptions::new()
                .create(true)
                .truncate(false)
                .read(true)
                .write(true)
                .open(&lock_path)
                .with_context(|| format!("opening {}", lock_path.display()))?;
            match lock.try_lock() {
                Ok(()) => {
                    let tx = self
                        .conn
                        .transaction_with_behavior(TransactionBehavior::Immediate)?;
                    tx.execute(
                        "UPDATE captures SET superseded_by = NULL WHERE superseded_by = ?1",
                        params![id],
                    )?;
                    tx.execute(
                        "UPDATE captures SET state = 'interrupted'
                         WHERE id = ?1 AND state = 'running'",
                        params![id],
                    )?;
                    tx.commit()?;
                    drop(lock);
                    let _ = std::fs::remove_file(&lock_path);
                }
                Err(std::fs::TryLockError::WouldBlock) => {}
                Err(std::fs::TryLockError::Error(error)) => {
                    return Err(error).with_context(|| format!("locking {}", lock_path.display()));
                }
            }
        }
        Ok(())
    }

    fn release_live_lock(&mut self, handle: &str) {
        self.live_locks.remove(handle);
        let _ = std::fs::remove_file(live_lock_path(&self.path, handle));
    }
}

fn live_lock_path(db_path: &Path, handle: &str) -> PathBuf {
    db_path.with_file_name(format!("toz-live-{handle}.lock"))
}

fn retry_busy<T>(mut operation: impl FnMut() -> Result<T>) -> Result<T> {
    let deadline = Instant::now() + Duration::from_secs(30);
    let mut delay = Duration::from_millis(10);
    loop {
        match operation() {
            Ok(value) => return Ok(value),
            Err(error) if sqlite_busy(&error) && Instant::now() < deadline => {
                std::thread::sleep(delay);
                delay = (delay * 2).min(Duration::from_millis(250));
            }
            Err(error) => return Err(error),
        }
    }
}

fn sqlite_busy(error: &anyhow::Error) -> bool {
    error.chain().any(|cause| {
        matches!(
            cause.downcast_ref::<rusqlite::Error>(),
            Some(rusqlite::Error::SqliteFailure(error, _))
                if matches!(
                    error.code,
                    rusqlite::ErrorCode::DatabaseBusy | rusqlite::ErrorCode::DatabaseLocked
                )
        )
    })
}

const CAPTURE_SELECT: &str = "
    SELECT c.id, c.handle, c.label, c.kind, c.source, c.bytes, c.exit_code, c.created_at,
           c.session, c.superseded_by, c.redactions, c.binary,
           (SELECT COUNT(*) FROM chunks ch WHERE ch.capture_id = c.id) AS chunk_count,
           c.file_mtime, c.file_hash, c.state
    FROM captures c";

fn map_capture(r: &rusqlite::Row) -> rusqlite::Result<CaptureRow> {
    Ok(CaptureRow {
        id: r.get(0)?,
        handle: r.get(1)?,
        label: r.get(2)?,
        kind: r.get(3)?,
        source: r.get(4)?,
        bytes: r.get(5)?,
        exit_code: r.get(6)?,
        created_at: r.get(7)?,
        session: r.get(8)?,
        superseded_by: r.get(9)?,
        redactions: r.get(10)?,
        binary: r.get::<_, i64>(11)? != 0,
        chunk_count: r.get(12)?,
        file_mtime: r.get(13)?,
        file_hash: r.get(14)?,
        state: r.get(15)?,
    })
}

/// Handles are short lowercase alphanumerics (no `0/o/1/l` ambiguity). 4 chars, growing to 5+
/// if the store is crowded.
fn fresh_handle(conn: &Connection) -> Result<String> {
    const ALPHABET: &[u8] = b"abcdefghjkmnpqrstuvwxyz23456789";
    let mut len = 4;
    let mut attempts = 0;
    loop {
        let mut seed = crate::rand::next_u64();
        let mut h = String::with_capacity(len);
        for _ in 0..len {
            h.push(ALPHABET[(seed % ALPHABET.len() as u64) as usize] as char);
            seed /= ALPHABET.len() as u64;
        }
        let exists: bool = conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM captures WHERE handle = ?1)",
            params![h],
            |r| r.get(0),
        )?;
        if !exists {
            return Ok(h);
        }
        attempts += 1;
        if attempts % 8 == 0 {
            len += 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chunk::chunk_default;
    use crate::config::Redact;
    use crate::redact::Redactor;

    fn store() -> Store {
        let dir = std::env::temp_dir().join(format!("toz-test-{}", crate::rand::next_u64()));
        Store::open(&dir.join("toz.db")).unwrap()
    }

    #[test]
    fn query_events_read_and_upgrade_legacy_query_log() {
        let s = store();
        let path = s.path().to_path_buf();
        s.conn()
            .execute_batch(
                "DROP TABLE query_log;
                 CREATE TABLE query_log (
                   id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, kind TEXT NOT NULL,
                   bytes_out INTEGER NOT NULL, session TEXT
                 );
                 INSERT INTO query_log(ts, kind, bytes_out, session)
                   VALUES (1, 'chunk', 12, 'old-session');",
            )
            .unwrap();
        drop(s);

        let readonly = Store::open_readonly(&path).unwrap();
        let events = readonly
            .query_events(Some("old-session"), None, 10)
            .unwrap();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].outcome, "ok");
        assert!(events[0].details.is_null());
        assert_eq!(readonly.stats(None, None).unwrap().query_bytes, 12);
        drop(readonly);

        let upgraded = Store::open(&path).unwrap();
        upgraded
            .log_query(
                "lines",
                4,
                Some("new-session"),
                "ok",
                &serde_json::json!({"handle":"abc"}),
            )
            .unwrap();
        let events = upgraded.query_events(None, None, 10).unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].details["handle"], "abc");
        assert_eq!(upgraded.stats(None, None).unwrap().query_bytes, 16);
    }

    fn cap<'a>(source: &'a str) -> NewCapture<'a> {
        NewCapture {
            label: source,
            kind: "run",
            source,
            source_key: source,
            legacy_source_key: None,
            bytes: 10,
            exit_code: Some(0),
            session: None,
            redactions: 0,
            binary: false,
            file_mtime: None,
            file_hash: None,
        }
    }

    #[test]
    fn migrates_legacy_capture_metadata_without_changing_capture_data() {
        let mut s = store();
        let legacy = "run --password=old-secret";
        let chunks: Vec<_> = chunk_default("raw output remains available\n")
            .into_iter()
            .map(|c| ("stdout".to_string(), c))
            .collect();
        let first = s.insert_capture(&cap(legacy), &chunks).unwrap();
        let second = s.insert_capture(&cap(legacy), &chunks).unwrap();
        let first_before = s.get_by_handle(&first).unwrap().unwrap();
        let second_before = s.get_by_handle(&second).unwrap().unwrap();
        let redactor = Redactor::from_config(&Redact {
            patterns: vec!["old-secret".into()],
            builtin: false,
        })
        .unwrap();

        assert_eq!(s.migrate_legacy_metadata(&redactor).unwrap(), 2);
        let first_after = s.get_by_handle(&first).unwrap().unwrap();
        let second_after = s.get_by_handle(&second).unwrap().unwrap();
        assert_eq!(first_after.id, first_before.id);
        assert_eq!(first_after.superseded_by, first_before.superseded_by);
        assert_eq!(second_after.id, second_before.id);
        assert_eq!(first_after.label, "run --password=[redacted:user]");
        assert_eq!(first_after.source, "run --password=[redacted:user]");
        assert_eq!(
            s.full_text(first_after.id, "stdout").unwrap(),
            "raw output remains available"
        );
        let expected_key =
            crate::metadata::identity_at(s.path().parent().unwrap(), legacy).unwrap();
        let actual_key: String = s
            .conn
            .query_row(
                "SELECT source_key FROM captures WHERE id = ?1",
                params![first_after.id],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(actual_key, expected_key);
        assert!(!std::fs::read(s.path())
            .unwrap()
            .windows(b"old-secret".len())
            .any(|bytes| bytes == b"old-secret"));
        let wal_path = s.path().with_extension("db-wal");
        if wal_path.exists() {
            assert_eq!(std::fs::metadata(wal_path).unwrap().len(), 0);
        }
        assert_eq!(s.migrate_legacy_metadata(&redactor).unwrap(), 0);
    }

    #[test]
    fn migration_preserves_keyed_and_empty_source_keys() {
        let mut s = store();
        let keyed =
            crate::metadata::identity_at(s.path().parent().unwrap(), "stable source").unwrap();
        let mut keyed_capture = cap("token=old-secret");
        keyed_capture.source_key = &keyed;
        let keyed_handle = s.insert_capture(&keyed_capture, &[]).unwrap();
        let mut empty_capture = cap("another old-secret");
        empty_capture.source_key = "";
        let empty_handle = s.insert_capture(&empty_capture, &[]).unwrap();
        let redactor = Redactor::from_config(&Redact {
            patterns: vec!["old-secret".into()],
            builtin: false,
        })
        .unwrap();

        assert_eq!(s.migrate_legacy_metadata(&redactor).unwrap(), 2);
        for (handle, expected) in [(keyed_handle, keyed), (empty_handle, String::new())] {
            let actual: String = s
                .conn
                .query_row(
                    "SELECT source_key FROM captures WHERE handle = ?1",
                    params![handle],
                    |row| row.get(0),
                )
                .unwrap();
            assert_eq!(actual, expected);
        }
        assert_eq!(s.migrate_legacy_metadata(&redactor).unwrap(), 0);
    }

    #[test]
    fn migration_hashes_legacy_hex_keys_with_label_or_source_provenance() {
        let mut s = store();
        let label_key = "a".repeat(64);
        let source_key = "b".repeat(64);
        let mut explicit = cap("echo explicit");
        explicit.label = &label_key;
        explicit.source_key = &label_key;
        let explicit_handle = s.insert_capture(&explicit, &[]).unwrap();

        let source = format!("  {source_key}  2>&1");
        let mut normalized = cap(&source);
        normalized.label = "short display";
        normalized.source_key = &source_key;
        let source_handle = s.insert_capture(&normalized, &[]).unwrap();
        let redactor = Redactor::from_config(&Redact {
            patterns: vec![],
            builtin: false,
        })
        .unwrap();

        assert_eq!(s.migrate_legacy_metadata(&redactor).unwrap(), 2);
        for (handle, plaintext) in [(explicit_handle, label_key), (source_handle, source_key)] {
            let actual: String = s
                .conn
                .query_row(
                    "SELECT source_key FROM captures WHERE handle = ?1",
                    params![handle],
                    |row| row.get(0),
                )
                .unwrap();
            assert_eq!(
                actual,
                crate::metadata::identity_at(s.path().parent().unwrap(), &plaintext).unwrap()
            );
        }
        assert_eq!(s.migrate_legacy_metadata(&redactor).unwrap(), 0);
    }

    #[test]
    fn migration_preserves_keyed_identity_when_display_fields_are_redacted() {
        let mut s = store();
        let keyed =
            crate::metadata::identity_at(s.path().parent().unwrap(), "echo old-secret").unwrap();
        let mut capture = cap("echo [redacted:user]");
        capture.source_key = &keyed;
        let handle = s.insert_capture(&capture, &[]).unwrap();
        let redactor = Redactor::from_config(&Redact {
            patterns: vec!["old-secret".into()],
            builtin: false,
        })
        .unwrap();

        assert_eq!(s.migrate_legacy_metadata(&redactor).unwrap(), 0);
        let actual: String = s
            .conn
            .query_row(
                "SELECT source_key FROM captures WHERE handle = ?1",
                params![handle],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(actual, keyed);
    }

    #[test]
    fn insert_and_fetch_roundtrip() {
        let mut s = store();
        let chunks: Vec<_> = chunk_default("hello world\nsecond line\n")
            .into_iter()
            .map(|c| ("stdout".to_string(), c))
            .collect();
        let h = s.insert_capture(&cap("echo hi"), &chunks).unwrap();
        let row = s.get_by_handle(&h).unwrap().unwrap();
        assert_eq!(row.label, "echo hi");
        assert_eq!(row.chunk_count, 1);
        assert_eq!(
            s.full_text(row.id, "stdout").unwrap(),
            "hello world\nsecond line"
        );
    }

    #[test]
    fn deferred_index_is_searchable_after_materialization_and_deletes_cleanly() {
        let mut s = store();
        let chunks: Vec<_> = chunk_default("uniqueindexword in raw text\n")
            .into_iter()
            .map(|c| ("stdout".to_string(), c))
            .collect();
        let h = s
            .insert_capture_indexed(&cap("deferred"), &chunks, false)
            .unwrap();
        let id = s.get_by_handle(&h).unwrap().unwrap().id;
        assert!(s.has_deferred(Some(&h)).unwrap());
        assert_eq!(
            s.full_text(id, "stdout").unwrap(),
            "uniqueindexword in raw text"
        );
        let hits = |s: &Store| -> i64 {
            s.conn()
                .query_row(
                    "SELECT count(*) FROM chunks_porter WHERE chunks_porter MATCH 'uniqueindexword'",
                    [],
                    |r| r.get(0),
                )
                .unwrap()
        };
        assert_eq!(hits(&s), 0);
        assert_eq!(s.index_deferred(Some(&h)).unwrap(), 1);
        assert!(!s.has_deferred(Some(&h)).unwrap());
        assert_eq!(s.index_deferred(Some(&h)).unwrap(), 0);
        assert_eq!(hits(&s), 1);
        s.conn()
            .execute("DELETE FROM captures WHERE id = ?1", params![id])
            .unwrap();
        assert_eq!(hits(&s), 0);
    }

    #[test]
    fn opening_existing_store_installs_conditional_fts_triggers() {
        let dir = std::env::temp_dir().join(format!("toz-migration-{}", crate::rand::next_u64()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("toz.db");
        let conn = Connection::open(&path).unwrap();
        let old_schema = SCHEMA
            .replace(
                "  state TEXT NOT NULL DEFAULT 'completed',\n  indexed INTEGER NOT NULL DEFAULT 1\n",
                "  state TEXT NOT NULL DEFAULT 'completed'\n",
            )
            .replace(
                "  body TEXT NOT NULL,\n  indexed INTEGER NOT NULL DEFAULT 1\n",
                "  body TEXT NOT NULL\n",
            )
            .replace("WHEN new.indexed = 1 BEGIN", "BEGIN")
            .replace("WHEN old.indexed = 1 BEGIN", "BEGIN");
        conn.execute_batch(&old_schema).unwrap();
        drop(conn);

        let mut store = Store::open(&path).unwrap();
        let chunks: Vec<_> = chunk_default("deferredmigrationword\n")
            .into_iter()
            .map(|chunk| ("stdout".to_string(), chunk))
            .collect();
        let handle = store
            .insert_capture_indexed(&cap("migration"), &chunks, false)
            .unwrap();
        assert!(store.has_deferred(Some(&handle)).unwrap());
        let hits: i64 = store
            .conn()
            .query_row(
                "SELECT count(*) FROM chunks_porter WHERE chunks_porter MATCH 'deferredmigrationword'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(hits, 0);
        assert_eq!(store.index_deferred(Some(&handle)).unwrap(), 1);
        let hits: i64 = store
            .conn()
            .query_row(
                "SELECT count(*) FROM chunks_porter WHERE chunks_porter MATCH 'deferredmigrationword'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(hits, 1);

        // Recover a store interrupted after columns were added but before
        // its old unconditional triggers were replaced.
        let partial_path = dir.join("partial.db");
        let conn = Connection::open(&partial_path).unwrap();
        let partial_schema = SCHEMA
            .replace("WHEN new.indexed = 1 BEGIN", "BEGIN")
            .replace("WHEN old.indexed = 1 BEGIN", "BEGIN");
        conn.execute_batch(&partial_schema).unwrap();
        drop(conn);
        let mut partial = Store::open(&partial_path).unwrap();
        let handle = partial
            .insert_capture_indexed(&cap("partial"), &chunks, false)
            .unwrap();
        assert!(partial.has_deferred(Some(&handle)).unwrap());
        let hits: i64 = partial
            .conn()
            .query_row(
                "SELECT count(*) FROM chunks_porter WHERE chunks_porter MATCH 'deferredmigrationword'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(hits, 0);
    }

    #[test]
    fn records_round_trip_in_call_order_per_kind() {
        let mut s = store();
        let h = s.insert_capture(&cap("echo hi"), &[]).unwrap();
        let id = s.get_by_handle(&h).unwrap().unwrap().id;
        s.insert_records(
            id,
            &[
                ("line".to_string(), r#"{"n":1}"#.to_string()),
                ("other".to_string(), r#"{"x":true}"#.to_string()),
                ("line".to_string(), r#"{"n":2}"#.to_string()),
            ],
        )
        .unwrap();
        assert_eq!(
            s.records_for(id, "line").unwrap(),
            vec![r#"{"n":1}"#.to_string(), r#"{"n":2}"#.to_string()]
        );
        assert_eq!(
            s.records_for(id, "other").unwrap(),
            vec![r#"{"x":true}"#.to_string()]
        );
        assert!(s.records_for(id, "missing").unwrap().is_empty());
    }

    #[test]
    fn records_are_deleted_with_their_capture() {
        let mut s = store();
        let h = s.insert_capture(&cap("echo hi"), &[]).unwrap();
        let id = s.get_by_handle(&h).unwrap().unwrap().id;
        s.insert_records(id, &[("line".to_string(), "1".to_string())])
            .unwrap();
        // Superseding with the same source key does not delete the row; only retention does.
        // Deleting the capture directly (as retention would) must cascade to its records.
        s.conn()
            .execute("DELETE FROM captures WHERE id = ?1", params![id])
            .unwrap();
        assert!(s.records_for(id, "line").unwrap().is_empty());
    }

    #[test]
    fn profile_diagnostics_round_trip_newest_first() {
        let mut s = store();
        let h = s.insert_capture(&cap("echo hi"), &[]).unwrap();
        let id = s.get_by_handle(&h).unwrap().unwrap().id;
        s.insert_profile_diagnostic(id, "p1", "script timed out")
            .unwrap();
        s.insert_profile_diagnostic(id, "p2", "script exception: boom")
            .unwrap();
        let recent = s.recent_profile_diagnostics(10).unwrap();
        assert_eq!(recent.len(), 2);
        assert_eq!(recent[0].profile_id, "p2");
        assert_eq!(recent[1].profile_id, "p1");
    }

    #[test]
    fn supersession_by_source_key() {
        let mut s = store();
        let h1 = s.insert_capture(&cap("cargo test"), &[]).unwrap();
        let h2 = s.insert_capture(&cap("cargo test"), &[]).unwrap();
        let _ = s.insert_capture(&cap("git diff"), &[]).unwrap();
        let old = s.get_by_handle(&h1).unwrap().unwrap();
        let new = s.get_by_handle(&h2).unwrap().unwrap();
        assert_eq!(old.superseded_by, Some(new.id));
        assert!(new.superseded_by.is_none());
        let live = s.list(10, false).unwrap();
        assert_eq!(live.len(), 2);
        assert_eq!(s.list(10, true).unwrap().len(), 3);
    }

    #[test]
    fn live_capture_commits_chunks_before_completion() {
        let mut s = store();
        let mut capture = cap("live");
        capture.bytes = 0;
        capture.exit_code = None;
        let handle = s.reserve_live_capture(&capture).unwrap();
        let running = s.get_by_handle(&handle).unwrap().unwrap();
        assert_eq!(running.state, "running");
        assert_eq!(running.exit_code, None);

        let chunk = Chunk {
            ordinal: 0,
            title: "ready".into(),
            line_start: 1,
            line_end: 1,
            content_type: crate::chunk::ContentType::Prose,
            body: "ready".into(),
        };
        s.append_live_chunk(&handle, "stdout", &chunk, 6, 0)
            .unwrap();
        let visible = s.get_by_handle(&handle).unwrap().unwrap();
        assert_eq!(visible.chunk_count, 1);
        assert_eq!(s.full_text(visible.id, "stdout").unwrap(), "ready");

        s.finish_live_capture(&handle, 6, 0, 0).unwrap();
        let completed = s.get_by_handle(&handle).unwrap().unwrap();
        assert_eq!(completed.state, "completed");
        assert_eq!(completed.exit_code, Some(0));
        assert_eq!(completed.bytes, 6);
    }

    #[test]
    fn cancelling_live_capture_restores_previous_visibility() {
        let mut s = store();
        let old = s.insert_capture(&cap("same"), &[]).unwrap();
        let mut live = cap("same");
        live.bytes = 0;
        live.exit_code = None;
        let reserved = s.reserve_live_capture(&live).unwrap();
        assert!(s
            .get_by_handle(&old)
            .unwrap()
            .unwrap()
            .superseded_by
            .is_none());

        s.cancel_live_capture(&reserved).unwrap();

        assert!(s.get_by_handle(&reserved).unwrap().is_none());
        assert!(s
            .get_by_handle(&old)
            .unwrap()
            .unwrap()
            .superseded_by
            .is_none());
    }

    #[test]
    fn completing_live_capture_supersedes_previous_capture() {
        let mut s = store();
        let old = s.insert_capture(&cap("same"), &[]).unwrap();
        let mut live = cap("same");
        live.bytes = 0;
        live.exit_code = None;
        let handle = s.reserve_live_capture(&live).unwrap();

        s.finish_live_capture(&handle, 0, 0, 0).unwrap();

        let completed = s.get_by_handle(&handle).unwrap().unwrap();
        assert_eq!(completed.state, "completed");
        assert_eq!(
            s.get_by_handle(&old).unwrap().unwrap().superseded_by,
            Some(completed.id)
        );
    }

    #[test]
    fn opening_store_recovers_abandoned_live_capture() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("toz.db");
        let (old, abandoned) = {
            let mut s = Store::open(&path).unwrap();
            let old = s.insert_capture(&cap("same"), &[]).unwrap();
            let mut live = cap("same");
            live.bytes = 0;
            live.exit_code = None;
            let abandoned = s.reserve_live_capture(&live).unwrap();
            let chunk = Chunk {
                ordinal: 0,
                title: "partial".into(),
                line_start: 1,
                line_end: 1,
                content_type: crate::chunk::ContentType::Prose,
                body: "partial output".into(),
            };
            s.append_live_chunk(&abandoned, "stdout", &chunk, 14, 0)
                .unwrap();
            (old, abandoned)
        };

        let recovered = Store::open(&path).unwrap();

        let interrupted = recovered.get_by_handle(&abandoned).unwrap().unwrap();
        assert_eq!(interrupted.state, "interrupted");
        assert_eq!(interrupted.chunk_count, 1);
        assert_eq!(
            recovered.full_text(interrupted.id, "stdout").unwrap(),
            "partial output"
        );
        assert!(recovered
            .get_by_handle(&old)
            .unwrap()
            .unwrap()
            .superseded_by
            .is_none());
    }

    #[test]
    fn opening_store_does_not_interrupt_active_live_capture() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("toz.db");
        let mut owner = Store::open(&path).unwrap();
        let handle = owner.reserve_live_capture(&cap("live")).unwrap();

        let observer = Store::open(&path).unwrap();

        assert_eq!(
            observer.get_by_handle(&handle).unwrap().unwrap().state,
            "running"
        );
        owner.cancel_live_capture(&handle).unwrap();
    }

    #[test]
    fn concurrent_stores_serialize_capture_transactions() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("toz.db");
        Store::open(&path).unwrap();
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(9));
        let workers: Vec<_> = (0..8)
            .map(|index| {
                let path = path.clone();
                let barrier = barrier.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    let mut store = Store::open(&path).unwrap();
                    let source = format!("worker-{index}");
                    store.insert_capture(&cap(&source), &[]).unwrap()
                })
            })
            .collect();
        barrier.wait();
        let handles: Vec<_> = workers
            .into_iter()
            .map(|worker| worker.join().unwrap())
            .collect();

        let store = Store::open(&path).unwrap();
        for handle in handles {
            assert!(store.get_by_handle(&handle).unwrap().is_some());
        }
        assert_eq!(store.list(20, true).unwrap().len(), 8);
    }

    #[test]
    #[ignore = "helper process for concurrent_capture_processes_persist_every_result"]
    fn multiprocess_capture_worker() {
        let base = PathBuf::from(std::env::var_os("TOZ_TEST_PROCESS_BASE").unwrap());
        let source = std::env::var("TOZ_TEST_PROCESS_SOURCE").unwrap();
        std::fs::write(base.join(format!("ready-{source}")), b"").unwrap();
        let deadline = Instant::now() + Duration::from_secs(10);
        while !base.join("go").exists() {
            assert!(
                Instant::now() < deadline,
                "timed out waiting for process gate"
            );
            std::thread::sleep(Duration::from_millis(5));
        }
        let mut store = Store::open(&base.join("toz.db")).unwrap();
        store.insert_capture(&cap(&source), &[]).unwrap();
    }

    #[test]
    fn concurrent_capture_processes_persist_every_result() {
        let dir = tempfile::tempdir().unwrap();
        Store::open(&dir.path().join("toz.db")).unwrap();
        let exe = std::env::current_exe().unwrap();
        let mut workers: Vec<_> = (0..8)
            .map(|index| {
                std::process::Command::new(&exe)
                    .args([
                        "--exact",
                        "store::tests::multiprocess_capture_worker",
                        "--ignored",
                    ])
                    .env("TOZ_TEST_PROCESS_BASE", dir.path())
                    .env("TOZ_TEST_PROCESS_SOURCE", format!("process-{index}"))
                    .spawn()
                    .unwrap()
            })
            .collect();
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            let ready = std::fs::read_dir(dir.path())
                .unwrap()
                .flatten()
                .filter(|entry| entry.file_name().to_string_lossy().starts_with("ready-"))
                .count();
            if ready == workers.len() {
                break;
            }
            assert!(
                Instant::now() < deadline,
                "workers did not reach process gate"
            );
            std::thread::sleep(Duration::from_millis(5));
        }
        std::fs::write(dir.path().join("go"), b"").unwrap();
        for worker in &mut workers {
            assert!(worker.wait().unwrap().success());
        }

        let store = Store::open(&dir.path().join("toz.db")).unwrap();
        assert_eq!(store.list(20, true).unwrap().len(), workers.len());
    }

    #[test]
    fn full_text_reassembles_overlapping_chunks() {
        let mut s = store();
        let text: String = (1..=200).map(|i| format!("line {i}\n")).collect();
        let chunks: Vec<_> = chunk_default(&text)
            .into_iter()
            .map(|c| ("stdout".to_string(), c))
            .collect();
        let h = s.insert_capture(&cap("gen"), &chunks).unwrap();
        let row = s.get_by_handle(&h).unwrap().unwrap();
        assert_eq!(s.full_text(row.id, "stdout").unwrap(), text.trim_end());
    }

    #[test]
    fn lazy_reader_matches_full_text_on_overlapping_chunks() {
        let mut s = store();
        let text: String = (1..=200).map(|i| format!("line {i}\n")).collect();
        let chunks: Vec<_> = chunk_default(&text)
            .into_iter()
            .map(|c| ("stdout".to_string(), c))
            .collect();
        let h = s.insert_capture(&cap("gen"), &chunks).unwrap();
        let row = s.get_by_handle(&h).unwrap().unwrap();

        let mut got: Vec<String> = Vec::new();
        s.for_each_line(row.id, "stdout", |l| {
            got.push(l.to_string());
            Ok(())
        })
        .unwrap();
        assert_eq!(got.join("\n"), s.full_text(row.id, "stdout").unwrap());
    }

    #[test]
    fn lazy_reader_bounds_peak_allocation() {
        let mut s = store();
        let text: String = (1..=60_000)
            .map(|i| format!("line {i} some padding to make this worth measuring\n"))
            .collect();
        let size = text.len();
        let chunks: Vec<_> = chunk_default(&text)
            .into_iter()
            .map(|c| ("stdout".to_string(), c))
            .collect();
        let h = s.insert_capture(&cap("big"), &chunks).unwrap();
        let row = s.get_by_handle(&h).unwrap().unwrap();
        drop(text);

        crate::alloc_probe::reset();
        let mut counted = 0usize;
        s.for_each_line(row.id, "stdout", |_| {
            counted += 1;
            Ok(())
        })
        .unwrap();
        let lazy_peak = crate::alloc_probe::peak();

        crate::alloc_probe::reset();
        let full = s.full_text(row.id, "stdout").unwrap();
        let eager_peak = crate::alloc_probe::peak();
        drop(full);

        assert!(counted > 50_000, "reader saw {counted} lines");
        // The point is a bound that scales with a chunk, not with the capture.
        assert!(
            lazy_peak * 8 < size,
            "lazy peak {lazy_peak} is not small against a {size}-byte capture"
        );
        assert!(
            lazy_peak * 4 < eager_peak,
            "lazy peak {lazy_peak} vs full_text peak {eager_peak}"
        );
        // Pins why this reader exists: `full_text` holds bodies, then a per-line Vec, then the
        // joined String. Measured at ~3.7x the capture; the lazy peak is one chunk.
        assert!(
            eager_peak > size,
            "full_text no longer materialises ({eager_peak} vs {size}); the lazy reader may be redundant"
        );
    }

    #[test]
    fn fts_tables_populated() {
        let mut s = store();
        let chunks: Vec<_> = chunk_default("the quick brown fox\n")
            .into_iter()
            .map(|c| ("stdout".to_string(), c))
            .collect();
        s.insert_capture(&cap("x"), &chunks).unwrap();
        let n: i64 = s
            .conn()
            .query_row(
                "SELECT COUNT(*) FROM chunks_porter WHERE chunks_porter MATCH 'quick'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(n, 1);
        let n: i64 = s
            .conn()
            .query_row(
                "SELECT COUNT(*) FROM chunks_trigram WHERE chunks_trigram MATCH 'uic'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(n, 1);
    }

    #[test]
    fn prune_reclaims_free_pages_without_deleting_captures() {
        let mut s = store();
        let h1 = s.insert_capture(&cap("first"), &[]).unwrap();
        let h2 = s.insert_capture(&cap("second"), &[]).unwrap();

        s.conn()
            .execute_batch(
                "CREATE TABLE discarded_data (body BLOB NOT NULL);
                 INSERT INTO discarded_data(body) VALUES (zeroblob(2097152));
                 DROP TABLE discarded_data;",
            )
            .unwrap();
        assert!(s.db_size_bytes().unwrap() > 1024 * 1024);

        let removed = s
            .prune(&Retention {
                days: 36_500,
                superseded_days: 36_500,
                max_mb: 1,
            })
            .unwrap();

        assert_eq!(removed, 0);
        assert!(s.get_by_handle(&h1).unwrap().is_some());
        assert!(s.get_by_handle(&h2).unwrap().is_some());
        assert!(s.db_size_bytes().unwrap() <= 1024 * 1024);
    }

    #[test]
    fn prune_never_removes_running_captures() {
        let mut s = store();
        let handle = s.reserve_live_capture(&cap("long-running")).unwrap();
        s.conn()
            .execute(
                "UPDATE captures SET created_at = 0 WHERE handle = ?1",
                params![handle],
            )
            .unwrap();

        let removed = s
            .prune(&Retention {
                days: 0,
                superseded_days: 0,
                max_mb: 0,
            })
            .unwrap();

        assert_eq!(removed, 0);
        assert_eq!(s.get_by_handle(&handle).unwrap().unwrap().state, "running");
        s.cancel_live_capture(&handle).unwrap();
    }
}
