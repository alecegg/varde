//! `build` subcommand: populate the persisted SQLite index the 17 query
//! modes read from (`~/.config/varde-code/repos/<name>-<hash>/index.db`).
//!
//! Before this existed, `extract` only printed JSON to stdout and nothing
//! ever wrote to that database — every query mode failed with `db_error` on
//! a repo that had never been indexed by anything else. This wires the
//! existing scan -> resolve -> persist pipeline (already exercised by the
//! integration tests) up to the CLI.

use anyhow::{Context, Result};
use rayon::prelude::*;
use std::path::Path;

use crate::model::ExtractOutput;
use crate::resolve::ResolvedGraph;

pub use crate::persist::StoredFileState;

/// Result of comparing stored file state with a current source listing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FileClassification {
    Unchanged { path: String },
    Changed { path: String },
    New { path: String },
    Deleted { path: String },
}

/// Classify current and stored files without reading current file contents.
pub fn classify_files(
    stored: &[StoredFileState],
    current: &[crate::scan::SourceFile],
) -> Vec<FileClassification> {
    let stored_by_path: std::collections::HashMap<&str, &StoredFileState> = stored
        .iter()
        .map(|file| (file.path.as_str(), file))
        .collect();
    let current_paths: std::collections::HashSet<&str> =
        current.iter().map(|file| file.path.as_str()).collect();

    let mut classifications = current
        .iter()
        .map(|file| match stored_by_path.get(file.path.as_str()) {
            None => FileClassification::New {
                path: file.path.clone(),
            },
            Some(stored) if files_match(stored, file) => FileClassification::Unchanged {
                path: file.path.clone(),
            },
            Some(_) => FileClassification::Changed {
                path: file.path.clone(),
            },
        })
        .collect::<Vec<_>>();

    classifications.extend(
        stored
            .iter()
            .filter(|file| !current_paths.contains(file.path.as_str()))
            .map(|file| FileClassification::Deleted {
                path: file.path.clone(),
            }),
    );

    classifications
}

/// Whether `current` can be treated as unchanged vs its `stored` state.
///
/// KNOWN LIMITATION (inherent TOCTOU, by design): when mtime+size are known,
/// a match classifies the file Unchanged without re-hashing at persist time.
/// A file edited between the directory scan and persist — without changing
/// mtime or size — is therefore treated as unchanged for this build. This is
/// self-correcting (the next build's scan picks up the newer mtime) and never
/// corrupts the index; the content-hash comparison below is the fallback used
/// only when metadata is UNKNOWN. Accepted rather than paying a re-stat/hash
/// on every unchanged file each build.
fn files_match(stored: &StoredFileState, current: &crate::scan::SourceFile) -> bool {
    if stored.mtime != current.mtime || stored.size != current.size {
        return false;
    }

    if stored.mtime == crate::scan::UNKNOWN_METADATA && stored.size == crate::scan::UNKNOWN_METADATA
    {
        return current.content_hash.as_deref() == Some(stored.content_hash.as_str());
    }

    true
}

/// Extract + resolve `repo_root`, then persist to its conventional db path.
/// Returns the db path written, plus entity/symbol counts for reporting.
pub fn run(repo_root: &str) -> Result<BuildSummary> {
    run_with_force(repo_root, false)
}

/// Build an index, optionally bypassing incremental state.
pub fn run_with_force(repo_root: &str, force: bool) -> Result<BuildSummary> {
    let db_path = crate::db::path::repo_db_path(Path::new(repo_root));
    if let Some(parent) = db_path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    if force {
        return run_full(repo_root, &db_path);
    }
    if db_path.exists() {
        return run_incremental(repo_root, &db_path);
    }

    run_full(repo_root, &db_path)
}

/// Build-on-read (§0, step 1): bring just `file_path`'s structural slice up to
/// date before a per-file query reads it, so the answer is always fresh while
/// the work stays proportional to what changed.
///
/// - Index absent or schema-mismatched → fall back to a full build (POC
///   fallback; a future targeted-build path can replace this).
/// - File unchanged since the index was built → no-op.
/// - File new or changed → reparse *only that file* and refresh its raw slice
///   (entities/symbols/diagnostics + `files` metadata), leaving the global
///   derived layer untouched — a `symbols_in_file` reader needs none of it.
///
/// A missing on-disk file is a no-op here (nothing to reparse); deletion
/// handling is left to the file's owning slice rebuild.
pub fn ensure_file_fresh(repo_root: &str, file_path: &str) -> Result<()> {
    crate::slice::ensure_fresh(
        &[crate::slice::Slice::Raw],
        repo_root,
        &crate::slice::Scope::File(file_path.to_string()),
    )
}

fn run_full(repo_root: &str, db_path: &Path) -> Result<BuildSummary> {
    // A full build owns a fixed sibling temp path before atomically renaming
    // it into place. Hold the repository lock for that entire lifecycle so
    // concurrent forced or first-time builds cannot delete, write, or rename
    // one another's temporary database.
    let _lock = crate::repo_lock::acquire(db_path, std::time::Duration::from_secs(30))?;

    run_full_while_locked(repo_root, db_path)
}

/// Build while the caller holds this repository's advisory lock.
///
/// [`crate::slice::ensure_fresh`] already owns the lock when a missing or
/// schema-mismatched index requires a full rebuild. Reacquiring it would wait
/// on that caller's own non-reentrant `flock`.
pub(crate) fn run_full_while_locked(repo_root: &str, db_path: &Path) -> Result<BuildSummary> {
    let profile = std::env::var_os("VARDE_PROFILE").is_some();
    let t0 = std::time::Instant::now();

    // Enumerate the file list up front, then hand it to the streaming full
    // build, which pipelines parsing against persistence (see
    // `persist::persist_full_streaming`). Parsing and the raw-row inserts run
    // concurrently instead of as two sequential phases.
    let listing = crate::scan::list_source_listing(repo_root)?;

    // Write to a sibling temp file and rename it into place only after a full
    // successful commit — an interruption mid-write leaves the prior good
    // index untouched (`journal_mode=OFF` gives up crash recovery, so a direct
    // write could corrupt it); only a clean run ever replaces it.
    let tmp_path = db_path.with_extension("db.tmp");
    let _ = std::fs::remove_file(&tmp_path);

    let stats =
        match crate::persist::persist_full_streaming(&tmp_path, listing, Path::new(repo_root)) {
            Ok(stats) => {
                std::fs::rename(&tmp_path, db_path)?;
                stats
            }
            Err(e) => {
                let _ = std::fs::remove_file(&tmp_path);
                return Err(e);
            }
        };

    // The built-at git HEAD and the eager `graph_cache` warm now happen inside
    // `persist_full_streaming`'s transaction (from the warm, just-written rows),
    // so a fresh build already lands both atomically with the index — no
    // post-commit reopen + cold from-SQL rebuild. See the streaming build's
    // graph_cache+githead step.

    if profile {
        eprintln!(
            "VARDE_PROFILE build: total={:?} entities={} symbols={} diagnostics={}",
            t0.elapsed(),
            stats.entities,
            stats.symbols,
            stats.diagnostics,
        );
    }

    Ok(BuildSummary {
        db_path: db_path.display().to_string(),
        entities: stats.entities,
        symbols: stats.symbols,
        diagnostics: stats.diagnostics,
        unchanged: 0,
        reparsed: stats.files.len(),
        changed_files: stats.files,
    })
}

fn run_incremental(repo_root: &str, db_path: &Path) -> Result<BuildSummary> {
    let profile = std::env::var_os("VARDE_PROFILE").is_some();
    let started = std::time::Instant::now();
    let _lock = crate::repo_lock::acquire(db_path, std::time::Duration::from_secs(30))?;
    let Some(start) = prepare_incremental(repo_root, db_path)? else {
        return run_full_while_locked(repo_root, db_path);
    };
    replace_traversal_diagnostics(&start.conn, &start.traversal)?;
    let classifications = classify_files(&start.stored, &start.current);
    let unchanged = classifications
        .iter()
        .filter(|item| matches!(item, FileClassification::Unchanged { .. }))
        .count();
    if classifications
        .iter()
        .all(|item| matches!(item, FileClassification::Unchanged { .. }))
    {
        return unchanged_summary(&start.conn, db_path, unchanged, profile, started);
    }
    let changes = IncrementalChanges::load(&start.conn, &classifications)?;
    let (changed_file_ids, delta_time) = persist_changed_files(&start.conn, repo_root, &changes)?;
    let resolved = resolve_incremental(&start.conn, repo_root, &changes, &changed_file_ids)?;
    report_incremental_profile(profile, started, delta_time, &resolved);
    Ok(BuildSummary {
        db_path: db_path.display().to_string(),
        entities: resolved.state.entities.len(),
        symbols: resolved.symbols,
        diagnostics: resolved.state.diagnostics,
        unchanged,
        reparsed: changes.changed_paths.len(),
        changed_files: changes.changed_paths,
    })
}

struct IncrementalStart {
    conn: rusqlite::Connection,
    current: Vec<crate::scan::SourceFile>,
    traversal: Vec<crate::model::Diagnostic>,
    stored: Vec<StoredFileState>,
}

fn prepare_incremental(repo_root: &str, db_path: &Path) -> Result<Option<IncrementalStart>> {
    let listing = crate::scan::list_source_listing(repo_root)?;
    if listing
        .diagnostics
        .iter()
        .any(|diagnostic| Path::new(&diagnostic.path) == Path::new(repo_root))
    {
        return Err(anyhow::anyhow!(
            "cannot traverse repository root: {repo_root}"
        ));
    }
    let conn = crate::db::open_incremental(db_path)?;
    let schema_matches =
        crate::db::schema_version(&conn).is_ok_and(|version| version == crate::db::SCHEMA_VERSION);
    if !schema_matches || !crate::persist::index_build_version_matches(&conn) {
        return Ok(None);
    }
    let Ok(stored) = crate::persist::load_file_states(&conn) else {
        return Ok(None);
    };
    if stored.is_empty()
        || stored
            .iter()
            .any(|file| !valid_content_hash(&file.content_hash))
    {
        return Ok(None);
    }
    Ok(Some(IncrementalStart {
        conn,
        current: listing.files,
        traversal: listing.diagnostics,
        stored,
    }))
}

fn replace_traversal_diagnostics(
    conn: &rusqlite::Connection,
    diagnostics: &[crate::model::Diagnostic],
) -> Result<()> {
    let transaction = conn.unchecked_transaction()?;
    crate::persist::replace_traversal_diagnostics(&transaction, diagnostics)?;
    transaction.commit()?;
    Ok(())
}

fn unchanged_summary(
    conn: &rusqlite::Connection,
    db_path: &Path,
    unchanged: usize,
    profile: bool,
    started: std::time::Instant,
) -> Result<BuildSummary> {
    let counts = crate::persist::index_counts(conn)?;
    if profile {
        eprintln!(
            "VARDE_PROFILE build: no changes — skipped global re-resolve, total={:?}",
            started.elapsed()
        );
    }
    Ok(BuildSummary {
        db_path: db_path.display().to_string(),
        entities: counts.entities,
        symbols: counts.symbols,
        diagnostics: counts.diagnostics,
        unchanged,
        reparsed: 0,
        changed_files: Vec::new(),
    })
}

struct IncrementalChanges {
    changed_paths: Vec<String>,
    new_paths: Vec<String>,
    deleted_ids: Vec<i64>,
}

impl IncrementalChanges {
    fn load(conn: &rusqlite::Connection, items: &[FileClassification]) -> Result<Self> {
        let file_ids = crate::persist::load_file_ids(conn)?;
        let changed_paths = items
            .iter()
            .filter_map(|item| match item {
                FileClassification::Changed { path } | FileClassification::New { path } => {
                    Some(path.clone())
                }
                _ => None,
            })
            .collect();
        let new_paths = items
            .iter()
            .filter_map(|item| match item {
                FileClassification::New { path } => Some(path.clone()),
                _ => None,
            })
            .collect();
        let deleted_ids = items
            .iter()
            .filter_map(|item| match item {
                FileClassification::Deleted { path } => file_ids.get(path).copied(),
                _ => None,
            })
            .collect();
        Ok(Self {
            changed_paths,
            new_paths,
            deleted_ids,
        })
    }

    fn changes_file_set(&self) -> bool {
        !self.new_paths.is_empty() || !self.deleted_ids.is_empty()
    }
}

fn persist_changed_files(
    conn: &rusqlite::Connection,
    repo_root: &str,
    changes: &IncrementalChanges,
) -> Result<(Vec<i64>, std::time::Duration)> {
    crate::persist::insert_new_files(conn, &changes.new_paths)?;
    let file_ids = crate::persist::load_file_ids(conn)?;
    crate::persist::delete_deleted_files(conn, &changes.deleted_ids)?;
    let outputs = changes
        .changed_paths
        .par_iter()
        .map(|path| crate::scan::run(path))
        .collect::<Result<Vec<_>>>()?;
    let changed_file_ids = changes
        .changed_paths
        .iter()
        .map(|path| {
            file_ids
                .get(path)
                .copied()
                .with_context(|| format!("missing file id for changed file {path}"))
        })
        .collect::<Result<Vec<_>>>()?;
    let started = std::time::Instant::now();
    crate::persist::persist_delta(
        conn,
        &changed_file_ids,
        &outputs,
        &empty_delta_graph(&outputs),
        Path::new(repo_root),
    )?;
    Ok((changed_file_ids, started.elapsed()))
}

struct IncrementalResolved {
    state: crate::persist::PersistedState,
    symbols: usize,
    elapsed: std::time::Duration,
}

fn resolve_incremental(
    conn: &rusqlite::Connection,
    repo_root: &str,
    changes: &IncrementalChanges,
    changed_file_ids: &[i64],
) -> Result<IncrementalResolved> {
    let started = std::time::Instant::now();
    let scope = if changes.changes_file_set() {
        None
    } else {
        crate::slice::reverse_dependent_scope(conn, changed_file_ids)?
    };
    let (state, symbols) = match scope {
        Some(scope_ids) => resolve_scoped(conn, &scope_ids)?,
        None => resolve_global(conn)?,
    };
    crate::slice::record_git_head(conn, repo_root)?;
    Ok(IncrementalResolved {
        state,
        symbols,
        elapsed: started.elapsed(),
    })
}

fn resolve_scoped(
    conn: &rusqlite::Connection,
    scope_ids: &std::collections::BTreeSet<i64>,
) -> Result<(crate::persist::PersistedState, usize)> {
    let state = crate::persist::query_persisted_state(conn, false)?;
    let max = crate::persist::max_rev(conn)?;
    crate::slice::run_scoped_edge_refresh(conn, &state, scope_ids, max)?;
    let edges = crate::persist::load_resolved_edges(conn, &state)?;
    let graph = crate::resolve::resolve_global_from_edges(&state.entities, &state.files, edges);
    crate::persist::rewrite_global(conn, &state, &graph)?;
    Ok((state, crate::persist::index_counts(conn)?.symbols))
}

fn resolve_global(conn: &rusqlite::Connection) -> Result<(crate::persist::PersistedState, usize)> {
    crate::persist::delete_global_rows(conn)?;
    let state = crate::persist::query_persisted_state(conn, false)?;
    let graph = crate::resolve::resolve(&state.entities, &state.symbols, &state.files)?;
    crate::persist::persist_global_graph(conn, &state, &graph)?;
    crate::persist::rebuild_graph_cache_full(conn)?;
    Ok((state, crate::persist::index_counts(conn)?.symbols))
}

fn report_incremental_profile(
    profile: bool,
    started: std::time::Instant,
    delta_time: std::time::Duration,
    resolved: &IncrementalResolved,
) {
    if profile {
        eprintln!(
            "VARDE_PROFILE build: scan={:?} resolve={:?} persist={delta_time:?} total={:?} entities={} symbols={} diagnostics={}",
            started
                .elapsed()
                .saturating_sub(delta_time + resolved.elapsed),
            resolved.elapsed,
            started.elapsed(),
            resolved.state.entities.len(),
            resolved.symbols,
            resolved.state.diagnostics,
        );
    }
}

fn valid_content_hash(hash: &str) -> bool {
    hash.len() == 16 && hash.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn empty_delta_graph(outputs: &[ExtractOutput]) -> ResolvedGraph {
    let files = outputs
        .iter()
        .flat_map(|output| output.files.iter().cloned())
        .collect::<Vec<_>>();
    ResolvedGraph {
        nodes: crate::resolve::graph::build_nodes(&files),
        edges: Vec::new(),
        communities: Vec::new(),
        clone_bands: Vec::new(),
    }
}

pub struct BuildSummary {
    pub db_path: String,
    pub entities: usize,
    pub symbols: usize,
    pub diagnostics: usize,
    pub unchanged: usize,
    pub reparsed: usize,
    /// Paths reparsed this run — the drill-down handle for agents to feed
    /// into `symbols_in_file`/`map_file` without re-deriving "what changed"
    /// themselves.
    pub changed_files: Vec<String>,
}

#[cfg(test)]
mod tests {
    use rusqlite::OptionalExtension;

    use super::{
        FileClassification, StoredFileState, classify_files, run_full_while_locked,
        run_incremental, run_with_force,
    };
    use crate::scan::SourceFile;
    use std::path::Path;

    fn temp_fixture_root(label: &str) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "varde-build-{label}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock is after epoch")
                .as_nanos()
        ));
        std::fs::create_dir_all(&path).expect("fixture directory creates");
        path
    }

    #[test]
    fn matching_metadata_is_unchanged_without_content_hash() {
        let stored = StoredFileState {
            path: "src/lib.rs".to_string(),
            mtime: 10,
            size: 20,
            content_hash: "stored-hash".to_string(),
        };
        let current = SourceFile {
            path: "src/lib.rs".to_string(),
            mtime: 10,
            size: 20,
            content_hash: None,
        };

        assert_eq!(
            classify_files(&[stored], &[current]),
            vec![FileClassification::Unchanged {
                path: "src/lib.rs".to_string(),
            }]
        );
    }

    #[test]
    fn differing_mtime_or_size_is_changed() {
        let stored = StoredFileState {
            path: "src/lib.rs".to_string(),
            mtime: 10,
            size: 20,
            content_hash: "stored-hash".to_string(),
        };
        let current = SourceFile {
            path: "src/lib.rs".to_string(),
            mtime: 11,
            size: 20,
            content_hash: None,
        };

        assert_eq!(
            classify_files(&[stored], &[current]),
            vec![FileClassification::Changed {
                path: "src/lib.rs".to_string(),
            }]
        );
    }

    #[test]
    fn differing_size_is_changed() {
        let stored = StoredFileState {
            path: "src/lib.rs".to_string(),
            mtime: 10,
            size: 20,
            content_hash: "stored-hash".to_string(),
        };
        let current = SourceFile {
            path: "src/lib.rs".to_string(),
            mtime: 10,
            size: 21,
            content_hash: None,
        };

        assert_eq!(
            classify_files(&[stored], &[current]),
            vec![FileClassification::Changed {
                path: "src/lib.rs".to_string(),
            }]
        );
    }

    #[test]
    fn current_file_without_stored_state_is_new() {
        let current = SourceFile {
            path: "src/new.rs".to_string(),
            mtime: 10,
            size: 20,
            content_hash: None,
        };

        assert_eq!(
            classify_files(&[], &[current]),
            vec![FileClassification::New {
                path: "src/new.rs".to_string(),
            }]
        );
    }

    #[test]
    fn stored_file_absent_from_current_state_is_deleted() {
        let stored = StoredFileState {
            path: "src/old.rs".to_string(),
            mtime: 10,
            size: 20,
            content_hash: "stored-hash".to_string(),
        };

        assert_eq!(
            classify_files(&[stored], &[]),
            vec![FileClassification::Deleted {
                path: "src/old.rs".to_string(),
            }]
        );
    }

    #[test]
    fn unknown_metadata_uses_content_hash_as_fallback() {
        let stored = StoredFileState {
            path: "src/lib.rs".to_string(),
            mtime: crate::scan::UNKNOWN_METADATA,
            size: crate::scan::UNKNOWN_METADATA,
            content_hash: "stored-hash".to_string(),
        };
        let current = SourceFile {
            path: "src/lib.rs".to_string(),
            mtime: crate::scan::UNKNOWN_METADATA,
            size: crate::scan::UNKNOWN_METADATA,
            content_hash: Some("stored-hash".to_string()),
        };

        assert_eq!(
            classify_files(&[stored], &[current]),
            vec![FileClassification::Unchanged {
                path: "src/lib.rs".to_string(),
            }]
        );
    }

    #[test]
    fn fresh_full_build_eagerly_populates_graph_cache() {
        // `run_with_force` resolves its db path from `HOME` (the conventional
        // repo-db layout) — isolate it like every other HOME-touching test to
        // avoid racing the real home dir or other parallel tests.
        let home = std::env::temp_dir().join(format!(
            "varde-build-home-eager-cache-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock is after epoch")
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&home);
        std::fs::create_dir_all(&home).expect("home creates");
        let _home_override = crate::test_support::HomeOverride::new(&home);

        let root = temp_fixture_root("eager-cache-full-build");
        std::fs::write(root.join("a.rs"), "fn a() { b(); }").expect("a.rs writes");
        std::fs::write(root.join("b.rs"), "fn b() {}").expect("b.rs writes");

        run_with_force(root.to_str().expect("root is utf-8"), true)
            .expect("fresh full build succeeds");

        let db_path = crate::db::path::repo_db_path(&root);
        let conn = crate::db::open(&db_path).expect("db opens");
        let row: Option<(Vec<u8>, i64)> = conn
            .query_row("SELECT blob, rev FROM graph_cache WHERE id = 1", [], |r| {
                Ok((r.get(0)?, r.get(1)?))
            })
            .optional()
            .expect("graph_cache query runs");
        let (blob, rev) = row.expect("graph_cache row is populated immediately after run_full");
        assert!(!blob.is_empty(), "graph_cache blob must be non-empty");
        assert!(rev >= 0, "graph_cache rev must be a valid ledger value");

        drop(conn);
        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn concurrent_incremental_builds_serialize_without_error() {
        // Regression for the repo-lock gap: two agents (or a build racing a
        // query-triggered `slice::ensure_fresh`) running `build` on the same
        // repo must serialize on the repo lock and all succeed — not race
        // SQLite's per-connection EXCLUSIVE lock into a SQLITE_BUSY error, which
        // `run_incremental` has no busy-retry of its own to absorb.
        let home = std::env::temp_dir().join(format!(
            "varde-build-home-concurrent-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock is after epoch")
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&home);
        std::fs::create_dir_all(&home).expect("home creates");
        let _home_override = crate::test_support::HomeOverride::new(&home);

        let root = temp_fixture_root("concurrent-build");
        std::fs::write(root.join("a.rs"), "fn a() { b(); }").expect("a.rs writes");
        std::fs::write(root.join("b.rs"), "fn b() {}").expect("b.rs writes");
        let root_s = root.to_str().expect("root is utf-8").to_string();

        // Initial build creates the DB so every later run takes the in-place
        // incremental path (the one that now holds the repo lock).
        run_with_force(&root_s, false).expect("initial build succeeds");
        // Give each concurrent run real incremental work to do.
        std::fs::write(root.join("a.rs"), "fn a() { b(); b(); }").expect("a.rs edit writes");

        let handles: Vec<_> = (0..4)
            .map(|_| {
                let root_s = root_s.clone();
                std::thread::spawn(move || run_with_force(&root_s, false))
            })
            .collect();
        for handle in handles {
            handle
                .join()
                .expect("build thread joins")
                .expect("concurrent incremental build succeeds without SQLITE_BUSY");
        }

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn concurrent_initial_and_forced_full_builds_serialize_without_error() {
        let home = std::env::temp_dir().join(format!(
            "varde-build-home-concurrent-full-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock is after epoch")
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&home);
        std::fs::create_dir_all(&home).expect("home creates");
        let _home_override = crate::test_support::HomeOverride::new(&home);

        let root = temp_fixture_root("concurrent-full-build");
        std::fs::write(root.join("a.rs"), "fn a() { b(); }").expect("a.rs writes");
        std::fs::write(root.join("b.rs"), "fn b() {}").expect("b.rs writes");
        let root_s = root.to_str().expect("root is utf-8").to_string();

        let handles: Vec<_> = (0..8)
            .map(|index| {
                let root_s = root_s.clone();
                std::thread::spawn(move || run_with_force(&root_s, index % 2 == 0))
            })
            .collect();
        for handle in handles {
            handle
                .join()
                .expect("build thread joins")
                .expect("concurrent initial or forced full build succeeds");
        }

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&root);
    }

    /// Read back every persisted traversal diagnostic (`file_id IS NULL`) as
    /// `(path, message)`.
    fn traversal_diagnostics(db_path: &Path) -> Vec<(String, String)> {
        let conn = crate::db::open(db_path).expect("db opens");
        let mut stmt = conn
            .prepare("SELECT path, message FROM diagnostics WHERE file_id IS NULL ORDER BY path")
            .expect("query prepares");
        stmt.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))
            .expect("query runs")
            .collect::<rusqlite::Result<Vec<(String, String)>>>()
            .expect("rows read")
    }

    /// CORRECTNESS-005: a full build over a tree with an unreadable nested
    /// directory indexes the valid siblings AND leaves durable evidence that
    /// discovery was incomplete.
    #[cfg(unix)]
    #[test]
    fn full_build_persists_path_based_traversal_diagnostic() {
        use std::os::unix::fs::PermissionsExt;

        let root = temp_fixture_root("traversal-full");
        let db_path = root.with_extension("traversal-full.db");
        std::fs::write(root.join("sibling.rs"), "fn sibling() {}").expect("sibling writes");
        let locked = root.join("locked");
        std::fs::create_dir_all(&locked).expect("locked dir creates");
        std::fs::set_permissions(&locked, std::fs::Permissions::from_mode(0o000))
            .expect("chmod 000");

        let summary = run_full_while_locked(root.to_str().expect("root is utf-8"), &db_path)
            .expect("full build survives the unreadable directory");

        std::fs::set_permissions(&locked, std::fs::Permissions::from_mode(0o755))
            .expect("chmod restore");

        assert!(
            summary
                .changed_files
                .iter()
                .any(|f| f.ends_with("sibling.rs")),
            "valid siblings must still be indexed: {:?}",
            summary.changed_files
        );
        let persisted = traversal_diagnostics(&db_path);
        assert_eq!(
            persisted.len(),
            1,
            "exactly one traversal diagnostic expected, got {persisted:?}"
        );
        assert!(
            persisted[0].0.ends_with("locked"),
            "diagnostic must carry the failing path: {persisted:?}"
        );
        assert!(
            persisted[0].1.contains("directory traversal failed"),
            "diagnostic message must name the failure: {persisted:?}"
        );

        let _ = std::fs::remove_dir_all(&root);
        let _ = std::fs::remove_file(&db_path);
    }

    /// CORRECTNESS-005: the traversal diagnostic is walk state, not file
    /// state. Once the directory is readable again the next incremental build
    /// must drop it — including when no source file changed, which is the
    /// path that takes `run_incremental`'s "nothing changed" early return.
    #[cfg(unix)]
    #[test]
    fn incremental_build_clears_resolved_traversal_diagnostic() {
        use std::os::unix::fs::PermissionsExt;

        let root = temp_fixture_root("traversal-incremental");
        let db_path = root.with_extension("traversal-incremental.db");
        std::fs::write(root.join("sibling.rs"), "fn sibling() {}").expect("sibling writes");
        let locked = root.join("locked");
        std::fs::create_dir_all(&locked).expect("locked dir creates");
        std::fs::set_permissions(&locked, std::fs::Permissions::from_mode(0o000))
            .expect("chmod 000");

        run_full_while_locked(root.to_str().expect("root is utf-8"), &db_path)
            .expect("initial build succeeds");
        assert_eq!(
            traversal_diagnostics(&db_path).len(),
            1,
            "precondition: the failure is persisted"
        );

        // Directory readable again; no source file touched, so the file-set
        // delta is empty.
        std::fs::set_permissions(&locked, std::fs::Permissions::from_mode(0o755))
            .expect("chmod restore");

        run_incremental(root.to_str().expect("root is utf-8"), &db_path)
            .expect("incremental build succeeds");

        assert_eq!(
            traversal_diagnostics(&db_path),
            Vec::new(),
            "a resolved traversal failure must not linger in the index"
        );

        let _ = std::fs::remove_dir_all(&root);
        let _ = std::fs::remove_file(&db_path);
    }

    #[test]
    fn deleting_non_max_rev_file_refreshes_graph_cache() {
        // CORRECTNESS-001 regression: `run_incremental`'s full path (file-set
        // changed) must eagerly rebuild `graph_cache` even when the deleted
        // file wasn't the max-rev file, since `MAX(files.rev)` is unchanged
        // by that deletion and can't be trusted alone to signal staleness.
        let root = temp_fixture_root("delete-non-max-rev");
        let db_path = root.with_extension("delete-non-max-rev.db");
        std::fs::write(root.join("a.rs"), "fn a() {}").expect("a.rs writes");
        std::fs::write(root.join("b.rs"), "fn b() { a(); }").expect("b.rs writes");
        std::fs::write(root.join("c.rs"), "fn c() { b(); }").expect("c.rs writes");

        // Initial full build: a, b, c persisted in that order (a gets the
        // lowest rev, c the highest/max rev), and the cache eagerly warmed.
        let output =
            crate::scan::run(root.to_str().expect("root is utf-8")).expect("initial scan succeeds");
        let graph = crate::resolve::resolve(&output.entities, &output.symbols, &output.files)
            .expect("initial resolve succeeds");
        crate::persist::persist(&db_path, &[output], &graph, &root)
            .expect("initial persist succeeds");
        {
            let conn = crate::db::open(&db_path).expect("db opens for warm-up");
            crate::persist::rebuild_graph_cache_full(&conn).expect("cache warms");
        }

        // Delete `a.rs` — not the max-rev file (`c.rs` is) — so `MAX(files.rev)`
        // is unaffected by the deletion.
        std::fs::remove_file(root.join("a.rs")).expect("a.rs removes");

        run_incremental(root.to_str().expect("root is utf-8"), &db_path)
            .expect("incremental build with deletion succeeds");

        let conn = crate::db::open(&db_path).expect("db reopens after incremental build");
        let max_rev = crate::persist::max_rev(&conn).expect("max_rev reads");
        let row: Option<(Vec<u8>, i64)> = conn
            .query_row("SELECT blob, rev FROM graph_cache WHERE id = 1", [], |r| {
                Ok((r.get(0)?, r.get(1)?))
            })
            .optional()
            .expect("graph_cache query runs");
        let (blob, cached_rev) = row.expect("graph_cache row still exists after the delete build");
        assert_eq!(
            cached_rev, max_rev,
            "graph_cache rev must be re-stamped to the post-delete ledger value"
        );

        let cached: crate::query::graph::Graph =
            postcard::from_bytes(&blob).expect("graph_cache blob decodes");
        let fresh = crate::query::graph::Graph::load_uncached(&conn)
            .expect("fresh SQL-scan rebuild succeeds");
        assert_eq!(
            cached, fresh,
            "graph_cache must match a from-SQL rebuild — it must not still \
             contain the deleted file's stale edges"
        );

        let _ = std::fs::remove_file(db_path);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn incremental_global_pass_matches_full_rebuild() {
        // Changed-only fixture below drives the shared scoped edge engine —
        // serialize against the other tests reading `SCOPED_EDGE_REFRESH_CALLS`.
        let _guard = crate::SCOPED_EDGE_REFRESH_TEST_LOCK
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let root = temp_fixture_root("global-pass");
        let incremental_db = root.with_extension("incremental.db");
        let full_db = root.with_extension("full.db");
        let first_source = r#"
            fn shared() {
                let a = 1;
                let b = 2;
                let c = 3;
                let d = 4;
                let e = 5;
                let f = 6;
                let g = 7;
                let h = 8;
            }
        "#;
        std::fs::write(root.join("a.rs"), first_source).expect("a.rs writes");
        std::fs::write(root.join("b.rs"), first_source).expect("b.rs writes");

        let initial =
            crate::scan::run(root.to_str().expect("root is utf-8")).expect("initial scan succeeds");
        let initial_graph =
            crate::resolve::resolve(&initial.entities, &initial.symbols, &initial.files)
                .expect("initial resolve succeeds");
        crate::persist::persist(&incremental_db, &[initial], &initial_graph, &root)
            .expect("initial persist succeeds");

        std::fs::write(
            root.join("a.rs"),
            first_source.replace("fn shared", "fn changed"),
        )
        .expect("changed a.rs writes");

        run_incremental(root.to_str().expect("root is utf-8"), &incremental_db)
            .expect("incremental build succeeds");

        let rebuilt =
            crate::scan::run(root.to_str().expect("root is utf-8")).expect("full scan succeeds");
        let rebuilt_graph =
            crate::resolve::resolve(&rebuilt.entities, &rebuilt.symbols, &rebuilt.files)
                .expect("full resolve succeeds");
        crate::persist::persist(&full_db, &[rebuilt], &rebuilt_graph, &root)
            .expect("full persist succeeds");

        let incremental = crate::db::open(&incremental_db).expect("incremental db opens");
        let full = crate::db::open(&full_db).expect("full db opens");
        for table in [
            "entities",
            "symbols",
            "resolved_edges",
            "communities",
            "clone_bands",
        ] {
            let incremental_count: i64 = incremental
                .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
                    row.get(0)
                })
                .expect("incremental count reads");
            let full_count: i64 = full
                .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
                    row.get(0)
                })
                .expect("full count reads");
            assert_eq!(
                incremental_count, full_count,
                "row count differs for {table}"
            );
        }

        let incremental_bands: Vec<String> = incremental
            .prepare("SELECT label FROM clone_bands ORDER BY label")
            .expect("incremental bands query prepares")
            .query_map([], |row| row.get(0))
            .expect("incremental bands query runs")
            .collect::<rusqlite::Result<_>>()
            .expect("incremental bands load");
        let full_bands: Vec<String> = full
            .prepare("SELECT label FROM clone_bands ORDER BY label")
            .expect("full bands query prepares")
            .query_map([], |row| row.get(0))
            .expect("full bands query runs")
            .collect::<rusqlite::Result<_>>()
            .expect("full bands load");
        assert!(!full_bands.is_empty(), "fixture must exercise clone bands");
        assert_eq!(incremental_bands, full_bands);

        let _ = std::fs::remove_file(incremental_db);
        let _ = std::fs::remove_file(full_db);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn no_change_incremental_skips_global_recompute() {
        let root = temp_fixture_root("no-change");
        let db_path = root.with_extension("no-change.db");
        std::fs::write(root.join("a.rs"), "fn a() { let x = 1; }").expect("a.rs writes");
        std::fs::write(root.join("b.rs"), "fn b() { let y = 2; }").expect("b.rs writes");

        // Initial full build.
        let output =
            crate::scan::run(root.to_str().expect("root is utf-8")).expect("initial scan succeeds");
        let graph = crate::resolve::resolve(&output.entities, &output.symbols, &output.files)
            .expect("initial resolve succeeds");
        crate::persist::persist(&db_path, &[output], &graph, &root)
            .expect("initial persist succeeds");

        let before: i64 = crate::db::open(&db_path)
            .expect("db opens")
            .query_row("SELECT COUNT(*) FROM entities", [], |row| row.get(0))
            .expect("entity count reads");

        // Incremental with nothing changed: must not reparse and must report
        // the existing counts without touching the derived layer.
        let summary = run_incremental(root.to_str().expect("root is utf-8"), &db_path)
            .expect("no-change incremental succeeds");
        assert_eq!(summary.reparsed, 0, "no files changed, nothing reparsed");
        assert_eq!(summary.unchanged, 2, "both files classified unchanged");
        assert_eq!(
            summary.entities as i64, before,
            "reported entity count matches the untouched index"
        );

        let _ = std::fs::remove_file(db_path);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn old_schema_falls_back_to_full_rebuild() {
        let root = temp_fixture_root("old-schema");
        let db_path = root.with_extension("old.db");
        std::fs::write(root.join("main.rs"), "fn main() {}").expect("source writes");
        {
            let conn = rusqlite::Connection::open(&db_path).expect("old db opens");
            conn.execute(
                "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT NOT NULL)",
                [],
            )
            .expect("old schema creates");
            conn.execute(
                "INSERT INTO files (path) VALUES (?1)",
                [root.join("main.rs").display().to_string()],
            )
            .expect("old file row inserts");
        }

        run_incremental(root.to_str().expect("root is utf-8"), &db_path)
            .expect("old schema recovers through full rebuild");
        let conn = crate::db::open(&db_path).expect("rebuilt db opens");
        let mtime_column: String = conn
            .query_row(
                "SELECT name FROM pragma_table_info('files') WHERE name = 'mtime'",
                [],
                |row| row.get(0),
            )
            .expect("rebuilt schema has mtime");
        assert_eq!(mtime_column, "mtime");

        let _ = std::fs::remove_file(db_path);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn malformed_stored_hash_falls_back_to_full_rebuild() {
        let root = temp_fixture_root("bad-hash");
        let db_path = root.with_extension("bad-hash.db");
        let source_path = root.join("main.rs");
        std::fs::write(&source_path, "fn main() {}").expect("source writes");
        let output =
            crate::scan::run(root.to_str().expect("root is utf-8")).expect("initial scan succeeds");
        let graph = crate::resolve::resolve(&output.entities, &output.symbols, &output.files)
            .expect("initial resolve succeeds");
        crate::persist::persist(&db_path, &[output], &graph, &root)
            .expect("initial persist succeeds");
        {
            let conn = crate::db::open(&db_path).expect("db opens");
            conn.execute(
                "UPDATE files SET content_hash = 'corrupt-hash' WHERE path = ?1",
                [source_path.display().to_string()],
            )
            .expect("corrupt hash writes");
        }

        run_incremental(root.to_str().expect("root is utf-8"), &db_path)
            .expect("corrupt hash recovers through full rebuild");
        let hash: String = crate::db::open(&db_path)
            .expect("rebuilt db opens")
            .query_row(
                "SELECT content_hash FROM files WHERE path = ?1",
                [source_path.display().to_string()],
                |row| row.get(0),
            )
            .expect("rebuilt hash reads");
        assert_eq!(hash.len(), 16);
        assert!(hash.bytes().all(|byte| byte.is_ascii_hexdigit()));

        let _ = std::fs::remove_file(db_path);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn schema_version_mismatch_falls_back_to_full_rebuild() {
        let root = temp_fixture_root("schema-version-mismatch");
        let db_path = root.with_extension("schema-version-mismatch.db");
        let source_path = root.join("main.rs");
        std::fs::write(&source_path, "fn main() {}").expect("source writes");
        let output =
            crate::scan::run(root.to_str().expect("root is utf-8")).expect("initial scan succeeds");
        let graph = crate::resolve::resolve(&output.entities, &output.symbols, &output.files)
            .expect("initial resolve succeeds");
        crate::persist::persist(&db_path, &[output], &graph, &root)
            .expect("initial persist succeeds");
        {
            // Simulate a database written before `SCHEMA_VERSION` existed
            // (or by an older/newer build with a different schema shape):
            // stamp a version that never matches the current constant.
            let conn = crate::db::open(&db_path).expect("db opens");
            conn.pragma_update(None, "user_version", crate::db::SCHEMA_VERSION + 1)
                .expect("user_version writes");
        }

        run_incremental(root.to_str().expect("root is utf-8"), &db_path)
            .expect("schema mismatch recovers through full rebuild");

        let conn = crate::db::open(&db_path).expect("rebuilt db opens");
        assert_eq!(
            crate::db::schema_version(&conn).expect("schema_version reads"),
            crate::db::SCHEMA_VERSION,
            "full rebuild re-stamps the current schema version"
        );
        let hash: String = conn
            .query_row(
                "SELECT content_hash FROM files WHERE path = ?1",
                [source_path.display().to_string()],
                |row| row.get(0),
            )
            .expect("rebuilt hash reads");
        assert_eq!(hash.len(), 16);

        let _ = std::fs::remove_file(db_path);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn build_version_mismatch_falls_back_to_full_rebuild() {
        // An index whose schema matches but whose `build_version` was written by
        // a different varde-code binary must be fully rebuilt — the gap
        // `SCHEMA_VERSION` alone misses (an extractor change that doesn't touch
        // the schema).
        let root = temp_fixture_root("build-version-mismatch");
        let db_path = root.with_extension("build-version-mismatch.db");
        let source_path = root.join("main.rs");
        std::fs::write(&source_path, "fn main() {}").expect("source writes");
        let output =
            crate::scan::run(root.to_str().expect("root is utf-8")).expect("initial scan succeeds");
        let graph = crate::resolve::resolve(&output.entities, &output.symbols, &output.files)
            .expect("initial resolve succeeds");
        crate::persist::persist(&db_path, &[output], &graph, &root).expect("initial persist");

        // Sanity: the fresh index is stamped with the current fingerprint, and
        // the schema is current (so this test isolates the build_version gate,
        // not the schema gate).
        {
            let conn = crate::db::open(&db_path).expect("db opens");
            assert_eq!(
                crate::db::schema_version(&conn).expect("schema reads"),
                crate::db::SCHEMA_VERSION
            );
            assert!(
                crate::persist::index_build_version_matches(&conn),
                "fresh index must carry the current build_version"
            );
            // Stamp a fingerprint no running binary would produce.
            crate::persist::set_slice_meta_value(
                &conn,
                "build_version",
                crate::db::build_version_fingerprint().wrapping_add(1),
            )
            .expect("tamper build_version");
        }

        run_incremental(root.to_str().expect("root is utf-8"), &db_path)
            .expect("build_version mismatch recovers through full rebuild");

        let conn = crate::db::open(&db_path).expect("rebuilt db opens");
        assert!(
            crate::persist::index_build_version_matches(&conn),
            "full rebuild re-stamps the current build_version"
        );

        let _ = std::fs::remove_file(db_path);
        let _ = std::fs::remove_dir_all(root);
    }

    /// Changed-only delta (no new/deleted files): `run_incremental` must call
    /// the shared scoped edge engine (`slice::run_scoped_edge_refresh`)
    /// rather than fully re-deriving edges/communities/clone-bands.
    /// `SCOPED_EDGE_REFRESH_CALLS` counts every invocation of that function
    /// regardless of caller, so a delta proves it ran here. Run this test
    /// under a `build::`-scoped filter (as the task's verification command
    /// does) — the counter is process-global and racy against any other test
    /// exercising the same shared engine (e.g. `slice::freshen_edges`'s own
    /// scoped-path tests) running concurrently in the same binary.
    #[test]
    fn changed_only_delta_uses_shared_scoped_engine() {
        let _guard = crate::SCOPED_EDGE_REFRESH_TEST_LOCK
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let root = temp_fixture_root("changed-only-scoped");
        let db_path = root.with_extension("changed-only-scoped.db");
        let first_source = "fn shared() { let a = 1; let b = 2; }";
        std::fs::write(root.join("a.rs"), first_source).expect("a.rs writes");
        std::fs::write(root.join("b.rs"), first_source).expect("b.rs writes");

        let output =
            crate::scan::run(root.to_str().expect("root is utf-8")).expect("initial scan succeeds");
        let graph = crate::resolve::resolve(&output.entities, &output.symbols, &output.files)
            .expect("initial resolve succeeds");
        crate::persist::persist(&db_path, &[output], &graph, &root)
            .expect("initial persist succeeds");

        // Only a.rs's content changes — no file is added or removed, so
        // `classify_files` reports `Changed` only.
        std::fs::write(
            root.join("a.rs"),
            first_source.replace("fn shared", "fn changed"),
        )
        .expect("changed a.rs writes");

        let calls_before =
            crate::SCOPED_EDGE_REFRESH_CALLS.load(std::sync::atomic::Ordering::Relaxed);
        run_incremental(root.to_str().expect("root is utf-8"), &db_path)
            .expect("changed-only incremental build succeeds");
        let calls_after =
            crate::SCOPED_EDGE_REFRESH_CALLS.load(std::sync::atomic::Ordering::Relaxed);

        assert!(
            calls_after > calls_before,
            "changed-only delta must call the shared scoped edge engine \
             (slice::run_scoped_edge_refresh), not fully re-derive edges"
        );

        let _ = std::fs::remove_file(db_path);
        let _ = std::fs::remove_dir_all(root);
    }

    /// A `New` or `Deleted` file forces the full re-derivation path (mirrors
    /// `slice::freshen_edges`'s `file_set_changed` rule) instead of the
    /// scoped engine — `SCOPED_EDGE_REFRESH_CALLS` must not advance.
    #[test]
    fn new_file_forces_full_rederivation() {
        let _guard = crate::SCOPED_EDGE_REFRESH_TEST_LOCK
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let root = temp_fixture_root("new-file-full");
        let db_path = root.with_extension("new-file-full.db");
        let first_source = "fn shared() { let a = 1; let b = 2; }";
        std::fs::write(root.join("a.rs"), first_source).expect("a.rs writes");

        let output =
            crate::scan::run(root.to_str().expect("root is utf-8")).expect("initial scan succeeds");
        let graph = crate::resolve::resolve(&output.entities, &output.symbols, &output.files)
            .expect("initial resolve succeeds");
        crate::persist::persist(&db_path, &[output], &graph, &root)
            .expect("initial persist succeeds");

        // A newly added file makes `classify_files` report a `New` entry —
        // the file *set* changed, which must force the full path.
        std::fs::write(root.join("b.rs"), first_source).expect("new b.rs writes");

        let calls_before =
            crate::SCOPED_EDGE_REFRESH_CALLS.load(std::sync::atomic::Ordering::Relaxed);
        run_incremental(root.to_str().expect("root is utf-8"), &db_path)
            .expect("new-file incremental build succeeds");
        let calls_after =
            crate::SCOPED_EDGE_REFRESH_CALLS.load(std::sync::atomic::Ordering::Relaxed);

        assert_eq!(
            calls_after, calls_before,
            "a new/deleted file must take the full re-derivation path and \
             never call the shared scoped edge engine"
        );

        let _ = std::fs::remove_file(db_path);
        let _ = std::fs::remove_dir_all(root);
    }
}
