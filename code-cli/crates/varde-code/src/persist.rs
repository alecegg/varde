//! Persistence entry point: writes everything `parsing-extraction` and
//! `resolution-graph-algorithms` produce into varde-code's own SQLite store.
//!
//! Write model: full rebuild per run. [`persist`] opens the database via
//! [`crate::db::open_or_rebuild`] (which drops and recreates the schema),
//! writes every table from the given `ExtractOutput`/`ResolvedGraph`, and
//! commits as one transaction. `query-surface` reads this store back.

use std::collections::{HashMap, HashSet};
use std::path::Path;

use anyhow::Result;
use rusqlite::OptionalExtension;

use crate::complexity::{ComplexityConfidence, ComplexityConfidenceReason, FunctionComplexity};
use crate::model::{Entity, EntityKind, ExtractOutput, Span, Symbol, SymbolKind};
use crate::resolve::{EdgeTarget, FileNode, ResolvedEdge, ResolvedGraph};

/// Per-file state loaded from a stored `files` row.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StoredFileState {
    pub path: String,
    pub mtime: i64,
    pub size: i64,
    pub content_hash: String,
}

/// Encoding version for persisted function-level complexity metrics.
const FUNCTION_METRIC_VERSION: i64 = 2;

/// Reconstructed raw state used by the global resolution pass.
pub(crate) struct PersistedState {
    pub entities: Vec<Entity>,
    pub entity_ids: Vec<i64>,
    pub symbols: Vec<Symbol>,
    pub files: Vec<String>,
    pub file_ids: Vec<i64>,
    /// db `files.id` → flat index into [`PersistedState::files`]/[`file_ids`].
    /// Built once in [`query_persisted_state`]; the scoped edge refresh uses it
    /// to map stale db ids to flat emit indices in O(1) instead of re-scanning
    /// `file_ids` linearly per id.
    pub file_index: HashMap<i64, u32>,
    pub diagnostics: usize,
}

pub(crate) fn load_file_states(conn: &rusqlite::Connection) -> Result<Vec<StoredFileState>> {
    let mut stmt =
        conn.prepare("SELECT path, mtime, size, content_hash FROM files ORDER BY path")?;
    let rows = stmt.query_map([], |row| {
        Ok(StoredFileState {
            path: row.get(0)?,
            mtime: row.get(1)?,
            size: row.get(2)?,
            content_hash: row.get(3)?,
        })
    })?;
    rows.collect::<rusqlite::Result<Vec<_>>>()
        .map_err(Into::into)
}

pub(crate) fn load_file_ids(conn: &rusqlite::Connection) -> Result<HashMap<String, i64>> {
    let mut stmt = conn.prepare("SELECT path, id FROM files")?;
    let rows = stmt.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
    rows.collect::<rusqlite::Result<HashMap<_, _>>>()
        .map_err(Into::into)
}

pub(crate) fn insert_new_files(conn: &rusqlite::Connection, paths: &[String]) -> Result<()> {
    for path in paths {
        // Insert the row with schema defaults (mtime/size/content_hash 0/''):
        // `update_file_states` backfills the scan-time metadata for every
        // changed file — new files included — immediately after re-scan, so
        // re-reading the bytes here would be wasted I/O.
        conn.execute(
            "INSERT INTO files (path) VALUES (?1)",
            rusqlite::params![path],
        )?;
    }
    Ok(())
}

/// Build the `?`-placeholder list for an `IN (...)` clause and the matching
/// parameter slice for `ids`. Kept in one place because the pattern is
/// fiddly (type annotations, `as &dyn ToSql` casts) and appears at every
/// scoped-`IN` site — see CORRECTNESS-104 for the variable-limit note and
/// the scoped-path cap in `slice::freshen_edges`.
pub(crate) fn in_clause(ids: &[i64]) -> (String, Vec<&dyn rusqlite::ToSql>) {
    let placeholders = vec!["?"; ids.len()].join(", ");
    let params: Vec<&dyn rusqlite::ToSql> =
        ids.iter().map(|id| id as &dyn rusqlite::ToSql).collect();
    (placeholders, params)
}

pub(crate) fn delete_deleted_files(conn: &rusqlite::Connection, deleted_ids: &[i64]) -> Result<()> {
    if deleted_ids.is_empty() {
        return Ok(());
    }
    for ids in deleted_ids.chunks(400) {
        delete_deleted_files_batch(conn, ids)?;
    }
    // Drop now-orphaned communities/clone bands after every batch completes.
    conn.execute(
        "DELETE FROM communities
         WHERE id NOT IN (SELECT DISTINCT community_id FROM community_members)",
        [],
    )?;
    conn.execute(
        "DELETE FROM clone_bands
         WHERE id NOT IN (SELECT DISTINCT band_id FROM clone_band_members)",
        [],
    )?;
    Ok(())
}

fn delete_deleted_files_batch(conn: &rusqlite::Connection, deleted_ids: &[i64]) -> Result<()> {
    let (placeholders, params) = in_clause(deleted_ids);
    conn.execute(
        &format!(
            "DELETE FROM clone_band_members
             WHERE entity_id IN (SELECT id FROM entities WHERE file_id IN ({placeholders}))"
        ),
        params.as_slice(),
    )?;
    conn.execute(
        &format!("DELETE FROM community_members WHERE file_id IN ({placeholders})"),
        params.as_slice(),
    )?;
    conn.execute(
        &format!(
            "DELETE FROM resolved_edges
             WHERE from_file_id IN ({placeholders}) OR to_file_id IN ({placeholders})"
        ),
        params
            .iter()
            .chain(params.iter())
            .copied()
            .collect::<Vec<_>>()
            .as_slice(),
    )?;
    conn.execute(
        &format!("DELETE FROM diagnostics WHERE file_id IN ({placeholders})"),
        params.as_slice(),
    )?;
    conn.execute(
        &format!("DELETE FROM function_metrics WHERE file_id IN ({placeholders})"),
        params.as_slice(),
    )?;
    conn.execute(
        &format!("DELETE FROM symbols WHERE file_id IN ({placeholders})"),
        params.as_slice(),
    )?;
    conn.execute(
        &format!("DELETE FROM entities WHERE file_id IN ({placeholders})"),
        params.as_slice(),
    )?;
    conn.execute(
        &format!("DELETE FROM files WHERE id IN ({placeholders})"),
        params.as_slice(),
    )?;
    Ok(())
}

pub(crate) fn delete_global_rows(conn: &rusqlite::Connection) -> Result<()> {
    conn.execute("DELETE FROM clone_band_members", [])?;
    conn.execute("DELETE FROM clone_bands", [])?;
    conn.execute("DELETE FROM community_members", [])?;
    conn.execute("DELETE FROM communities", [])?;
    conn.execute("DELETE FROM resolved_edges", [])?;
    conn.execute(
        "UPDATE files SET community_id = NULL, fan_in = 0, fan_out = 0",
        [],
    )?;
    Ok(())
}

/// Cheap row counts for a fully-persisted index, read via `COUNT(*)` without
/// materializing any rows. The incremental build's no-change early-exit uses
/// this to report a `BuildSummary` without paying for the full
/// [`query_persisted_state`] read-back.
pub(crate) struct IndexCounts {
    pub entities: usize,
    pub symbols: usize,
    pub diagnostics: usize,
}

/// Load the stored `files` row for one path, or `None` if absent. The
/// build-on-read freshness check (§0) compares this against the file's current
/// on-disk metadata to decide whether its slice needs a targeted rebuild.
pub(crate) fn load_file_state(
    conn: &rusqlite::Connection,
    path: &str,
) -> Result<Option<StoredFileState>> {
    Ok(conn
        .query_row(
            "SELECT path, mtime, size, content_hash FROM files WHERE path = ?1",
            [path],
            |row| {
                Ok(StoredFileState {
                    path: row.get(0)?,
                    mtime: row.get(1)?,
                    size: row.get(2)?,
                    content_hash: row.get(3)?,
                })
            },
        )
        .optional()?)
}

/// Bring one file's raw structural slice — its `entities`/`symbols`/
/// `diagnostics` rows plus `files` metadata — up to date from a fresh
/// single-file scan, WITHOUT touching the global derived layer
/// (edges/communities/clones/fan). Used by build-on-read query modes that read
/// only per-file rows (§0, step 1). `output` must be a single-file scan whose
/// `files[0]` is the path being refreshed.
///
/// Cross-slice note: reinserting a file's entities changes their rowids, so
/// edge/clone rows referencing the old ids go stale — that is expected. Each
/// tool freshens the slice it reads; the edges/global slices are rebuilt by
/// their own consumers' `ensure_fresh`, not here.
pub(crate) fn refresh_file_slice(
    conn: &rusqlite::Connection,
    output: &ExtractOutput,
) -> Result<()> {
    let path = output
        .files
        .first()
        .ok_or_else(|| anyhow::anyhow!("refresh_file_slice needs a single-file scan"))?;
    let tx = conn.unchecked_transaction()?;
    let file_db_id = ensure_file_row(&tx, path)?;
    clear_raw_file_rows(&tx, file_db_id)?;
    let file_ids = FileIds {
        flat: vec![file_db_id],
        offsets: vec![0],
    };
    let out = std::slice::from_ref(output);
    let (_entity_ids, complexity_counts) = write_entities(&tx, out, &file_ids)?;
    write_symbols(&tx, out, &file_ids)?;
    write_diagnostics(&tx, out, &file_ids)?;
    write_function_metrics(&tx, out, &file_ids)?;
    write_complexity(&tx, &file_ids, &complexity_counts)?;
    update_file_metadata_and_revision(&tx, output, file_db_id)?;
    tx.commit()?;
    Ok(())
}

fn ensure_file_row(conn: &rusqlite::Connection, path: &str) -> Result<i64> {
    if let Some(id) = conn
        .query_row("SELECT id FROM files WHERE path = ?1", [path], |row| {
            row.get(0)
        })
        .optional()?
    {
        return Ok(id);
    }
    conn.execute("INSERT INTO files (path) VALUES (?1)", [path])?;
    Ok(conn.last_insert_rowid())
}

fn clear_raw_file_rows(conn: &rusqlite::Connection, file_id: i64) -> Result<()> {
    for sql in [
        "DELETE FROM entities WHERE file_id = ?1",
        "DELETE FROM symbols WHERE file_id = ?1",
        "DELETE FROM diagnostics WHERE file_id = ?1",
        "DELETE FROM function_metrics WHERE file_id = ?1",
    ] {
        conn.execute(sql, [file_id])?;
    }
    Ok(())
}

fn update_file_metadata_and_revision(
    conn: &rusqlite::Connection,
    output: &ExtractOutput,
    file_id: i64,
) -> Result<()> {
    if let Some(meta) = output.file_meta.first() {
        conn.execute(
            "UPDATE files SET mtime = ?1, size = ?2, content_hash = ?3 WHERE id = ?4",
            rusqlite::params![meta.mtime, meta.size, meta.content_hash, file_id],
        )?;
    }
    let rev = next_rev(conn)?;
    conn.execute(
        "UPDATE files SET rev = ?1 WHERE id = ?2",
        rusqlite::params![rev, file_id],
    )?;
    Ok(())
}

/// Store a `slice_meta` integer value under `key` (upsert).
pub(crate) fn set_slice_meta_value(
    conn: &rusqlite::Connection,
    key: &str,
    value: i64,
) -> Result<()> {
    conn.execute(
        "INSERT INTO slice_meta (key, value) VALUES (?1, ?2)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        rusqlite::params![key, value],
    )?;
    Ok(())
}

/// Read a `slice_meta` integer value, `None` when absent.
pub(crate) fn slice_meta_value(conn: &rusqlite::Connection, key: &str) -> Result<Option<i64>> {
    Ok(conn
        .query_row("SELECT value FROM slice_meta WHERE key = ?1", [key], |r| {
            r.get(0)
        })
        .optional()?)
}

/// Whether an existing index was built by a varde-code binary compatible with
/// the one now running, per the `build_version` fingerprint (see
/// [`crate::db::build_version_fingerprint`]). `false` for an index that predates
/// the fingerprint (no `build_version` row) or was built by a different binary,
/// so the incremental build/build-on-read paths force a full rebuild rather
/// than serving rows the current extractor would produce differently. A read
/// error is treated as a mismatch (safe: triggers a rebuild).
pub(crate) fn index_build_version_matches(conn: &rusqlite::Connection) -> bool {
    slice_meta_value(conn, "build_version").ok().flatten()
        == Some(crate::db::build_version_fingerprint())
}

/// The next monotonic revision for a raw-slice write, from the `slice_meta`
/// counter (seeded from the current `MAX(files.rev)` so a database populated
/// before the counter existed still continues monotonically).
pub(crate) fn next_rev(conn: &rusqlite::Connection) -> Result<i64> {
    let current: Option<i64> = conn
        .query_row(
            "SELECT value FROM slice_meta WHERE key = 'next_rev'",
            [],
            |r| r.get(0),
        )
        .optional()?;
    let next = match current {
        Some(v) => v + 1,
        None => {
            let max: i64 =
                conn.query_row("SELECT COALESCE(MAX(rev), 0) FROM files", [], |r| r.get(0))?;
            max + 1
        }
    };
    set_slice_meta_value(conn, "next_rev", next)?;
    Ok(next)
}

/// The highest `files.rev` currently persisted (0 on an empty index).
pub(crate) fn max_rev(conn: &rusqlite::Connection) -> Result<i64> {
    Ok(conn.query_row("SELECT COALESCE(MAX(rev), 0) FROM files", [], |r| r.get(0))?)
}

/// Record a derived slice as freshly built against `built_through_rev`.
pub(crate) fn set_slice_state(
    conn: &rusqlite::Connection,
    slice: &str,
    built_through_rev: i64,
) -> Result<()> {
    conn.execute(
        "INSERT INTO slice_state (slice, built_through_rev, schema_version)
         VALUES (?1, ?2, ?3)
         ON CONFLICT(slice) DO UPDATE SET
             built_through_rev = excluded.built_through_rev,
             schema_version = excluded.schema_version",
        rusqlite::params![slice, built_through_rev, crate::db::SCHEMA_VERSION],
    )?;
    Ok(())
}

/// Mark every derived slice (imports/edges/global) fresh against the current
/// `max(files.rev)`. Called after a full or incremental build writes the whole
/// derived layer, so later build-on-read calls see the derived slices as up to
/// date (no needless recompute).
pub(crate) fn record_all_slices_fresh(conn: &rusqlite::Connection) -> Result<()> {
    let rev = max_rev(conn)?;
    for slice in ["imports", "edges", "global"] {
        set_slice_state(conn, slice, rev)?;
    }
    Ok(())
}

/// Drop the imports/edges/global ledger rows entirely, so the next freshen
/// treats each as never-built. Used when a file-set change (add/delete)
/// can't be signaled by `max(files.rev)` alone.
pub(crate) fn invalidate_derived_slice_state(conn: &rusqlite::Connection) -> Result<()> {
    conn.execute(
        "DELETE FROM slice_state WHERE slice IN ('imports', 'edges', 'global')",
        [],
    )?;
    Ok(())
}

/// Read a derived slice's `built_through_rev` from `slice_state`, `None` when
/// it has never been ledgered (build-on-miss → rebuild).
pub(crate) fn slice_built_through_rev(
    conn: &rusqlite::Connection,
    slice: &str,
) -> Result<Option<i64>> {
    Ok(conn
        .query_row(
            "SELECT built_through_rev FROM slice_state WHERE slice = ?1",
            [slice],
            |r| r.get(0),
        )
        .optional()?)
}

/// Rewrite only the `Import`-kind rows of `resolved_edges` (the imports slice).
/// Call edges are left untouched — the `edges` slice owns those.
///
/// Only valid immediately after a raw re-parse of exactly the files these
/// import edges came from, in the same transaction/pass that just wrote
/// those files' entity rowids — `state.entity_ids` must already reflect the
/// fresh rowids for `edge.from_entity` to resolve correctly (mirrors
/// `rewrite_edges_for_files`'s `from_entity_id` lookup below).
pub(crate) fn rewrite_import_edges(
    conn: &rusqlite::Connection,
    state: &PersistedState,
    import_edges: &[ResolvedEdge],
) -> Result<()> {
    let tx = conn.unchecked_transaction()?;
    tx.execute(
        "DELETE FROM resolved_edges WHERE kind = ?1",
        [crate::resolve::EdgeKind::Import.as_i64()],
    )?;
    let mut stmt = conn.prepare(
        "INSERT INTO resolved_edges (from_file_id, from_entity_id, to_file_id, kind, resolved)
         VALUES (?1, ?2, ?3, ?4, ?5)",
    )?;
    for edge in import_edges {
        let from = state.file_ids[edge.from as usize];
        let from_entity = edge
            .from_entity
            .and_then(|eidx| entity_id_at(&state.entity_ids, eidx as usize));
        let to = if edge.resolved {
            match edge.to {
                EdgeTarget::File(fid) => Some(state.file_ids[fid as usize]),
                _ => None,
            }
        } else {
            None
        };
        stmt.execute(rusqlite::params![
            from,
            from_entity,
            to,
            edge.kind.as_i64(),
            edge.resolved as i64
        ])?;
    }
    drop(stmt);
    tx.commit()?;
    Ok(())
}

/// Rewrite every `resolved_edges` row (the edges slice) from a fresh
/// edge-layer resolve, and denormalize the fresh fan-in/fan-out back onto
/// `files`.
///
/// Unlike [`rewrite_import_edges`] this deletes **all** rows, not just the
/// Import kind: call edges carry `from_entity_id` references to entity
/// rowids, and a raw re-parse reassigns rowids — so any raw advance
/// invalidates the whole edge set. `nodes` carries the fan metrics computed
/// by the same resolve (import + call edges both contribute), so they are
/// rewritten here in the same transaction as the edges they are derived
/// from. `community_id` is deliberately untouched — that column belongs to
/// the global slice (Phase 3).
pub(crate) fn rewrite_edges(
    conn: &rusqlite::Connection,
    state: &PersistedState,
    edges: &[ResolvedEdge],
    nodes: &[FileNode],
) -> Result<()> {
    let tx = conn.unchecked_transaction()?;
    tx.execute("DELETE FROM resolved_edges", [])?;
    let mut stmt = tx.prepare(
        "INSERT INTO resolved_edges (from_file_id, from_entity_id, to_file_id, kind, resolved)
         VALUES (?1, ?2, ?3, ?4, ?5)",
    )?;
    for edge in edges {
        let from = state.file_ids[edge.from as usize];
        let from_entity = edge
            .from_entity
            .and_then(|eidx| entity_id_at(&state.entity_ids, eidx as usize));
        let to = if edge.resolved {
            match edge.to {
                EdgeTarget::File(fid) => Some(state.file_ids[fid as usize]),
                EdgeTarget::Entity(entity_id) => {
                    let file_index = state.entities[entity_id as usize].file_id as usize;
                    Some(state.file_ids[file_index])
                }
                EdgeTarget::Unknown => None,
            }
        } else {
            None
        };
        stmt.execute(rusqlite::params![
            from,
            from_entity,
            to,
            edge.kind.as_i64(),
            edge.resolved as i64
        ])?;
    }
    drop(stmt);

    let mut file_stmt = tx.prepare("UPDATE files SET fan_in = ?1, fan_out = ?2 WHERE id = ?3")?;
    for (index, node) in nodes.iter().enumerate() {
        file_stmt.execute(rusqlite::params![
            node.fan_in,
            node.fan_out,
            state.file_ids[index]
        ])?;
    }
    drop(file_stmt);

    // A full edge re-resolve recomputes every file's outgoing edges, so the
    // per-file edge ledger is stamped at every file's own rev.
    tx.execute("UPDATE files SET edges_built_rev = rev", [])?;

    tx.commit()?;
    Ok(())
}

/// Read the cached [`crate::query::graph::Graph`] from `graph_cache`, if any
/// row is present. `None` when the cache hasn't been written yet — callers
/// treat that as "nothing to patch", not an error.
pub(crate) fn read_graph_cache(
    conn: &rusqlite::Connection,
) -> Result<Option<crate::query::graph::Graph>> {
    let blob: Option<Vec<u8>> = conn
        .query_row("SELECT blob FROM graph_cache WHERE id = 1", [], |r| {
            r.get(0)
        })
        .optional()?;
    let Some(blob) = blob else {
        return Ok(None);
    };
    let graph: crate::query::graph::Graph =
        postcard::from_bytes(&blob).map_err(|e| anyhow::anyhow!("graph_cache decode: {e}"))?;
    Ok(Some(graph))
}

/// Upsert `graph` into the single-row `graph_cache` table, stamping `rev`
/// with [`max_rev`] — the same ledger value `freshen_edges` compares against
/// `slice_state.built_through_rev` to decide edges-slice freshness. Stamping
/// the cache with that same value (rather than an independent counter) is
/// what lets a reader (`Graph::load`) do a valid freshness check: a stored
/// `graph_cache.rev == max_rev(conn)` means the cached adjacency reflects
/// every file revision written so far.
pub(crate) fn write_graph_cache(
    conn: &rusqlite::Connection,
    graph: &crate::query::graph::Graph,
) -> Result<()> {
    let blob =
        postcard::to_allocvec(graph).map_err(|e| anyhow::anyhow!("graph_cache encode: {e}"))?;
    let rev = max_rev(conn)?;
    conn.execute(
        "INSERT INTO graph_cache (id, blob, rev) VALUES (1, ?1, ?2)
         ON CONFLICT(id) DO UPDATE SET blob = excluded.blob, rev = excluded.rev",
        rusqlite::params![blob, rev],
    )?;
    Ok(())
}

/// Read the cached [`crate::query::graph::Graph`] only if its stored `rev`
/// matches the current ledger value ([`max_rev`]) — the same freshness test
/// `freshen_edges` uses for the edges slice. Returns `None` (never an error)
/// on a missing row, a stale/mismatched `rev`, or a decode failure:
/// all three are treated identically by the caller ([`crate::query::graph::
/// Graph::load`]) as "no usable cache, fall back to the full rebuild".
pub(crate) fn read_graph_cache_if_fresh(
    conn: &rusqlite::Connection,
) -> Result<Option<crate::query::graph::Graph>> {
    let row: Option<(Vec<u8>, i64)> = conn
        .query_row("SELECT blob, rev FROM graph_cache WHERE id = 1", [], |r| {
            Ok((r.get(0)?, r.get(1)?))
        })
        .optional()?;
    let Some((blob, rev)) = row else {
        return Ok(None);
    };
    if rev != max_rev(conn)? {
        return Ok(None);
    }
    let decoded: std::result::Result<crate::query::graph::Graph, _> = postcard::from_bytes(&blob);
    Ok(decoded.ok())
}

/// Rebuild the `graph_cache` row from scratch by reading the just-persisted
/// full adjacency back from SQL. Called after a full edge re-resolve
/// ([`rewrite_edges`]) commits, where the whole `resolved_edges`/`files`
/// table is already exactly what a fresh [`crate::query::graph::Graph::load`]
/// would see, so re-deriving directly from the resolve output would just
/// duplicate that read.
pub(crate) fn rebuild_graph_cache_full(conn: &rusqlite::Connection) -> Result<()> {
    let graph = crate::query::graph::Graph::load_uncached(conn).map_err(anyhow::Error::from)?;
    write_graph_cache(conn, &graph)
}

/// Patch the cached `Graph`'s `out`/`inc` maps to reflect a scoped edge
/// refresh, without re-deriving the whole graph from SQL. For each rescoped
/// `from` file: drop its old outgoing entries (and the matching incoming
/// backlinks) from the cache, then insert the freshly resolved `edges`
/// (already scoped to exactly these files by the caller). No-ops when no
/// `graph_cache` row exists yet — nothing to patch.
pub(crate) fn patch_graph_cache_scoped(
    conn: &rusqlite::Connection,
    state: &PersistedState,
    refresh: &crate::resolve::ScopedEdgeRefresh,
    edges: &[ResolvedEdge],
) -> Result<()> {
    let Some(mut graph) = read_graph_cache(conn)? else {
        return Ok(());
    };
    let mut removals: HashMap<i64, HashSet<i64>> = HashMap::new();
    for &from in &refresh.file_ids {
        for to in graph.take_out(from) {
            removals.entry(to).or_default().insert(from);
        }
    }
    for (to, sources) in removals {
        graph.remove_incoming(to, &sources);
    }
    for edge in edges {
        if !edge.resolved {
            continue;
        }
        let from = state.file_ids[edge.from as usize];
        let to = match edge.to {
            EdgeTarget::File(fid) => Some(state.file_ids[fid as usize]),
            EdgeTarget::Entity(entity_id) => {
                let file_index = state.entities[entity_id as usize].file_id as usize;
                Some(state.file_ids[file_index])
            }
            EdgeTarget::Unknown => None,
        };
        if let Some(to) = to {
            graph.push_edge(from, to);
        }
    }
    write_graph_cache(conn, &graph)
}

/// Rewrite only the `resolved_edges` rows for the given `from_file_id`s (the
/// scoped re-resolve set), and apply the fan denorm as a **delta** instead of
/// a full recompute: `fan_out` of each rescoped file is set directly from its
/// new resolved-edge count; `fan_in` of every target that left the edge set is
/// decremented and every target that entered is incremented — computed and
/// applied inside the same transaction as the delete+insert, so a partial
/// failure can never double-count or drop a target.
///
/// `edges` must be the freshly resolved edges for exactly these files (from
/// [`crate::resolve::resolve_edges_only_scoped`]). Non-rescoped files' edges
/// and fan values are untouched — they are provably unchanged (their own
/// content and their direct targets' export sets didn't change). `fan_in` of a
/// target only changes by the scoped files' edge deltas, since non-scoped
/// files' contributions are still in the table. Stamps `files.edges_built_rev`
/// to each rescoped file's own `rev` (the per-file edge ledger).
pub(crate) fn rewrite_edges_for_files(
    conn: &rusqlite::Connection,
    state: &PersistedState,
    refresh: &crate::resolve::ScopedEdgeRefresh,
    edges: &[ResolvedEdge],
) -> Result<()> {
    let file_ids = &refresh.file_ids;
    if file_ids.is_empty() {
        return Ok(());
    }
    let tx = conn.unchecked_transaction()?;
    let (placeholders, params) = in_clause(file_ids);
    let old_incoming = scoped_incoming_counts(&tx, &placeholders, &params)?;
    tx.execute(
        &format!("DELETE FROM resolved_edges WHERE from_file_id IN ({placeholders})"),
        params.as_slice(),
    )?;
    let (new_outgoing, new_incoming) = insert_scoped_edges(&tx, state, edges)?;
    apply_fan_deltas(&tx, file_ids, &old_incoming, &new_outgoing, &new_incoming)?;
    tx.execute(
        &format!("UPDATE files SET edges_built_rev = rev WHERE id IN ({placeholders})"),
        params.as_slice(),
    )?;
    patch_graph_cache_scoped(&tx, state, refresh, edges)?;
    tx.commit()?;
    Ok(())
}

type FanCounts = std::collections::HashMap<i64, i64>;

fn scoped_incoming_counts(
    conn: &rusqlite::Connection,
    placeholders: &str,
    params: &[&dyn rusqlite::ToSql],
) -> Result<FanCounts> {
    let mut counts = FanCounts::new();
    let mut stmt = conn.prepare(&format!(
        "SELECT to_file_id FROM resolved_edges
         WHERE from_file_id IN ({placeholders}) AND resolved = 1"
    ))?;
    for row in stmt.query_map(params, |row| row.get::<_, Option<i64>>(0))? {
        if let Some(target) = row? {
            *counts.entry(target).or_insert(0) += 1;
        }
    }
    Ok(counts)
}

fn insert_scoped_edges(
    conn: &rusqlite::Connection,
    state: &PersistedState,
    edges: &[ResolvedEdge],
) -> Result<(FanCounts, FanCounts)> {
    let mut stmt = conn.prepare(
        "INSERT INTO resolved_edges (from_file_id, from_entity_id, to_file_id, kind, resolved)
         VALUES (?1, ?2, ?3, ?4, ?5)",
    )?;
    let mut outgoing = FanCounts::new();
    let mut incoming = FanCounts::new();
    for edge in edges {
        let from = state.file_ids[edge.from as usize];
        let from_entity = edge
            .from_entity
            .and_then(|eidx| entity_id_at(&state.entity_ids, eidx as usize));
        let to = if edge.resolved {
            match edge.to {
                EdgeTarget::File(fid) => Some(state.file_ids[fid as usize]),
                EdgeTarget::Entity(entity_id) => {
                    let file_index = state.entities[entity_id as usize].file_id as usize;
                    Some(state.file_ids[file_index])
                }
                EdgeTarget::Unknown => None,
            }
        } else {
            None
        };
        stmt.execute(rusqlite::params![
            from,
            from_entity,
            to,
            edge.kind.as_i64(),
            edge.resolved as i64
        ])?;
        if edge.resolved {
            *outgoing.entry(from).or_insert(0) += 1;
            if let Some(to) = to {
                *incoming.entry(to).or_insert(0) += 1;
            }
        }
    }
    Ok((outgoing, incoming))
}

fn apply_fan_deltas(
    conn: &rusqlite::Connection,
    file_ids: &[i64],
    old_incoming: &FanCounts,
    new_outgoing: &FanCounts,
    new_incoming: &FanCounts,
) -> Result<()> {
    let mut file_stmt =
        conn.prepare("UPDATE files SET fan_in = fan_in + ?1, fan_out = ?2 WHERE id = ?3")?;
    for &file_id in file_ids {
        let delta_out = new_outgoing.get(&file_id).copied().unwrap_or(0);
        let delta_in = new_incoming.get(&file_id).copied().unwrap_or(0)
            - old_incoming.get(&file_id).copied().unwrap_or(0);
        file_stmt.execute(rusqlite::params![delta_in, delta_out, file_id])?;
    }
    let mut target_stmt = conn.prepare("UPDATE files SET fan_in = fan_in + ?1 WHERE id = ?2")?;
    let targets: std::collections::BTreeSet<i64> = old_incoming
        .keys()
        .chain(new_incoming.keys())
        .copied()
        .collect();
    // O(1) membership for the "target isn't itself a scoped emitter" guard
    // (the linear `contains` was O(|scope|) per target in the hot path).
    let scope: std::collections::HashSet<i64> = file_ids.iter().copied().collect();
    for target in targets {
        let delta_in = new_incoming.get(&target).copied().unwrap_or(0)
            - old_incoming.get(&target).copied().unwrap_or(0);
        if delta_in != 0 && !scope.contains(&target) {
            target_stmt.execute(rusqlite::params![delta_in, target])?;
        }
    }
    Ok(())
}

/// Rewrite only the global slice — `communities`, `community_members`,
/// `clone_bands`, `clone_band_members`, and the `community_id` (plus fan)
/// denorm on `files` — from a fresh full [`crate::resolve::resolve`].
///
/// Unlike [`persist_global_graph`] this leaves `resolved_edges` untouched (the
/// edges slice owns those rows) and does not ledger the other slices. The
/// caller (`slice::freshen_global`) guarantees the edges slice is fresh first,
/// so the fan values written here are the same ones the edges slice computed.
pub(crate) fn rewrite_global(
    conn: &rusqlite::Connection,
    state: &PersistedState,
    graph: &ResolvedGraph,
) -> Result<()> {
    anyhow::ensure!(
        graph.nodes.len() == state.file_ids.len(),
        "resolved graph nodes must match persisted files"
    );
    let tx = conn.unchecked_transaction()?;
    tx.execute("DELETE FROM clone_band_members", [])?;
    tx.execute("DELETE FROM clone_bands", [])?;
    tx.execute("DELETE FROM community_members", [])?;
    tx.execute("DELETE FROM communities", [])?;
    tx.execute("UPDATE files SET community_id = NULL", [])?;
    let file_ids = FileIds {
        flat: state.file_ids.clone(),
        offsets: vec![0],
    };
    write_communities(&tx, graph, &file_ids)?;
    write_clone_bands(&tx, graph, &state.entity_ids)?;
    tx.commit()?;
    Ok(())
}

/// Rewrite `files.churn` from a precomputed path → count map (the churn slice).
pub(crate) fn set_churn_batch(
    conn: &rusqlite::Connection,
    counts: &HashMap<String, u32>,
) -> Result<()> {
    let tx = conn.unchecked_transaction()?;
    {
        let mut stmt = tx.prepare("UPDATE files SET churn = ?1 WHERE path = ?2")?;
        for (path, count) in counts {
            stmt.execute(rusqlite::params![*count, path])?;
        }
    }
    tx.commit()?;
    Ok(())
}

pub(crate) fn index_counts(conn: &rusqlite::Connection) -> Result<IndexCounts> {
    let count = |table: &str| -> Result<usize> {
        let n: i64 = conn.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
            row.get(0)
        })?;
        Ok(n as usize)
    };
    Ok(IndexCounts {
        entities: count("entities")?,
        symbols: count("symbols")?,
        diagnostics: count("diagnostics")?,
    })
}

/// Read persisted raw state back into memory. `include_symbols = false` skips
/// the (potentially multi-million-row) symbols deserialization for callers that
/// only feed `resolve`/`persist_global_graph` — neither of which reads symbols
/// — leaving `PersistedState::symbols` empty.
pub(crate) fn query_persisted_state(
    conn: &rusqlite::Connection,
    include_symbols: bool,
) -> Result<PersistedState> {
    let files_with_ids = load_persisted_files(conn)?;
    let file_index = files_with_ids
        .iter()
        .enumerate()
        .map(|(index, (id, _))| (*id, index as u32))
        .collect();
    let (entity_ids, entities) = load_persisted_entities(conn, &file_index)?;
    let symbols = if include_symbols {
        load_persisted_symbols(conn, &file_index)?
    } else {
        Vec::new()
    };
    let diagnostics: i64 =
        conn.query_row("SELECT COUNT(*) FROM diagnostics", [], |row| row.get(0))?;
    Ok(PersistedState {
        entities,
        entity_ids,
        symbols,
        files: files_with_ids
            .iter()
            .map(|(_, path)| path.clone())
            .collect(),
        file_ids: files_with_ids.iter().map(|(id, _)| *id).collect(),
        file_index,
        diagnostics: diagnostics as usize,
    })
}

fn load_persisted_files(conn: &rusqlite::Connection) -> Result<Vec<(i64, String)>> {
    let mut file_stmt = conn.prepare("SELECT id, path FROM files ORDER BY path")?;
    Ok(file_stmt
        .query_map([], |row| {
            Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?)
}

fn load_persisted_entities(
    conn: &rusqlite::Connection,
    file_index: &HashMap<i64, u32>,
) -> Result<(Vec<i64>, Vec<Entity>)> {
    let mut entity_stmt = conn.prepare(
        "SELECT id, kind, name, file_id,
                start_byte, end_byte, start_line, start_col, end_line, end_col,
                enclosing_function, method, path, status, body_shape,
                body_minhash, is_async, is_test, owner_type
         FROM entities ORDER BY id",
    )?;
    let mut entities = Vec::new();
    let mut entity_ids = Vec::new();
    for row in entity_stmt.query_map([], |row| {
        let kind = EntityKind::from_i64(row.get(1)?).ok_or_else(|| {
            rusqlite::Error::InvalidColumnType(1, "kind".into(), rusqlite::types::Type::Integer)
        })?;
        let db_file_id: i64 = row.get(3)?;
        let file_id = *file_index.get(&db_file_id).ok_or_else(|| {
            rusqlite::Error::InvalidColumnType(3, "file_id".into(), rusqlite::types::Type::Integer)
        })?;
        Ok((
            row.get::<_, i64>(0)?,
            Entity {
                kind,
                name: row.get(2)?,
                file_id,
                span: Span {
                    start_byte: row.get::<_, i64>(4)? as u32,
                    end_byte: row.get::<_, i64>(5)? as u32,
                    start_line: row.get::<_, i64>(6)? as u32,
                    start_col: row.get::<_, i64>(7)? as u32,
                    end_line: row.get::<_, i64>(8)? as u32,
                    end_col: row.get::<_, i64>(9)? as u32,
                },
                enclosing_function: row.get(10)?,
                method: row.get(11)?,
                path: row.get(12)?,
                status: row.get(13)?,
                body_shape: row.get(14)?,
                body_minhash: row
                    .get::<_, Option<Vec<u8>>>(15)?
                    .and_then(|blob| blob_to_minhash(&blob)),
                is_async: row.get(16)?,
                is_test: row.get(17)?,
                owner_type: row.get(18)?,
            },
        ))
    })? {
        let (id, entity) = row?;
        entity_ids.push(id);
        entities.push(entity);
    }
    Ok((entity_ids, entities))
}

fn load_persisted_symbols(
    conn: &rusqlite::Connection,
    file_index: &HashMap<i64, u32>,
) -> Result<Vec<Symbol>> {
    let mut symbols = Vec::new();
    let mut symbol_stmt = conn.prepare(
        "SELECT kind, name, file_id,
                start_byte, end_byte, start_line, start_col, end_line, end_col
         FROM symbols ORDER BY id",
    )?;
    for row in symbol_stmt.query_map([], |row| persisted_symbol(row, file_index))? {
        symbols.push(row?);
    }
    Ok(symbols)
}

fn persisted_symbol(
    row: &rusqlite::Row<'_>,
    file_index: &HashMap<i64, u32>,
) -> rusqlite::Result<Symbol> {
    let kind = SymbolKind::from_i64(row.get(0)?).ok_or_else(|| {
        rusqlite::Error::InvalidColumnType(0, "kind".into(), rusqlite::types::Type::Integer)
    })?;
    let db_file_id: i64 = row.get(2)?;
    let file_id = *file_index.get(&db_file_id).ok_or_else(|| {
        rusqlite::Error::InvalidColumnType(2, "file_id".into(), rusqlite::types::Type::Integer)
    })?;
    Ok(Symbol {
        kind,
        name: row.get(1)?,
        file_id,
        span: Span {
            start_byte: row.get::<_, i64>(3)? as u32,
            end_byte: row.get::<_, i64>(4)? as u32,
            start_line: row.get::<_, i64>(5)? as u32,
            start_col: row.get::<_, i64>(6)? as u32,
            end_line: row.get::<_, i64>(7)? as u32,
            end_col: row.get::<_, i64>(8)? as u32,
        },
    })
}

/// Reconstruct the current persisted edge layer in flat-index form.
///
/// Scoped incremental refreshes already leave `resolved_edges` authoritative.
/// Loading those rows avoids resolving every repository edge again merely to
/// recompute communities, clone bands, and fan metrics.
pub(crate) fn load_resolved_edges(
    conn: &rusqlite::Connection,
    state: &PersistedState,
) -> Result<Vec<ResolvedEdge>> {
    let entity_index: HashMap<i64, u32> = state
        .entity_ids
        .iter()
        .enumerate()
        .map(|(index, id)| (*id, index as u32))
        .collect();
    let mut stmt = conn.prepare(
        "SELECT from_file_id, to_file_id, kind, resolved,
                from_entity_id, to_entity_id
         FROM resolved_edges ORDER BY id",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, i64>(0)?,
            row.get::<_, Option<i64>>(1)?,
            row.get::<_, i64>(2)?,
            row.get::<_, bool>(3)?,
            row.get::<_, Option<i64>>(4)?,
            row.get::<_, Option<i64>>(5)?,
        ))
    })?;

    let mut edges = Vec::new();
    for row in rows {
        edges.push(decode_resolved_edge(row?, state, &entity_index)?);
    }
    Ok(edges)
}

type StoredEdge = (i64, Option<i64>, i64, bool, Option<i64>, Option<i64>);

fn decode_resolved_edge(
    row: StoredEdge,
    state: &PersistedState,
    entity_index: &HashMap<i64, u32>,
) -> Result<ResolvedEdge> {
    let (from_file, to_file, kind, resolved, from_entity, to_entity) = row;
    let from = state
        .file_index
        .get(&from_file)
        .copied()
        .ok_or_else(|| anyhow::anyhow!("edge references missing source file {from_file}"))?;
    let kind = crate::resolve::EdgeKind::from_i64(kind)
        .ok_or_else(|| anyhow::anyhow!("edge has invalid kind {kind}"))?;
    let from_entity = map_entity_id(from_entity, entity_index, "source")?;
    let to = decode_edge_target(resolved, to_file, to_entity, state, entity_index)?;
    Ok(ResolvedEdge {
        from,
        to,
        kind,
        resolved,
        from_entity,
    })
}

fn map_entity_id(
    id: Option<i64>,
    entity_index: &HashMap<i64, u32>,
    role: &str,
) -> Result<Option<u32>> {
    id.map(|id| {
        entity_index
            .get(&id)
            .copied()
            .ok_or_else(|| anyhow::anyhow!("edge references missing {role} entity {id}"))
    })
    .transpose()
}

fn decode_edge_target(
    resolved: bool,
    file_id: Option<i64>,
    entity_id: Option<i64>,
    state: &PersistedState,
    entity_index: &HashMap<i64, u32>,
) -> Result<EdgeTarget> {
    if !resolved {
        return Ok(EdgeTarget::Unknown);
    }
    if let Some(target) = map_entity_id(entity_id, entity_index, "target")? {
        return Ok(EdgeTarget::Entity(target));
    }
    if let Some(id) = file_id {
        let target = state
            .file_index
            .get(&id)
            .copied()
            .ok_or_else(|| anyhow::anyhow!("edge references missing target file {id}"))?;
        return Ok(EdgeTarget::File(target));
    }
    Err(anyhow::anyhow!("resolved edge has no target"))
}

pub(crate) fn persist_global_graph(
    conn: &rusqlite::Connection,
    state: &PersistedState,
    graph: &ResolvedGraph,
) -> Result<()> {
    anyhow::ensure!(
        graph.nodes.len() == state.file_ids.len(),
        "resolved graph nodes must match persisted files"
    );
    let tx = conn.unchecked_transaction()?;
    write_state_edges(&tx, state, &graph.edges)?;
    let file_ids = FileIds {
        flat: state.file_ids.clone(),
        offsets: vec![0],
    };
    write_communities(&tx, graph, &file_ids)?;
    write_clone_bands(&tx, graph, &state.entity_ids)?;
    tx.execute("UPDATE files SET edges_built_rev = rev", [])?;
    record_all_slices_fresh(&tx)?;
    tx.commit()?;
    Ok(())
}

fn write_state_edges(
    conn: &rusqlite::Connection,
    state: &PersistedState,
    edges: &[ResolvedEdge],
) -> Result<()> {
    let mut edge_stmt = conn.prepare(
        "INSERT INTO resolved_edges
            (from_file_id, to_file_id, kind, resolved, from_entity_id, to_entity_id)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
    )?;
    for edge in edges {
        let from = state.file_ids[edge.from as usize];
        let to = if edge.resolved {
            match edge.to {
                EdgeTarget::File(file_id) => Some(state.file_ids[file_id as usize]),
                EdgeTarget::Entity(entity_id) => {
                    let file_index = state.entities[entity_id as usize].file_id as usize;
                    Some(state.file_ids[file_index])
                }
                EdgeTarget::Unknown => None,
            }
        } else {
            None
        };
        let from_entity_id = edge
            .from_entity
            .and_then(|entity_id| entity_id_at(&state.entity_ids, entity_id as usize));
        let to_entity_id = if edge.resolved {
            match edge.to {
                EdgeTarget::Entity(entity_id) => {
                    entity_id_at(&state.entity_ids, entity_id as usize)
                }
                EdgeTarget::File(_) | EdgeTarget::Unknown => None,
            }
        } else {
            None
        };
        edge_stmt.execute(rusqlite::params![
            from,
            to,
            edge.kind.as_i64(),
            edge.resolved as i64,
            from_entity_id,
            to_entity_id
        ])?;
    }
    Ok(())
}

/// Global `files.id` for every file across every `ExtractOutput`, in the same
/// flattened order `resolve()` was given (`output[0].files ++ output[1].files
/// ++ ...`) — a `ResolvedGraph` node's index is a position in that same
/// concatenation, so `nodes[i]` and `flat_ids[i]` refer to the same file with
/// no path lookup needed. Per-entity/symbol/diagnostic resolution is a plain
/// array index (`flat_ids[offsets[out_idx] + local_file_id]`), replacing the
/// previous `HashMap<String, i64>` path cache — no string hashing or
/// comparison anywhere in the persist phase now.
struct FileIds {
    flat: Vec<i64>,
    offsets: Vec<usize>,
}

impl FileIds {
    fn get(&self, out_idx: usize, local_file_id: u32) -> i64 {
        self.flat[self.offsets[out_idx] + local_file_id as usize]
    }

    /// Global id of the file at flattened position `node` — used for
    /// `ResolvedGraph` node/edge indices, which are positions in the same
    /// concatenated file order.
    fn by_node(&self, node: u32) -> i64 {
        self.flat[node as usize]
    }
}

/// Persist a full extraction + resolution pass to `db_path`.
///
/// The database is opened with the full-rebuild schema scaffold (all prior
/// data wiped), every table is populated, and the write is committed as a
/// single transaction.
///
/// Complexity (cyclomatic, from `ControlFlow` entities) and churn (commit
/// count via `git log`) are computed here — see `complexity.rs`/`churn.rs` —
/// so `query-surface` can be a pure reader.
pub fn persist(
    db_path: &Path,
    output: &[ExtractOutput],
    graph: &ResolvedGraph,
    repo_root: &Path,
) -> Result<()> {
    ensure_default_subscriber();
    let profile = std::env::var_os("VARDE_PROFILE").is_some();
    let t = std::time::Instant::now();
    let _persist_span = tracing::info_span!("persist").entered();
    let mut conn = crate::db::open(db_path)?;
    let tx = conn.transaction()?;
    // Schema drop/rebuild AND every data write share one transaction: an
    // interruption at any point rolls the database back to its prior valid
    // state (no partial writes, no half-rebuilt schema).
    {
        let _span = tracing::info_span!("schema").entered();
        crate::db::rebuild_schema(&tx)?;
    }
    if profile {
        eprintln!("VARDE_PROFILE persist: schema done at {:?}", t.elapsed());
    }
    write_all(&tx, output, graph, repo_root)?;
    if profile {
        eprintln!("VARDE_PROFILE persist: write_all done at {:?}", t.elapsed());
    }
    // Same build fingerprint the streaming full build stamps, so an index this
    // path writes is recognized as current-binary by the incremental gate.
    set_slice_meta_value(&tx, "build_version", crate::db::build_version_fingerprint())?;
    {
        let _span = tracing::info_span!("indexes").entered();
        crate::db::create_indexes(&tx)?;
    }
    if profile {
        eprintln!("VARDE_PROFILE persist: indexes done at {:?}", t.elapsed());
    }
    tx.commit()?;
    if profile {
        eprintln!("VARDE_PROFILE persist: commit done at {:?}", t.elapsed());
    }
    Ok(())
}

/// Counts and file list reported back to `build::run_full` after a streaming
/// full build (the same fields it previously read off the in-memory
/// `ExtractOutput`).
pub(crate) struct FullBuildStats {
    pub entities: usize,
    pub symbols: usize,
    pub diagnostics: usize,
    pub files: Vec<String>,
}

/// Number of files parsed per pipeline chunk. Sized so the whole repo is a
/// couple dozen chunks at most (deep enough to keep the parse and insert
/// stages overlapped, coarse enough that each chunk's `write_*` calls prepare
/// their statements a handful of times rather than per-row).
const STREAM_CHUNK_FILES: usize = 512;

/// Full build that overlaps parsing with persistence (proposal #1).
///
/// Equivalent to `persist(scan::run(root) then resolve then persist)` but
/// pipelined: a parser thread `parse_chunk`s the file list in order and hands
/// each chunk to this thread, which owns the transaction and inserts the
/// chunk's raw rows via the exact same `write_files`/`write_entities`/
/// `write_symbols`/`write_diagnostics` primitives the incremental delta path
/// uses — so the two paths never diverge in how a row is written. Parsing
/// chunk N+1 overlaps inserting chunk N, hiding the insert cost behind the
/// (longer) parse.
///
/// Ordering is preserved end to end: chunks are parsed and inserted in file-
/// list order and `parse_chunk` collects each chunk in order, so files,
/// entities and symbols receive exactly the row ids a single whole-repo
/// `scan::run` + `persist` would assign. The result is a byte-identical index
/// to the non-streaming build (asserted by `streaming_matches_batch_build`).
///
/// After the raw layer is streamed in, `resolve` runs on the assembled
/// in-memory output (no DB read-back — the same source the old full build
/// resolved from) and the derived layer (edges, communities, clone bands,
/// complexity, churn) is written with the shared primitives, then indexes are
/// built once and the whole thing commits as one transaction. Crash safety is
/// unchanged: the caller writes to a sibling temp file and renames on success.
pub(crate) fn persist_full_streaming(
    db_path: &Path,
    listing: crate::scan::SourceListing,
    repo_root: &Path,
) -> Result<FullBuildStats> {
    ensure_default_subscriber();
    let profile = std::env::var_os("VARDE_PROFILE").is_some();
    let t = std::time::Instant::now();
    let crate::scan::SourceListing {
        files,
        diagnostics: traversal,
    } = listing;
    let churn_files: Vec<String> = files.iter().map(|f| f.path.clone()).collect();
    let churn_root = repo_root.to_path_buf();
    let churn_handle =
        std::thread::spawn(move || crate::churn::commit_counts_batch(&churn_files, &churn_root));

    let mut conn = crate::db::open(db_path)?;
    // Single transaction for the whole streaming build: every `write_*` below
    // propagates errors via `?`, so an early return drops `tx` without
    // `.commit()` and rusqlite rolls back via RAII (`Transaction::drop`).
    // That makes the graph_cache warm and `record_git_head` further down
    // (both run inside this same `tx`) atomic with every row write here —
    // either the whole build lands, or none of it does.
    let tx = conn.transaction()?;
    crate::db::rebuild_schema(&tx)?;
    let mut raw = stream_raw_files(&tx, &files)?;
    stream_checkpoint(profile, t, "parse+raw-insert");
    replace_traversal_diagnostics(&tx, &traversal)?;
    raw.merged.diagnostics.extend(traversal);
    let graph =
        crate::resolve::resolve(&raw.merged.entities, &raw.merged.symbols, &raw.merged.files)?;
    stream_checkpoint(profile, t, "resolve");
    write_streaming_derived(&tx, &raw, &graph, churn_handle)?;
    stream_checkpoint(profile, t, "derived");
    crate::db::create_indexes(&tx)?;
    stream_checkpoint(profile, t, "indexes");
    finalize_streaming_metadata(&tx, repo_root)?;
    stream_checkpoint(profile, t, "graph_cache+githead");
    tx.commit()?;
    stream_checkpoint(profile, t, "commit");
    Ok(FullBuildStats {
        entities: raw.merged.entities.len(),
        symbols: raw.merged.symbols.len(),
        diagnostics: raw.merged.diagnostics.len(),
        files: raw.merged.files,
    })
}

struct StreamingRaw {
    merged: ExtractOutput,
    file_ids: FileIds,
    entity_ids: EntityIdIndex,
    complexity_counts: Vec<u32>,
}

fn stream_raw_files(
    conn: &rusqlite::Connection,
    files: &[crate::scan::SourceFile],
) -> Result<StreamingRaw> {
    let mut raw = empty_streaming_raw(files.len());
    let mut insert_err = None;
    std::thread::scope(|scope| {
        let (tx_ch, rx_ch) =
            std::sync::mpsc::sync_channel::<(usize, usize, crate::scan::ChunkParsed)>(2);
        let tx_parser = tx_ch.clone();
        let files_ref = files;
        scope.spawn(move || parse_streaming_chunks(files_ref, tx_parser));
        drop(tx_ch);
        consume_streaming_chunks(conn, files, &rx_ch, &mut raw, &mut insert_err);
    });
    if let Some(error) = insert_err {
        return Err(error);
    }
    Ok(raw)
}

fn empty_streaming_raw(file_count: usize) -> StreamingRaw {
    StreamingRaw {
        merged: ExtractOutput {
            entities: Vec::new(),
            symbols: Vec::new(),
            diagnostics: Vec::new(),
            files: Vec::with_capacity(file_count),
            file_meta: Vec::with_capacity(file_count),
        },
        file_ids: FileIds {
            flat: Vec::with_capacity(file_count),
            offsets: vec![0],
        },
        entity_ids: Vec::new(),
        complexity_counts: vec![0; file_count],
    }
}

fn parse_streaming_chunks(
    files: &[crate::scan::SourceFile],
    sender: std::sync::mpsc::SyncSender<(usize, usize, crate::scan::ChunkParsed)>,
) {
    for (index, chunk) in files.chunks(STREAM_CHUNK_FILES).enumerate() {
        let parsed = crate::scan::parse_chunk(chunk, index * STREAM_CHUNK_FILES);
        if sender.send((index, chunk.len(), parsed)).is_err() {
            break;
        }
    }
}

fn consume_streaming_chunks(
    conn: &rusqlite::Connection,
    files: &[crate::scan::SourceFile],
    receiver: &std::sync::mpsc::Receiver<(usize, usize, crate::scan::ChunkParsed)>,
    raw: &mut StreamingRaw,
    error: &mut Option<anyhow::Error>,
) {
    while let Ok((index, chunk_len, parsed)) = receiver.recv() {
        if parsed.content_hashes.len() != chunk_len {
            *error = Some(anyhow::anyhow!(
                "chunk {index} produced {} content hashes for {chunk_len} files",
                parsed.content_hashes.len()
            ));
            break;
        }
        let start = index * STREAM_CHUNK_FILES;
        let chunk_files = &files[start..start + chunk_len];
        if let Err(cause) = ingest_chunk(
            conn,
            chunk_files,
            parsed,
            &mut raw.merged,
            &mut raw.file_ids,
            &mut raw.entity_ids,
            &mut raw.complexity_counts,
        ) {
            *error = Some(cause);
            break;
        }
    }
}

fn write_streaming_derived(
    conn: &rusqlite::Connection,
    raw: &StreamingRaw,
    graph: &ResolvedGraph,
    churn_handle: std::thread::JoinHandle<HashMap<String, u32>>,
) -> Result<()> {
    let derived = std::slice::from_ref(&raw.merged);
    write_edges(conn, derived, graph, &raw.file_ids, &raw.entity_ids)?;
    write_communities(conn, graph, &raw.file_ids)?;
    write_clone_bands(conn, graph, &raw.entity_ids)?;
    write_complexity(conn, &raw.file_ids, &raw.complexity_counts)?;
    write_churn(conn, derived, &raw.file_ids, churn_handle)?;
    record_all_slices_fresh(conn)?;
    conn.execute("UPDATE files SET edges_built_rev = rev", [])?;
    Ok(())
}

fn finalize_streaming_metadata(conn: &rusqlite::Connection, repo_root: &Path) -> Result<()> {
    if let Some(root) = repo_root.to_str() {
        crate::slice::record_git_head(conn, root)?;
    }
    set_slice_meta_value(
        conn,
        "build_version",
        crate::db::build_version_fingerprint(),
    )?;
    rebuild_graph_cache_full(conn)
}

fn stream_checkpoint(profile: bool, started: std::time::Instant, label: &str) {
    if profile {
        eprintln!(
            "VARDE_PROFILE stream: {label} done at {:?}",
            started.elapsed()
        );
    }
}

/// Insert one parsed chunk's raw rows and fold its results into the repo-wide
/// accumulators. Files are inserted first (their ids extend `file_ids.flat` in
/// list order), then entities/symbols/diagnostics via the shared `write_*`
/// primitives against the global file-id table; finally the chunk's rows are
/// appended to `merged` so `resolve` and the derived writes see the whole repo
/// in file order. See [`persist_full_streaming`] for why order is preserved.
fn ingest_chunk(
    conn: &rusqlite::Connection,
    chunk_files: &[crate::scan::SourceFile],
    parsed: crate::scan::ChunkParsed,
    merged: &mut crate::model::ExtractOutput,
    file_ids: &mut FileIds,
    entity_ids: &mut EntityIdIndex,
    complexity_counts: &mut [u32],
) -> Result<()> {
    // A single-file `ExtractOutput` view of just this chunk, used both to feed
    // the shared writers and (drained) to grow `merged`.
    let mut sub = crate::model::ExtractOutput {
        entities: parsed.entities,
        symbols: parsed.symbols,
        diagnostics: parsed.diagnostics,
        files: chunk_files.iter().map(|f| f.path.clone()).collect(),
        file_meta: chunk_files
            .iter()
            .zip(&parsed.content_hashes)
            .map(|(f, hash)| crate::model::FileMeta {
                mtime: f.mtime,
                size: f.size,
                content_hash: hash.clone(),
            })
            .collect(),
    };

    // Files first: extend the global flat id table in list order.
    let chunk_file_ids = write_files(conn, std::slice::from_ref(&sub))?;
    file_ids.flat.extend_from_slice(&chunk_file_ids.flat);

    // Raw rows against the global file-id table (entities carry global file_id,
    // so `file_ids.get(0, e.file_id)` resolves into the flat table just grown).
    let (chunk_entity_ids, chunk_complexity) =
        write_entities(conn, std::slice::from_ref(&sub), file_ids)?;
    entity_ids.extend_from_slice(&chunk_entity_ids);
    for (slot, add) in complexity_counts.iter_mut().zip(&chunk_complexity) {
        *slot += *add;
    }
    write_symbols(conn, std::slice::from_ref(&sub), file_ids)?;
    write_diagnostics(conn, std::slice::from_ref(&sub), file_ids)?;
    let chunk_start = (file_ids.flat.len() - chunk_files.len()) as u32;
    write_function_metrics_with_bases(conn, std::slice::from_ref(&sub), file_ids, &[chunk_start])?;

    // Grow the assembled output in file order (drains `sub`).
    merged.entities.append(&mut sub.entities);
    merged.symbols.append(&mut sub.symbols);
    merged.diagnostics.append(&mut sub.diagnostics);
    merged.files.append(&mut sub.files);
    merged.file_meta.append(&mut sub.file_meta);
    Ok(())
}

/// Ensure human-readable stderr logging when no subscriber is configured.
///
/// If a subscriber already exists (installed by the caller, the CLI, or a
/// test), this is a no-op and the existing subscriber is respected. Otherwise
/// a scoped (thread-local) fmt subscriber writes to stderr — scoped, not
/// global, so it never disturbs a later `set_global_default` (the pattern
/// varde's own tracing-capture tests rely on).
fn ensure_default_subscriber() {
    if tracing::dispatcher::has_been_set() {
        return;
    }
    let filter = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));
    let subscriber = tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_writer(std::io::stderr)
        .finish();
    let _default = tracing::subscriber::set_default(subscriber);
}

/// Replace persisted data for changed files within an existing database.
///
/// `changed_file_ids` must match the flattened order of `output.files` and
/// `graph.nodes`. The files rows themselves remain in place; every dependent
/// row is explicitly removed before the freshly parsed rows are inserted.
pub(crate) fn persist_delta(
    conn: &rusqlite::Connection,
    changed_file_ids: &[i64],
    output: &[ExtractOutput],
    graph: &ResolvedGraph,
    repo_root: &Path,
) -> Result<()> {
    let mut offsets = Vec::with_capacity(output.len());
    let mut file_count = 0usize;
    for out in output {
        offsets.push(file_count);
        file_count += out.files.len();
    }
    anyhow::ensure!(
        file_count == changed_file_ids.len(),
        "changed file IDs must match flattened output files"
    );
    anyhow::ensure!(
        graph.nodes.len() == changed_file_ids.len(),
        "graph nodes must match changed file IDs"
    );

    let churn_handle = spawn_churn(output, repo_root);

    let tx = conn.unchecked_transaction()?;
    delete_delta_rows(&tx, changed_file_ids)?;

    let file_ids = FileIds {
        flat: changed_file_ids.to_vec(),
        offsets,
    };
    let (entity_ids, complexity_counts) = write_entities(&tx, output, &file_ids)?;
    write_symbols(&tx, output, &file_ids)?;
    write_diagnostics(&tx, output, &file_ids)?;
    write_function_metrics(&tx, output, &file_ids)?;
    write_edges(&tx, output, graph, &file_ids, &entity_ids)?;
    write_communities(&tx, graph, &file_ids)?;
    write_clone_bands(&tx, graph, &entity_ids)?;
    write_complexity(&tx, &file_ids, &complexity_counts)?;
    write_churn(&tx, output, &file_ids, churn_handle)?;
    update_file_states(&tx, changed_file_ids, output)?;
    tx.commit()?;
    Ok(())
}

fn update_file_states(
    conn: &rusqlite::Connection,
    changed_file_ids: &[i64],
    output: &[ExtractOutput],
) -> Result<()> {
    let mut stmt =
        conn.prepare("UPDATE files SET mtime = ?1, size = ?2, content_hash = ?3 WHERE id = ?4")?;
    let mut ids = changed_file_ids.iter();
    for out in output {
        for (path, meta) in out.files.iter().zip(&out.file_meta) {
            let file_id = ids
                .next()
                .ok_or_else(|| anyhow::anyhow!("missing changed file id for {path}"))?;
            stmt.execute(rusqlite::params![
                meta.mtime,
                meta.size,
                meta.content_hash,
                file_id
            ])?;
        }
    }
    anyhow::ensure!(
        ids.next().is_none(),
        "extra changed file IDs beyond flattened output files"
    );
    Ok(())
}

fn delete_delta_rows(conn: &rusqlite::Connection, changed_file_ids: &[i64]) -> Result<()> {
    if changed_file_ids.is_empty() {
        return Ok(());
    }
    for ids in changed_file_ids.chunks(400) {
        delete_delta_rows_batch(conn, ids)?;
    }
    conn.execute(
        "DELETE FROM communities
         WHERE id NOT IN (SELECT DISTINCT community_id FROM community_members)",
        [],
    )?;
    conn.execute(
        "DELETE FROM clone_bands
         WHERE id NOT IN (SELECT DISTINCT band_id FROM clone_band_members)",
        [],
    )?;
    Ok(())
}

fn delete_delta_rows_batch(conn: &rusqlite::Connection, changed_file_ids: &[i64]) -> Result<()> {
    let (placeholders, params) = in_clause(changed_file_ids);

    conn.execute(
        &format!(
            "DELETE FROM clone_band_members
             WHERE entity_id IN (SELECT id FROM entities WHERE file_id IN ({placeholders}))"
        ),
        params.as_slice(),
    )?;
    conn.execute(
        &format!("DELETE FROM community_members WHERE file_id IN ({placeholders})"),
        params.as_slice(),
    )?;
    conn.execute(
        &format!(
            "DELETE FROM resolved_edges
             WHERE from_file_id IN ({placeholders}) OR to_file_id IN ({placeholders})"
        ),
        params
            .iter()
            .chain(params.iter())
            .copied()
            .collect::<Vec<_>>()
            .as_slice(),
    )?;
    conn.execute(
        &format!("DELETE FROM diagnostics WHERE file_id IN ({placeholders})"),
        params.as_slice(),
    )?;
    conn.execute(
        &format!("DELETE FROM function_metrics WHERE file_id IN ({placeholders})"),
        params.as_slice(),
    )?;
    conn.execute(
        &format!("DELETE FROM symbols WHERE file_id IN ({placeholders})"),
        params.as_slice(),
    )?;
    conn.execute(
        &format!("DELETE FROM entities WHERE file_id IN ({placeholders})"),
        params.as_slice(),
    )?;
    Ok(())
}

/// Every table write, in dependency order.
pub(crate) fn write_all(
    conn: &rusqlite::Connection,
    output: &[ExtractOutput],
    graph: &ResolvedGraph,
    repo_root: &Path,
) -> Result<()> {
    let profile = std::env::var_os("VARDE_PROFILE").is_some();
    let t = std::time::Instant::now();
    let churn_handle = spawn_churn(output, repo_root);
    let (file_ids, entity_ids, complexity_counts) = write_raw_tables(conn, output, profile, t)?;
    write_derived_tables(
        conn,
        output,
        graph,
        &file_ids,
        &entity_ids,
        &complexity_counts,
        churn_handle,
        profile,
        t,
    )?;
    record_all_slices_fresh(conn)?;
    conn.execute("UPDATE files SET edges_built_rev = rev", [])?;
    Ok(())
}

fn write_raw_tables(
    conn: &rusqlite::Connection,
    output: &[ExtractOutput],
    profile: bool,
    started: std::time::Instant,
) -> Result<(FileIds, EntityIdIndex, Vec<u32>)> {
    let file_ids = {
        let _span = tracing::info_span!("files").entered();
        write_files(conn, output)?
    };
    write_checkpoint(profile, started, "files");
    let (entity_ids, complexity_counts) = {
        let _span = tracing::info_span!("entities").entered();
        write_entities(conn, output, &file_ids)?
    };
    write_checkpoint(profile, started, "entities");
    {
        let _span = tracing::info_span!("symbols").entered();
        write_symbols(conn, output, &file_ids)?;
    }
    write_checkpoint(profile, started, "symbols");
    {
        let _span = tracing::info_span!("diagnostics").entered();
        write_diagnostics(conn, output, &file_ids)?;
    }
    write_checkpoint(profile, started, "diagnostics");
    write_function_metrics(conn, output, &file_ids)?;
    write_checkpoint(profile, started, "function_metrics");
    Ok((file_ids, entity_ids, complexity_counts))
}

#[allow(clippy::too_many_arguments)]
fn write_derived_tables(
    conn: &rusqlite::Connection,
    output: &[ExtractOutput],
    graph: &ResolvedGraph,
    file_ids: &FileIds,
    entity_ids: &EntityIdIndex,
    complexity_counts: &[u32],
    churn_handle: std::thread::JoinHandle<HashMap<String, u32>>,
    profile: bool,
    started: std::time::Instant,
) -> Result<()> {
    {
        let _span = tracing::info_span!("edges").entered();
        write_edges(conn, output, graph, file_ids, entity_ids)?;
    }
    write_checkpoint(profile, started, "edges");
    {
        let _span = tracing::info_span!("communities").entered();
        write_communities(conn, graph, file_ids)?;
    }
    write_checkpoint(profile, started, "communities");
    {
        let _span = tracing::info_span!("clone_bands").entered();
        write_clone_bands(conn, graph, entity_ids)?;
    }
    write_checkpoint(profile, started, "clone_bands");
    write_complexity(conn, file_ids, complexity_counts)?;
    write_checkpoint(profile, started, "complexity");
    write_churn(conn, output, file_ids, churn_handle)?;
    write_checkpoint(profile, started, "churn");
    Ok(())
}

fn write_checkpoint(profile: bool, started: std::time::Instant, label: &str) {
    if profile {
        eprintln!(
            "VARDE_PROFILE write_all: {label} done at {:?}",
            started.elapsed()
        );
    }
}

/// Batch size for multi-row `INSERT ... VALUES (...), (...), ...` statements.
/// Large enough to amortize statement-prepare/round-trip overhead, small
/// enough to keep the generated SQL text and bound-parameter count modest.
const INSERT_BATCH: usize = 500;

/// Multi-row `INSERT INTO <table_cols> VALUES ...` SQL for `rows` rows, each
/// tuple shaped `placeholder`.
fn multi_insert_sql(table_cols: &str, placeholder: &str, rows: usize) -> String {
    let placeholders = vec![placeholder; rows].join(", ");
    format!("INSERT INTO {table_cols} VALUES {placeholders}")
}

/// Execute `rows` in batches of [`INSERT_BATCH`], building the statement via
/// `sql_for(n)` and pushing each row's params via `push`. Returns the rowid of
/// the first inserted row (rowids are consecutive, so callers derive the rest),
/// or `None` if `rows` is empty.
fn batch_insert<'a, T>(
    conn: &rusqlite::Connection,
    sql_for: impl Fn(usize) -> String,
    ncols: usize,
    rows: &'a [T],
    push: impl Fn(&mut Vec<&'a dyn rusqlite::ToSql>, &'a T),
) -> Result<Option<i64>> {
    let total = rows.len();
    if total == 0 {
        return Ok(None);
    }
    let tail = total % INSERT_BATCH;
    let mut stmt_full = conn.prepare(&sql_for(INSERT_BATCH))?;
    let mut stmt_tail = (tail > 0)
        .then(|| conn.prepare(&sql_for(tail)))
        .transpose()?;
    let mut first: Option<i64> = None;
    for chunk in rows.chunks(INSERT_BATCH) {
        let stmt = if chunk.len() == INSERT_BATCH {
            &mut stmt_full
        } else {
            stmt_tail.as_mut().expect("tail statement prepared")
        };
        let mut params: Vec<&'a dyn rusqlite::ToSql> = Vec::with_capacity(chunk.len() * ncols);
        for row in chunk {
            push(&mut params, row);
        }
        stmt.execute(params.as_slice())?;
        let last = conn.last_insert_rowid();
        let f = last - chunk.len() as i64 + 1;
        if first.is_none() {
            first = Some(f);
        }
    }
    Ok(first)
}

/// Multi-row `INSERT INTO symbols` SQL for `rows` rows.
fn symbols_insert_sql(rows: usize) -> String {
    multi_insert_sql(
        "symbols (kind, file_id, name, start_byte, end_byte, start_line, start_col, end_line, end_col)",
        "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
}

/// Multi-row `INSERT INTO entities` SQL for `rows` rows.
fn entities_insert_sql(rows: usize) -> String {
    multi_insert_sql(
        "entities (kind, file_id, name, start_byte, end_byte, start_line, start_col, end_line, end_col, enclosing_function, method, path, status, body_shape, body_minhash, is_async, is_test, owner_type)",
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
}

/// Insert one `files` row per file across every `ExtractOutput`, in flattened
/// concatenation order, batched `INSERT_BATCH` rows per statement.
///
/// `complexity`/`churn`/`community_id` are left NULL and `fan_in`/`fan_out`
/// at 0 at this stage; later persistence stages backfill them.
fn write_files(conn: &rusqlite::Connection, output: &[ExtractOutput]) -> Result<FileIds> {
    let mut offsets = Vec::with_capacity(output.len());
    let mut running = 0usize;
    for out in output {
        offsets.push(running);
        running += out.files.len();
    }

    let all_paths: Vec<&str> = output
        .iter()
        .flat_map(|o| o.files.iter().map(String::as_str))
        .collect();
    // Scan-time metadata (mtime/size/content_hash) was captured during the
    // walk; consume it directly instead of re-statting and re-reading every
    // file here (which cost a full 141 MB read on scale targets).
    let states: Vec<(i64, i64, &str)> = output
        .iter()
        .flat_map(|o| {
            o.file_meta
                .iter()
                .map(|m| (m.mtime, m.size, m.content_hash.as_str()))
        })
        .collect();

    let mut flat = Vec::with_capacity(all_paths.len());
    for (path_chunk, state_chunk) in all_paths
        .chunks(INSERT_BATCH)
        .zip(states.chunks(INSERT_BATCH))
    {
        let placeholders = path_chunk
            .iter()
            .map(|_| "(?, ?, ?, ?)")
            .collect::<Vec<_>>()
            .join(", ");
        let sql =
            format!("INSERT INTO files (path, mtime, size, content_hash) VALUES {placeholders}");
        let mut stmt = conn.prepare(&sql)?;
        let mut params: Vec<&dyn rusqlite::ToSql> = Vec::with_capacity(path_chunk.len() * 4);
        for (path, (mtime, size, content_hash)) in path_chunk.iter().zip(state_chunk) {
            params.push(path as &dyn rusqlite::ToSql);
            params.push(mtime as &dyn rusqlite::ToSql);
            params.push(size as &dyn rusqlite::ToSql);
            params.push(content_hash as &dyn rusqlite::ToSql);
        }
        stmt.execute(params.as_slice())?;
        let last = conn.last_insert_rowid();
        let first = last - path_chunk.len() as i64 + 1;
        flat.extend(first..=last);
    }
    Ok(FileIds { flat, offsets })
}

/// Insert `symbols` rows in batches, each keyed to its file's `files.id`.
fn write_symbols<'a>(
    conn: &rusqlite::Connection,
    output: &'a [ExtractOutput],
    file_ids: &FileIds,
) -> Result<()> {
    type SymbolRow<'a> = (i64, i64, &'a str, i64, i64, i64, i64, i64, i64);
    let rows: Vec<SymbolRow<'a>> = output
        .iter()
        .enumerate()
        .flat_map(|(out_idx, out)| {
            out.symbols.iter().map(move |s| {
                (
                    s.kind.as_i64(),
                    file_ids.get(out_idx, s.file_id),
                    s.name.as_str(),
                    s.span.start_byte as i64,
                    s.span.end_byte as i64,
                    s.span.start_line as i64,
                    s.span.start_col as i64,
                    s.span.end_line as i64,
                    s.span.end_col as i64,
                )
            })
        })
        .collect();

    batch_insert(conn, symbols_insert_sql, 9, &rows, |params, row| {
        params.push(&row.0);
        params.push(&row.1);
        params.push(&row.2);
        params.push(&row.3);
        params.push(&row.4);
        params.push(&row.5);
        params.push(&row.6);
        params.push(&row.7);
        params.push(&row.8);
    })?;
    Ok(())
}

/// Persist communities, membership, and the denormalized fan/community
/// columns on `files`.
///
/// - One `communities` row per [`Community`], labeled `community-<upstream
///   id>` (the model carries no intrinsic label).
/// - One `community_members` row per (community, file) pair, keyed by the
///   communities table's surrogate id (the upstream `Community.id` is not the
///   persisted `communities.id`).
/// - `files.community_id` set from each `FileNode.community_id`, mapped
///   through the surrogate id.
/// - `files.fan_in`/`files.fan_out` copied verbatim from `FileNode` — the
///   source of truth; never recomputed from `resolved_edges`.
fn write_communities(
    conn: &rusqlite::Connection,
    graph: &ResolvedGraph,
    file_ids: &FileIds,
) -> Result<()> {
    let surrogate = insert_community_labels(conn, &graph.communities)?;
    if graph.communities.is_empty() {
        return Ok(());
    }
    insert_community_members(conn, graph, file_ids, &surrogate)?;
    update_community_files(conn, graph, file_ids, &surrogate)
}

fn insert_community_labels(
    conn: &rusqlite::Connection,
    communities: &[crate::resolve::Community],
) -> Result<HashMap<u32, i64>> {
    let labels: Vec<String> = communities
        .iter()
        .map(|c| format!("community-{}", c.id))
        .collect();
    let first_rowid = batch_insert(
        conn,
        |n| multi_insert_sql("communities (label)", "(?)", n),
        1,
        &labels,
        |params, label| params.push(label),
    )?;
    if communities.is_empty() {
        return Ok(HashMap::new());
    }
    let Some(first) = first_rowid else {
        anyhow::bail!("batch_insert returned no rowid for a non-empty communities batch");
    };
    let mut surrogate: std::collections::HashMap<u32, i64> =
        std::collections::HashMap::with_capacity(communities.len());
    for (i, community) in communities.iter().enumerate() {
        surrogate.insert(community.id, first + i as i64);
    }
    Ok(surrogate)
}

fn insert_community_members(
    conn: &rusqlite::Connection,
    graph: &ResolvedGraph,
    file_ids: &FileIds,
    surrogate: &HashMap<u32, i64>,
) -> Result<()> {
    let node_by_path: std::collections::HashMap<&str, u32> = graph
        .nodes
        .iter()
        .enumerate()
        .map(|(i, n)| (n.path.as_str(), i as u32))
        .collect();

    let node_by_path = &node_by_path;
    let member_rows: Vec<(i64, i64)> = graph
        .communities
        .iter()
        .flat_map(|community| {
            let cid = surrogate[&community.id];
            community.members.iter().filter_map(move |member| {
                node_by_path
                    .get(member.as_str())
                    .map(|&node| (cid, file_ids.by_node(node)))
            })
        })
        .collect();
    batch_insert(
        conn,
        |n| multi_insert_sql("community_members (community_id, file_id)", "(?, ?)", n),
        2,
        &member_rows,
        |params, row| {
            params.push(&row.0);
            params.push(&row.1);
        },
    )?;
    Ok(())
}

fn update_community_files(
    conn: &rusqlite::Connection,
    graph: &ResolvedGraph,
    file_ids: &FileIds,
    surrogate: &HashMap<u32, i64>,
) -> Result<()> {
    let mut stmt = conn
        .prepare("UPDATE files SET community_id = ?1, fan_in = ?2, fan_out = ?3 WHERE id = ?4")?;
    for (i, node) in graph.nodes.iter().enumerate() {
        let fid = file_ids.by_node(i as u32);
        let community_id = node
            .community_id
            .and_then(|cid| surrogate.get(&cid).copied());
        stmt.execute(rusqlite::params![
            community_id,
            node.fan_in,
            node.fan_out,
            fid
        ])?;
    }
    Ok(())
}

/// Persist clone bands and membership.
///
/// `CloneBand.members` holds flat entity indices (the same concatenation order
/// [`write_entities`] inserts), so each member maps directly to
/// `entity_ids[member]` — no `(file_id, start_byte, end_byte)` correlation.
/// Bands are labeled `clone-band-<upstream id>`.
fn write_clone_bands(
    conn: &rusqlite::Connection,
    graph: &ResolvedGraph,
    entity_ids: &EntityIdIndex,
) -> Result<()> {
    // 1. Insert bands in one batch; rowids are consecutive, so band_id =
    // first_rowid + flat_index.
    let labels: Vec<String> = graph
        .clone_bands
        .iter()
        .map(|b| format!("clone-band-{}", b.id))
        .collect();
    let first_rowid = batch_insert(
        conn,
        |n| multi_insert_sql("clone_bands (label)", "(?)", n),
        1,
        &labels,
        |params, label| params.push(label),
    )?;
    if graph.clone_bands.is_empty() {
        return Ok(());
    }
    let Some(first) = first_rowid else {
        anyhow::bail!("batch_insert returned no rowid for a non-empty clone_bands batch");
    };

    // 2. Membership rows: one per (band, entity) pair.
    let member_rows: Vec<(i64, i64)> = graph
        .clone_bands
        .iter()
        .enumerate()
        .flat_map(|(band_idx, band)| {
            let band_id = first + band_idx as i64;
            band.members.iter().filter_map(move |&member| {
                match entity_id_at(entity_ids, member as usize) {
                    Some(eid) => Some((band_id, eid)),
                    None => {
                        tracing::warn!(
                            band = band.id,
                            entity = member,
                            "clone-band member index out of range; skipping"
                        );
                        None
                    }
                }
            })
        })
        .collect();
    batch_insert(
        conn,
        |n| multi_insert_sql("clone_band_members (band_id, entity_id)", "(?, ?)", n),
        2,
        &member_rows,
        |params, row| {
            params.push(&row.0);
            params.push(&row.1);
        },
    )?;
    Ok(())
}

/// Backfill `files.complexity` with cyclomatic complexity per file.
///
/// Formula (documented in `memory-bank/knowledge/reference/sqlite-persistence.md`):
/// base 1 + one per `ControlFlow` entity. The per-file `ControlFlow` count is
/// accumulated by [`write_entities`] and passed in as `complexity_counts`.
fn write_complexity(
    conn: &rusqlite::Connection,
    file_ids: &FileIds,
    complexity_counts: &[u32],
) -> Result<()> {
    let mut stmt = conn.prepare("UPDATE files SET complexity = ?1 WHERE id = ?2")?;
    for (flat_idx, &count) in complexity_counts.iter().enumerate() {
        stmt.execute(rusqlite::params![1 + count, file_ids.flat[flat_idx]])?;
    }
    Ok(())
}

/// Persist versioned function metrics with their supporting evidence.
fn write_function_metrics(
    conn: &rusqlite::Connection,
    output: &[ExtractOutput],
    file_ids: &FileIds,
) -> Result<()> {
    let bases = vec![0; output.len()];
    write_function_metrics_with_bases(conn, output, file_ids, &bases)
}

/// Persist metrics when extracted file ids start above zero.
///
/// Streaming chunks retain repository-global file ids. `file_id_bases`
/// maps those ids into each chunk's local `files` vector.
fn write_function_metrics_with_bases(
    conn: &rusqlite::Connection,
    output: &[ExtractOutput],
    file_ids: &FileIds,
    file_id_bases: &[u32],
) -> Result<()> {
    anyhow::ensure!(
        output.len() == file_id_bases.len(),
        "metric file-id bases must match extraction outputs"
    );
    let mut stmt = conn.prepare(
        "INSERT INTO function_metrics (
             file_id, identity, name, owner_type,
             start_byte, end_byte, start_line, start_col, end_line, end_col,
             cyclomatic, cognitive, max_nesting, line_span, byte_size,
             confidence, confidence_reasons, metric_version
         ) VALUES (
             ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9,
             ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18
         )",
    )?;

    for (out_idx, out) in output.iter().enumerate() {
        write_output_function_metrics(&mut stmt, out, file_ids, out_idx, file_id_bases[out_idx])?;
    }
    Ok(())
}

struct MetricDiagnosticFiles {
    all: HashSet<u32>,
    syntax: HashSet<u32>,
}

impl MetricDiagnosticFiles {
    fn from_output(output: &ExtractOutput) -> Self {
        let all = output
            .diagnostics
            .iter()
            .filter_map(|diagnostic| diagnostic.file_id)
            .collect();
        let syntax = output
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.message.contains("syntax error"))
            .filter_map(|diagnostic| diagnostic.file_id)
            .collect();
        Self { all, syntax }
    }
}

fn write_output_function_metrics(
    stmt: &mut rusqlite::Statement<'_>,
    output: &ExtractOutput,
    file_ids: &FileIds,
    output_index: usize,
    file_id_base: u32,
) -> Result<()> {
    let diagnostic_files = MetricDiagnosticFiles::from_output(output);
    for metric in crate::complexity::function_complexities(&output.entities) {
        let path = function_metric_path(output, &metric, file_id_base)?;
        let certified_language = has_certified_complexity_profile(Path::new(path));
        write_function_metric_row(
            stmt,
            file_ids.get(output_index, metric.file_id),
            &metric,
            &diagnostic_files,
            certified_language,
        )?;
    }
    Ok(())
}

fn has_certified_complexity_profile(path: &Path) -> bool {
    use ast_grep_language::SupportLang;

    matches!(
        crate::parse::language_for_path(path),
        Some(
            SupportLang::Bash
                | SupportLang::C
                | SupportLang::Cpp
                | SupportLang::CSharp
                | SupportLang::Dart
                | SupportLang::Elixir
                | SupportLang::Go
                | SupportLang::Haskell
                | SupportLang::Java
                | SupportLang::JavaScript
                | SupportLang::Kotlin
                | SupportLang::Lua
                | SupportLang::Php
                | SupportLang::Python
                | SupportLang::Ruby
                | SupportLang::Rust
                | SupportLang::Scala
                | SupportLang::Solidity
                | SupportLang::Swift
                | SupportLang::Tsx
                | SupportLang::TypeScript
        )
    )
}

fn function_metric_path<'a>(
    output: &'a ExtractOutput,
    metric: &FunctionComplexity,
    file_id_base: u32,
) -> Result<&'a str> {
    let local_file_id = metric
        .file_id
        .checked_sub(file_id_base)
        .ok_or_else(|| anyhow::anyhow!("function metric file id precedes its output base"))?
        as usize;
    output
        .files
        .get(local_file_id)
        .map(String::as_str)
        .ok_or_else(|| anyhow::anyhow!("function metric file id is outside its output"))
}

fn function_metric_confidence(
    metric: &FunctionComplexity,
    diagnostic_files: &MetricDiagnosticFiles,
    certified_language: bool,
) -> &'static str {
    if metric.confidence == ComplexityConfidence::Low
        || diagnostic_files.all.contains(&metric.file_id)
    {
        "low"
    } else if certified_language {
        "high"
    } else {
        "partial"
    }
}

fn function_metric_reasons(
    metric: &FunctionComplexity,
    diagnostic_files: &MetricDiagnosticFiles,
    certified_language: bool,
) -> Result<String> {
    let mut reasons: Vec<String> = metric
        .confidence_reasons
        .iter()
        .map(format_confidence_reason)
        .collect();
    if diagnostic_files.syntax.contains(&metric.file_id) {
        reasons.push("syntax_diagnostic".to_string());
    } else if diagnostic_files.all.contains(&metric.file_id) {
        reasons.push("file_diagnostic".to_string());
    }
    if !certified_language {
        reasons.push("unsupported_language_profile".to_string());
    }
    serde_json::to_string(&reasons).map_err(Into::into)
}

fn format_confidence_reason(reason: &ComplexityConfidenceReason) -> String {
    match reason {
        ComplexityConfidenceReason::UnknownControlFlowRole { name } => {
            format!("unknown_control_flow_role:{name}")
        }
        ComplexityConfidenceReason::IncompleteDecisionContainer { name } => {
            format!("incomplete_decision_container:{name}")
        }
    }
}

fn function_metric_identity(metric: &FunctionComplexity) -> String {
    match metric.owner_type.as_deref() {
        Some(owner) => format!("{owner}::{}", metric.name),
        None => metric.name.clone(),
    }
}

fn write_function_metric_row(
    stmt: &mut rusqlite::Statement<'_>,
    db_file_id: i64,
    metric: &FunctionComplexity,
    diagnostic_files: &MetricDiagnosticFiles,
    certified_language: bool,
) -> Result<()> {
    let identity = function_metric_identity(metric);
    let confidence = function_metric_confidence(metric, diagnostic_files, certified_language);
    let reasons = function_metric_reasons(metric, diagnostic_files, certified_language)?;
    stmt.execute(rusqlite::params![
        db_file_id,
        identity,
        metric.name,
        metric.owner_type,
        metric.span.start_byte,
        metric.span.end_byte,
        metric.span.start_line,
        metric.span.start_col,
        metric.span.end_line,
        metric.span.end_col,
        metric.cyclomatic,
        metric.cognitive,
        metric.max_nesting,
        metric.line_span,
        metric.byte_size,
        confidence,
        reasons,
        FUNCTION_METRIC_VERSION,
    ])?;
    Ok(())
}

/// Kick off the churn `git log` walk on a background thread. It only needs
/// the file list (available the moment scan finishes), so the walk overlaps
/// the entity/symbol/edge inserts below; the handle is joined in
/// [`write_churn`].
fn spawn_churn(
    output: &[ExtractOutput],
    repo_root: &Path,
) -> std::thread::JoinHandle<HashMap<String, u32>> {
    let files: Vec<String> = output.iter().flat_map(|o| o.files.clone()).collect();
    let root = repo_root.to_path_buf();
    std::thread::spawn(move || crate::churn::commit_counts_batch(&files, &root))
}

/// Backfill `files.churn` with each file's 90-day commit count.
///
/// The count was precomputed by [`spawn_churn`]'s background `git log
/// --name-only` walk (0 on any git failure, untracked file, or non-repo
/// directory); this joins that thread and writes the result.
fn write_churn(
    conn: &rusqlite::Connection,
    output: &[ExtractOutput],
    file_ids: &FileIds,
    churn_handle: std::thread::JoinHandle<HashMap<String, u32>>,
) -> Result<()> {
    let counts = churn_handle.join().unwrap_or_default();
    let mut stmt = conn.prepare("UPDATE files SET churn = ?1 WHERE id = ?2")?;
    for (out_idx, out) in output.iter().enumerate() {
        for (local_file_id, path) in out.files.iter().enumerate() {
            let count = counts.get(path).copied().unwrap_or(0);
            stmt.execute(rusqlite::params![
                count,
                file_ids.get(out_idx, local_file_id as u32)
            ])?;
        }
    }
    Ok(())
}

/// Insert `resolved_edges` rows from `ResolvedGraph::edges`.
///
/// Target mapping: `EdgeTarget::File(f)` → the target node's file id;
/// `EdgeTarget::Entity(i)` → the file id of the flattened entity at index
/// `i` (same flat `Vec<Entity>` order `resolve()` consumed); `Unknown` →
/// NULL `to_file_id`. Unresolved edges are persisted, not dropped.
///
/// `edge.from_entity` (`Call`-kind edges only) is looked up in `entity_ids`
/// — the same flat index `write_entities` returns — to persist the
/// call-site entity's actual DB id as `from_entity_id`, letting rules join
/// back to that entity's `enclosing_function` for per-function aggregation.
fn write_edges(
    conn: &rusqlite::Connection,
    output: &[ExtractOutput],
    graph: &ResolvedGraph,
    file_ids: &FileIds,
    entity_ids: &EntityIdIndex,
) -> Result<()> {
    let entities: Vec<(usize, &crate::model::Entity)> = output
        .iter()
        .enumerate()
        .flat_map(|(out_idx, o)| o.entities.iter().map(move |e| (out_idx, e)))
        .collect();

    let rows: Vec<EdgeRow> = graph
        .edges
        .iter()
        .map(|edge| edge_row(edge, &entities, file_ids, entity_ids))
        .collect();

    batch_insert(
        conn,
        |n| {
            multi_insert_sql(
                "resolved_edges (from_file_id, to_file_id, kind, resolved, from_entity_id, to_entity_id)",
                "(?, ?, ?, ?, ?, ?)",
                n,
            )
        },
        6,
        &rows,
        |params, row| {
            params.push(&row.0);
            params.push(&row.1);
            params.push(&row.2);
            params.push(&row.3);
            params.push(&row.4);
            params.push(&row.5);
        },
    )?;
    Ok(())
}

type EdgeRow = (i64, Option<i64>, i64, i64, Option<i64>, Option<i64>);

fn edge_row(
    edge: &ResolvedEdge,
    entities: &[(usize, &crate::model::Entity)],
    file_ids: &FileIds,
    entity_ids: &EntityIdIndex,
) -> EdgeRow {
    let target_file = if edge.resolved {
        match edge.to {
            EdgeTarget::File(file) => Some(file_ids.by_node(file)),
            EdgeTarget::Entity(entity) => entities
                .get(entity as usize)
                .map(|(output, entity)| file_ids.get(*output, entity.file_id)),
            EdgeTarget::Unknown => None,
        }
    } else {
        None
    };
    let target_entity = match (edge.resolved, edge.to) {
        (true, EdgeTarget::Entity(entity)) => entity_id_at(entity_ids, entity as usize),
        _ => None,
    };
    let source_entity = edge
        .from_entity
        .and_then(|entity| entity_id_at(entity_ids, entity as usize));
    (
        file_ids.by_node(edge.from),
        target_file,
        edge.kind.as_i64(),
        i64::from(edge.resolved),
        source_entity,
        target_entity,
    )
}

/// Insert `diagnostics` rows: per-file ones keyed to their file's `files.id`,
/// traversal failures with a NULL `file_id` and their path alone.
///
/// Persists whatever `parsing-extraction` produced — no severity taxonomy
/// re-validation.
fn write_diagnostics(
    conn: &rusqlite::Connection,
    output: &[ExtractOutput],
    file_ids: &FileIds,
) -> Result<()> {
    let rows: Vec<(Option<i64>, &str, &str, &str)> = output
        .iter()
        .enumerate()
        .flat_map(|(out_idx, out)| {
            out.diagnostics.iter().map(move |d| {
                (
                    d.file_id.map(|file_id| file_ids.get(out_idx, file_id)),
                    d.path.as_str(),
                    d.message.as_str(),
                    d.severity.as_str(),
                )
            })
        })
        .collect();

    batch_insert(
        conn,
        |n| {
            multi_insert_sql(
                "diagnostics (file_id, path, message, severity)",
                "(?, ?, ?, ?)",
                n,
            )
        },
        4,
        &rows,
        |params, row| {
            params.push(&row.0);
            params.push(&row.1);
            params.push(&row.2);
            params.push(&row.3);
        },
    )?;
    Ok(())
}

/// Replace every persisted traversal diagnostic with the current walk's.
///
/// Traversal diagnostics have no `file_id`, so the per-file `DELETE ... WHERE
/// file_id IN (...)` that incremental builds run never reaches them. Without
/// this an unreadable directory, once fixed, would keep reporting forever.
/// The delete runs even when `diagnostics` is empty — that empty case *is* the
/// "failure resolved" signal.
pub(crate) fn replace_traversal_diagnostics(
    conn: &rusqlite::Connection,
    diagnostics: &[crate::model::Diagnostic],
) -> Result<()> {
    conn.execute("DELETE FROM diagnostics WHERE file_id IS NULL", [])?;
    let rows: Vec<(&str, &str, &str)> = diagnostics
        .iter()
        .map(|d| (d.path.as_str(), d.message.as_str(), d.severity.as_str()))
        .collect();
    batch_insert(
        conn,
        |n| {
            multi_insert_sql(
                "diagnostics (file_id, path, message, severity)",
                "(NULL, ?, ?, ?)",
                n,
            )
        },
        3,
        &rows,
        |params, row| {
            params.push(&row.0);
            params.push(&row.1);
            params.push(&row.2);
        },
    )?;
    Ok(())
}

/// Serialize a function's per-band MinHash signatures into a compact BLOB
/// (one little-endian `u64` per band).
fn minhash_to_blob(sigs: &[u64]) -> Vec<u8> {
    let mut out = Vec::with_capacity(sigs.len() * 8);
    for s in sigs {
        out.extend_from_slice(&s.to_le_bytes());
    }
    out
}

/// Deserialize a `body_minhash` BLOB back into per-band signatures.
fn blob_to_minhash(blob: &[u8]) -> Option<Vec<u64>> {
    if !blob.len().is_multiple_of(8) {
        return None;
    }
    // `as_chunks::<8>()` yields `&[u8; 8]` directly (no fallible `try_into`);
    // the remainder is provably empty given the `is_multiple_of(8)` guard above.
    Some(
        blob.as_chunks::<8>()
            .0
            .iter()
            .map(|c| u64::from_le_bytes(*c))
            .collect(),
    )
}

/// Inserted `entities.id` rowids, indexed by flat entity index (the same
/// concatenation order [`write_entities`] inserts and [`write_clone_bands`]
/// consumes). Rowids are consecutive per chunk, so a flat `Vec` in that order
/// replaces the old `(file_id, start_byte, end_byte)` map, its ~130 MB peak,
/// and its latent last-wins span-collision bug.
type EntityIdIndex = Vec<i64>;

/// Read the persisted rowid for a flat entity index, asserting it is not the
/// dropped-kind `-1` sentinel (see [`is_dropped_kind`]). Dropped kinds are
/// never referenced as `from_entity`/clone members; a future change that does
/// so should fail loudly in debug/test builds instead of silently persisting
/// an FK to nothing.
fn entity_id_at(entity_ids: &EntityIdIndex, flat_index: usize) -> Option<i64> {
    let id = entity_ids.get(flat_index).copied();
    debug_assert!(
        id.is_none_or(|v| v != -1),
        "referenced a dropped entity kind (flat index {flat_index})"
    );
    id
}

/// Insert `entities` rows in batches, each keyed to its file's `files.id`.
/// Entity kinds extracted and used at build time (they feed derived columns
/// and the call graph) but read back out of the index by *no* rule, query
/// mode, or resolver. They are not persisted, which shrinks the `entities`
/// table substantially at zero consumer impact. `ControlFlow` is deliberately
/// NOT here — one `complexity` rule joins it live and it feeds the
/// `files.complexity` count.
///
/// `Variable` and `Parameter` were previously dropped too, but they ARE read
/// back: `declaration_kinds()` (the contract behind `symbols_in_file`,
/// `get_symbol`, and `filter_symbols`) lists both, so dropping them made every
/// field/property/constant/parameter invisible to exactly the queries meant to
/// surface them (audit S3: Java `@Column` fields, C#/PHP properties, TS module
/// consts, Ruby attrs all "not captured"). They are now persisted.
fn is_dropped_kind(kind: EntityKind) -> bool {
    matches!(
        kind,
        EntityKind::Literal | EntityKind::MemberAccess | EntityKind::Catch | EntityKind::Throw
    )
}

/// Returns a flat `Vec` of inserted rowids, indexed by the same flat entity
/// index [`write_clone_bands`] uses for `band.members`. Dropped-kind entities
/// (see [`is_dropped_kind`]) are not inserted; their slot holds a `-1` sentinel
/// that is never dereferenced (only kept kinds are referenced as
/// `from_entity`/clone members).
fn write_entities(
    conn: &rusqlite::Connection,
    output: &[ExtractOutput],
    file_ids: &FileIds,
) -> Result<(EntityIdIndex, Vec<u32>)> {
    let mut complexity_counts = vec![0u32; file_ids.flat.len()];
    let rows = collect_entity_rows(output, file_ids, &mut complexity_counts);
    let ids = insert_entity_rows(conn, &rows)?;
    Ok((ids, complexity_counts))
}

#[allow(clippy::type_complexity)]
type EntityInsertRow<'a> = (
    i64,
    i64,
    &'a str,
    i64,
    i64,
    i64,
    i64,
    i64,
    i64,
    Option<&'a str>,
    Option<&'a str>,
    Option<&'a str>,
    Option<&'a str>,
    Option<&'a str>,
    Option<Vec<u8>>,
    Option<bool>,
    bool,
    Option<&'a str>,
);

fn collect_entity_rows<'a>(
    output: &'a [ExtractOutput],
    file_ids: &FileIds,
    complexity_counts: &mut [u32],
) -> Vec<EntityInsertRow<'a>> {
    let total = output.iter().map(|item| item.entities.len()).sum();
    let mut rows = Vec::with_capacity(total);
    for (out_idx, out) in output.iter().enumerate() {
        let offset = file_ids.offsets[out_idx];
        for e in &out.entities {
            if e.kind == EntityKind::ControlFlow {
                complexity_counts[offset + e.file_id as usize] += 1;
            }
            rows.push((
                e.kind.as_i64(),
                file_ids.get(out_idx, e.file_id),
                e.name.as_str(),
                e.span.start_byte as i64,
                e.span.end_byte as i64,
                e.span.start_line as i64,
                e.span.start_col as i64,
                e.span.end_line as i64,
                e.span.end_col as i64,
                e.enclosing_function.as_deref(),
                e.method.as_deref(),
                e.path.as_deref(),
                e.status.as_deref(),
                e.body_shape.as_deref(),
                e.body_minhash.as_ref().map(|sigs| minhash_to_blob(sigs)),
                e.is_async,
                e.is_test,
                e.owner_type.as_deref(),
            ));
        }
    }
    rows
}

fn insert_entity_rows(
    conn: &rusqlite::Connection,
    rows: &[EntityInsertRow<'_>],
) -> Result<Vec<i64>> {
    let kept: Vec<(usize, &_)> = rows
        .iter()
        .enumerate()
        .filter(|(_, row)| EntityKind::from_i64(row.0).is_none_or(|k| !is_dropped_kind(k)))
        .collect();

    let mut ids = vec![-1i64; rows.len()];
    let first_rowid = batch_insert(conn, entities_insert_sql, 18, &kept, |params, kept_row| {
        let row = kept_row.1;
        params.push(&row.0);
        params.push(&row.1);
        params.push(&row.2);
        params.push(&row.3);
        params.push(&row.4);
        params.push(&row.5);
        params.push(&row.6);
        params.push(&row.7);
        params.push(&row.8);
        params.push(&row.9);
        params.push(&row.10);
        params.push(&row.11);
        params.push(&row.12);
        params.push(&row.13);
        params.push(&row.14);
        params.push(&row.15);
        params.push(&row.16);
        params.push(&row.17);
    })?;
    if let Some(first_rowid) = first_rowid {
        for (offset, &(flat_idx, _)) in kept.iter().enumerate() {
            ids[flat_idx] = first_rowid + offset as i64;
        }
    }
    Ok(ids)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Diagnostic, Entity, EntityKind, FileMeta, Span, Symbol, SymbolKind};

    /// A persisted `entities` row (kind, name, file_id, byte/line span,
    /// enclosing_function, method, path, status, body_shape).
    type EntityRow = (
        i64,
        String,
        i64,
        i64,
        i64,
        i64,
        i64,
        i64,
        i64,
        Option<String>,
        Option<String>,
        Option<String>,
        Option<String>,
        Option<String>,
    );

    /// A persisted `symbols` row (kind, name, file_id, byte/line span).
    type SymbolRow = (i64, String, i64, i64, i64, i64, i64, i64, i64);

    /// A persisted `resolved_edges` row joined with file paths (from_file_id,
    /// to_file_id, kind, resolved, from path, to path, to_entity_id).
    type ResolvedEdgeRow = (
        i64,
        Option<i64>,
        i64,
        i64,
        String,
        Option<String>,
        Option<i64>,
    );

    pub fn span() -> Span {
        Span {
            start_byte: 0,
            end_byte: 4,
            start_line: 1,
            start_col: 0,
            end_line: 1,
            end_col: 4,
        }
    }

    pub fn entity(file_id: u32, name: &str) -> Entity {
        Entity {
            kind: EntityKind::Function,
            name: name.to_string(),
            file_id,
            span: span(),
            enclosing_function: None,
            method: None,
            path: None,
            status: None,
            body_shape: None,
            body_minhash: None,
            is_async: None,
            is_test: false,
            owner_type: None,
        }
    }

    pub fn symbol(file_id: u32, name: &str) -> Symbol {
        Symbol {
            kind: SymbolKind::Binding,
            name: name.to_string(),
            file_id,
            span: span(),
        }
    }

    #[allow(dead_code)]
    pub fn diagnostic(file_id: u32, message: &str) -> Diagnostic {
        Diagnostic {
            file_id: Some(file_id),
            path: format!("file{file_id}.rs"),
            message: message.to_string(),
            severity: "error".to_string(),
        }
    }

    /// A valid, deterministic placeholder for scan-time file metadata used by
    /// tests that don't assert mtime/size/content_hash.
    pub fn dummy_meta() -> FileMeta {
        FileMeta {
            mtime: 0,
            size: 0,
            content_hash: "0000000000000000".to_string(),
        }
    }

    /// One `ExtractOutput` per distinct path, each with a single-entry file
    /// table (`file_id` 0 within its own output) — matches the pre-interning
    /// fixture shape where every test file stood alone. Duplicate paths
    /// collapse before building outputs, matching `scan::run`'s guarantee
    /// that a real `files` table never repeats a path (persistence no longer
    /// dedupes across `ExtractOutput`s itself — see `FileIds`).
    pub fn output(files: &[&str]) -> Vec<ExtractOutput> {
        let mut seen = std::collections::HashSet::new();
        files
            .iter()
            .filter(|f| seen.insert(**f))
            .map(|f| ExtractOutput {
                entities: vec![entity(0, "fn")],
                symbols: vec![symbol(0, "fn")],
                diagnostics: vec![],
                files: vec![f.to_string()],
                file_meta: vec![dummy_meta()],
            })
            .collect()
    }

    pub fn temp_db(tag: &str) -> std::path::PathBuf {
        let dir =
            std::env::temp_dir().join(format!("varde-persist-{}-{}", tag, std::process::id()));
        std::fs::create_dir_all(&dir).expect("temp dir creates");
        let db = dir.join("index.db");
        let _ = std::fs::remove_file(&db);
        db
    }

    pub fn empty_graph() -> ResolvedGraph {
        ResolvedGraph {
            nodes: vec![],
            edges: vec![],
            communities: vec![],
            clone_bands: vec![],
        }
    }

    fn row_count(conn: &rusqlite::Connection, table: &str) -> i64 {
        conn.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r.get(0))
            .expect("count query works")
    }

    #[test]
    fn shared_batch_insert_handles_empty_tail_and_sparse_entity_ids() {
        let db_path = temp_db("shared-batch-insert");
        let conn = crate::db::open_or_rebuild(&db_path).expect("schema creates");
        let mut output = vec![ExtractOutput {
            entities: vec![],
            symbols: vec![],
            diagnostics: vec![],
            files: vec!["a.rs".to_string()],
            file_meta: vec![dummy_meta()],
        }];
        let file_ids = write_files(&conn, &output).expect("file writes");

        let (empty_ids, _) = write_entities(&conn, &output, &file_ids).expect("empty entities");
        write_symbols(&conn, &output, &file_ids).expect("empty symbols");
        assert!(empty_ids.is_empty());

        let mut dropped = entity(0, "literal");
        dropped.kind = EntityKind::Literal;
        output[0].entities.push(dropped);
        output[0]
            .entities
            .extend((0..501).map(|i| entity(0, &format!("entity_{i}"))));
        output[0]
            .symbols
            .extend((0..501).map(|i| symbol(0, &format!("symbol_{i}"))));

        let (ids, _) = write_entities(&conn, &output, &file_ids).expect("entities write");
        write_symbols(&conn, &output, &file_ids).expect("symbols write");

        assert_eq!(row_count(&conn, "entities"), 501);
        assert_eq!(row_count(&conn, "symbols"), 501);
        assert_eq!(ids.len(), 502);
        assert_eq!(ids[0], -1, "dropped entity keeps its sentinel slot");
        assert_eq!(ids[501] - ids[1], 500, "kept rowids remain contiguous");
    }

    /// Every row of `table` rendered to comparable strings, ordered by rowid
    /// (insertion order) — used to assert two builds produced identical tables.
    fn dump_table(conn: &rusqlite::Connection, table: &str) -> Vec<String> {
        let mut stmt = conn
            .prepare(&format!("SELECT * FROM {table} ORDER BY 1"))
            .expect("dump query prepares");
        let ncol = stmt.column_count();
        let rows: Vec<String> = stmt
            .query_map([], |r| {
                let mut rendered = String::new();
                for i in 0..ncol {
                    let value: rusqlite::types::Value = r.get(i)?;
                    rendered.push_str(&format!("{value:?}|"));
                }
                Ok(rendered)
            })
            .expect("dump maps")
            .map(|r| r.expect("row ok"))
            .collect();
        rows
    }

    /// The streaming full build ([`persist_full_streaming`]) must produce a
    /// byte-identical index to the non-streaming path (`scan::run` then
    /// `resolve` then [`persist`]) — same rows, same row ids — so pipelining
    /// parse against persistence never changes what gets stored. Guards the
    /// invariant the roughly 18% build speedup rests on.
    #[test]
    fn streaming_matches_batch_build() {
        let root = std::env::temp_dir().join(format!(
            "varde-stream-eq-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock after epoch")
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).expect("temp repo dir");
        // Cross-file call (b -> a) and a base/derived pair (c) so entities,
        // symbols, resolved call edges, and type-hierarchy edges all populate.
        std::fs::write(root.join("a.py"), "def helper():\n    return 1\n").expect("write a");
        std::fs::write(
            root.join("b.py"),
            "from a import helper\n\ndef main():\n    return helper()\n",
        )
        .expect("write b");
        std::fs::write(
            root.join("c.py"),
            "class Base:\n    pass\n\n\nclass Child(Base):\n    def run(self):\n        return 2\n",
        )
        .expect("write c");
        let root_str = root.to_str().expect("utf-8 path");
        // DBs live OUTSIDE the scanned repo so neither build's output file is
        // picked up as a source file by the other build's walk.
        let batch_db = root.with_extension("batch.db");
        let stream_db = root.with_extension("stream.db");

        // Non-streaming reference build.
        let output = crate::scan::run(root_str).expect("scan");
        let graph = crate::resolve::resolve(&output.entities, &output.symbols, &output.files)
            .expect("resolve");
        persist(&batch_db, std::slice::from_ref(&output), &graph, &root).expect("batch persist");

        // Streaming build over the same files.
        let listing = crate::scan::list_source_listing(root_str).expect("list files");
        persist_full_streaming(&stream_db, listing, &root).expect("streaming persist");

        let batch = rusqlite::Connection::open(&batch_db).expect("batch db opens");
        let stream = rusqlite::Connection::open(&stream_db).expect("stream db opens");
        for table in [
            "files",
            "entities",
            "symbols",
            "diagnostics",
            "resolved_edges",
            "communities",
            "community_members",
            "clone_bands",
            "clone_band_members",
        ] {
            assert_eq!(
                dump_table(&batch, table),
                dump_table(&stream, table),
                "table {table} differs between batch and streaming build",
            );
        }

        let _ = std::fs::remove_dir_all(&root);
        let _ = std::fs::remove_file(&batch_db);
        let _ = std::fs::remove_file(&stream_db);
    }

    mod files_table_one_row_per_file {
        use super::*;

        #[test]
        fn one_row_per_distinct_path() {
            let db_path = temp_db("files");
            let output = output(&["a.rs", "b.rs", "a.rs", "c.rs"]);

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            assert_eq!(row_count(&conn, "files"), 3);
            let mut stmt = conn
                .prepare("SELECT path FROM files ORDER BY path")
                .expect("query prepares");
            let paths: Vec<String> = stmt
                .query_map([], |r| r.get(0))
                .expect("maps")
                .map(|r| r.expect("row ok"))
                .collect();
            assert_eq!(paths, vec!["a.rs", "b.rs", "c.rs"]);
        }

        #[test]
        fn file_meta_is_persisted_from_scan_output() {
            // `write_files` must write the scan-time metadata verbatim (it no
            // longer re-stats or re-reads file bytes); the content-hash
            // computation itself is covered by `scan`'s unit test.
            let db_path = temp_db("files-state");
            let output = vec![ExtractOutput {
                entities: vec![entity(0, "fn")],
                symbols: vec![symbol(0, "fn")],
                diagnostics: vec![],
                files: vec!["a.rs".to_string()],
                file_meta: vec![FileMeta {
                    mtime: 1_700_000_000_000_000_000,
                    size: 42,
                    content_hash: "deadbeefdeadbeef".to_string(),
                }],
            }];
            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let row: (i64, i64, String) = conn
                .query_row("SELECT mtime, size, content_hash FROM files", [], |r| {
                    Ok((r.get(0)?, r.get(1)?, r.get(2)?))
                })
                .expect("file state reads");

            assert_eq!(row.0, 1_700_000_000_000_000_000);
            assert_eq!(row.1, 42);
            assert_eq!(row.2, "deadbeefdeadbeef");
        }

        #[test]
        fn churn_fan_and_community_default_until_backfilled() {
            let db_path = temp_db("files-placeholder");
            let output = output(&["a.rs"]);

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            // Complexity and churn are backfilled at persist time (base 1 +
            // decision points; 0 for a non-repo path); fan_in/fan_out/
            // community_id stay at defaults without a graph.
            let row: (Option<i64>, Option<i64>, i64, i64, Option<i64>) = conn
                .query_row(
                    "SELECT complexity, churn, fan_in, fan_out, community_id FROM files",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
                )
                .expect("row reads");
            assert_eq!(row, (Some(1), Some(0), 0, 0, None));
        }

        #[test]
        fn second_run_replaces_first_run() {
            let db_path = temp_db("files-replace");
            let first = output(&["a.rs", "b.rs"]);
            persist(
                &db_path,
                &first,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("first persist succeeds");

            let second = output(&["c.rs", "d.rs"]);
            persist(
                &db_path,
                &second,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("second persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            assert_eq!(row_count(&conn, "files"), 2, "no leftover rows from run 1");
            let mut stmt = conn
                .prepare("SELECT path FROM files ORDER BY path")
                .expect("query prepares");
            let paths: Vec<String> = stmt
                .query_map([], |r| r.get(0))
                .expect("maps")
                .map(|r| r.expect("row ok"))
                .collect();
            assert_eq!(paths, vec!["c.rs", "d.rs"]);
        }
    }

    mod entities_table_field_roundtrip {
        use super::*;

        #[test]
        fn all_fields_roundtrip_exactly() {
            let db_path = temp_db("entities");
            let mut entity = entity(0, "handler");
            entity.kind = EntityKind::Route;
            entity.span = Span {
                start_byte: 10,
                end_byte: 42,
                start_line: 3,
                start_col: 2,
                end_line: 5,
                end_col: 9,
            };
            entity.enclosing_function = Some("outer".to_string());
            entity.method = Some("get".to_string());
            entity.path = Some("/api/items".to_string());
            entity.status = Some("200".to_string());
            entity.body_shape = Some("json".to_string());
            let output = vec![ExtractOutput {
                entities: vec![entity],
                symbols: vec![],
                diagnostics: vec![],
                files: vec!["a.rs".to_string()],
                file_meta: vec![dummy_meta()],
            }];

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let row: EntityRow = conn
                .query_row(
                    "SELECT kind, name, file_id, start_byte, end_byte, start_line, start_col, end_line, end_col, enclosing_function, method, path, status, body_shape FROM entities",
                    [],
                    |r| {
                        Ok((
                            r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?,
                            r.get(6)?, r.get(7)?, r.get(8)?, r.get(9)?, r.get(10)?, r.get(11)?,
                            r.get(12)?, r.get(13)?,
                        ))
                    },
                )
                .expect("row reads");
            assert_eq!(row.0, EntityKind::Route.as_i64());
            assert_eq!(row.1, "handler");
            assert_eq!(row.3, 10);
            assert_eq!(row.4, 42);
            assert_eq!(row.5, 3);
            assert_eq!(row.6, 2);
            assert_eq!(row.7, 5);
            assert_eq!(row.8, 9);
            assert_eq!(row.9.as_deref(), Some("outer"));
            assert_eq!(row.10.as_deref(), Some("get"));
            assert_eq!(row.11.as_deref(), Some("/api/items"));
            assert_eq!(row.12.as_deref(), Some("200"));
            assert_eq!(row.13.as_deref(), Some("json"));
        }

        #[test]
        fn callable_boundary_persists_for_containment_queries() {
            let db_path = temp_db("callable-boundary");
            let mut boundary = entity(0, "");
            boundary.kind = EntityKind::CallableBoundary;
            boundary.span = Span {
                start_byte: 10,
                end_byte: 42,
                start_line: 2,
                start_col: 4,
                end_line: 4,
                end_col: 5,
            };
            let output = vec![ExtractOutput {
                entities: vec![boundary],
                symbols: vec![],
                diagnostics: vec![],
                files: vec!["a.rs".to_string()],
                file_meta: vec![dummy_meta()],
            }];

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let row: (i64, String, i64, i64) = conn
                .query_row(
                    "SELECT kind, name, start_byte, end_byte FROM entities",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
                )
                .expect("boundary reads");
            assert_eq!(row.0, EntityKind::CallableBoundary.as_i64());
            assert_eq!(row.1, "");
            assert_eq!(row.2, 10);
            assert_eq!(row.3, 42);
        }

        #[test]
        fn file_id_links_to_matching_files_row() {
            let db_path = temp_db("entities-file");
            let output = output(&["a.rs"]);

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let (entity_fid, file_id_value, file_path): (i64, i64, String) = conn
                .query_row(
                    "SELECT e.file_id, f.id, f.path FROM entities e JOIN files f ON f.id = e.file_id",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
                )
                .expect("join reads");
            assert_eq!(entity_fid, file_id_value);
            assert_eq!(file_path, "a.rs");
        }

        #[test]
        fn unknown_file_still_persists_via_insert() {
            let db_path = temp_db("entities-unknown");
            let mut orphan = entity(0, "orphan_fn");
            orphan.kind = EntityKind::Call;
            let output = vec![ExtractOutput {
                entities: vec![orphan],
                symbols: vec![],
                diagnostics: vec![],
                files: vec!["orphan.rs".to_string()],
                file_meta: vec![dummy_meta()],
            }];

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let (fid, path): (i64, String) = conn
                .query_row(
                    "SELECT e.file_id, f.path FROM entities e JOIN files f ON f.id = e.file_id",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .expect("join reads");
            assert_eq!(path, "orphan.rs");
            assert!(fid > 0);
        }
    }

    mod symbols_table_field_roundtrip {
        use super::*;

        #[test]
        fn fields_roundtrip_and_kinds_distinguishable() {
            let db_path = temp_db("symbols");
            let mut b = symbol(0, "helper");
            b.kind = SymbolKind::Binding;
            b.span = Span {
                start_byte: 5,
                end_byte: 11,
                start_line: 2,
                start_col: 0,
                end_line: 2,
                end_col: 6,
            };
            let mut r = symbol(0, "helper_ref");
            r.kind = SymbolKind::Reference;
            r.name = "helper".to_string();
            let output = vec![ExtractOutput {
                entities: vec![],
                symbols: vec![b, r],
                diagnostics: vec![],
                files: vec!["a.rs".to_string()],
                file_meta: vec![dummy_meta()],
            }];

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let rows: Vec<SymbolRow> = {
                let mut stmt = conn
                    .prepare(
                        "SELECT kind, name, file_id, start_byte, end_byte, start_line, start_col, end_line, end_col FROM symbols ORDER BY id",
                    )
                    .expect("query prepares");
                stmt.query_map([], |r| {
                    Ok((
                        r.get(0)?,
                        r.get(1)?,
                        r.get(2)?,
                        r.get(3)?,
                        r.get(4)?,
                        r.get(5)?,
                        r.get(6)?,
                        r.get(7)?,
                        r.get(8)?,
                    ))
                })
                .expect("maps")
                .map(|r| r.expect("row ok"))
                .collect()
            };
            assert_eq!(rows.len(), 2);
            // Binding row roundtrips fields exactly.
            assert_eq!(rows[0].0, SymbolKind::Binding.as_i64());
            assert_eq!(rows[0].1, "helper");
            assert_eq!(rows[0].3, 5);
            assert_eq!(rows[0].4, 11);
            assert_eq!(rows[0].5, 2);
            assert_eq!(rows[0].6, 0);
            assert_eq!(rows[0].7, 2);
            assert_eq!(rows[0].8, 6);
            // Reference row kind is distinguishable by query.
            assert_eq!(rows[1].0, SymbolKind::Reference.as_i64());
            assert_eq!(rows[1].1, "helper");
            let kinds: Vec<i64> = {
                let mut stmt = conn
                    .prepare("SELECT kind FROM symbols ORDER BY id")
                    .expect("query prepares");
                stmt.query_map([], |r| r.get(0))
                    .expect("maps")
                    .map(|r| r.expect("row ok"))
                    .collect()
            };
            assert_eq!(
                kinds,
                vec![SymbolKind::Binding.as_i64(), SymbolKind::Reference.as_i64()]
            );
        }

        #[test]
        fn file_id_links_to_matching_files_row() {
            let db_path = temp_db("symbols-file");
            let output = vec![ExtractOutput {
                entities: vec![],
                symbols: vec![symbol(0, "sym")],
                diagnostics: vec![],
                files: vec!["x.rs".to_string()],
                file_meta: vec![dummy_meta()],
            }];

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let (sym_fid, file_id_value, path): (i64, i64, String) = conn
                .query_row(
                    "SELECT s.file_id, f.id, f.path FROM symbols s JOIN files f ON f.id = s.file_id",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
                )
                .expect("join reads");
            assert_eq!(sym_fid, file_id_value);
            assert_eq!(path, "x.rs");
        }
    }

    mod diagnostics_table_field_roundtrip {
        use super::*;

        #[test]
        fn message_severity_roundtrip_and_file_linkage() {
            let db_path = temp_db("diagnostics");
            let output = vec![ExtractOutput {
                entities: vec![],
                symbols: vec![],
                diagnostics: vec![diagnostic(0, "syntax error — skipped")],
                files: vec!["y.rs".to_string()],
                file_meta: vec![dummy_meta()],
            }];

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let (fid, message, severity, path): (i64, String, String, String) = conn
                .query_row(
                    "SELECT d.file_id, d.message, d.severity, f.path FROM diagnostics d JOIN files f ON f.id = d.file_id",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
                )
                .expect("row reads");
            assert_eq!(message, "syntax error — skipped");
            assert_eq!(severity, "error");
            assert_eq!(path, "y.rs");
            assert!(fid > 0);
        }

        #[test]
        fn diagnostic_only_file_still_persists() {
            let db_path = temp_db("diagnostics-only");
            // File appears in NO entity and NO symbol — only a diagnostic.
            let output = vec![ExtractOutput {
                entities: vec![],
                symbols: vec![],
                diagnostics: vec![diagnostic(0, "cannot read directory")],
                files: vec!["orphan-diagnostics.rs".to_string()],
                file_meta: vec![dummy_meta()],
            }];

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let count: i64 = row_count(&conn, "diagnostics");
            assert_eq!(count, 1);
            let (fid, path): (i64, String) = conn
                .query_row(
                    "SELECT d.file_id, f.path FROM diagnostics d JOIN files f ON f.id = d.file_id",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .expect("join reads");
            assert_eq!(path, "orphan-diagnostics.rs");
            assert!(fid > 0);
        }
    }

    mod resolved_edges_table_roundtrip {
        use super::*;
        use crate::resolve::{EdgeKind, EdgeTarget, FileNode, ResolvedEdge};

        fn graph_with_edges() -> (ResolvedGraph, Vec<ExtractOutput>) {
            let graph = ResolvedGraph {
                nodes: vec![
                    FileNode {
                        path: "a.rs".to_string(),
                        community_id: None,
                        fan_in: 0,
                        fan_out: 0,
                    },
                    FileNode {
                        path: "b.rs".to_string(),
                        community_id: None,
                        fan_in: 0,
                        fan_out: 0,
                    },
                ],
                edges: vec![
                    ResolvedEdge {
                        from: 0,
                        to: EdgeTarget::File(1),
                        kind: EdgeKind::Import,
                        resolved: true,
                        from_entity: None,
                    },
                    ResolvedEdge {
                        from: 0,
                        to: EdgeTarget::Unknown,
                        kind: EdgeKind::Call,
                        resolved: false,
                        from_entity: None,
                    },
                ],
                communities: vec![],
                clone_bands: vec![],
            };
            // a.rs declares fn (entity idx 0) so the call edge target can
            // also be exercised as an entity target in the first test below.
            let mut a_entity = entity(0, "helper");
            a_entity.kind = EntityKind::Function;
            let output = vec![ExtractOutput {
                entities: vec![a_entity],
                symbols: vec![],
                diagnostics: vec![],
                // Must match graph.nodes order: node index == file_id here.
                files: vec!["a.rs".to_string(), "b.rs".to_string()],
                file_meta: vec![dummy_meta(), dummy_meta()],
            }];
            (graph, output)
        }

        #[test]
        fn all_edges_persist_with_kinds_and_resolved_flag() {
            let db_path = temp_db("edges");
            let (graph, output) = graph_with_edges();

            persist(
                &db_path,
                &output,
                &graph,
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            assert_eq!(
                row_count(&conn, "resolved_edges"),
                2,
                "exactly M rows for M edges"
            );

            let rows: Vec<ResolvedEdgeRow> = {
                let mut stmt = conn
                    .prepare(
                        "SELECT e.from_file_id, e.to_file_id, e.kind, e.resolved, f1.path, f2.path, e.to_entity_id
                         FROM resolved_edges e
                         JOIN files f1 ON f1.id = e.from_file_id
                         LEFT JOIN files f2 ON f2.id = e.to_file_id
                         ORDER BY e.id",
                    )
                    .expect("query prepares");
                stmt.query_map([], |r| {
                    Ok((
                        r.get(0)?,
                        r.get(1)?,
                        r.get(2)?,
                        r.get(3)?,
                        r.get(4)?,
                        r.get(5)?,
                        r.get(6)?,
                    ))
                })
                .expect("maps")
                .map(|r| r.expect("row ok"))
                .collect()
            };

            // Import edge: a.rs -> b.rs, resolved.
            assert_eq!(rows[0].0, 1); // a.rs files.id
            assert_eq!(rows[0].1, Some(2)); // b.rs files.id
            assert_eq!(rows[0].2, EdgeKind::Import.as_i64());
            assert_eq!(rows[0].3, 1);
            assert_eq!(rows[0].4, "a.rs");
            assert_eq!(rows[0].5.as_deref(), Some("b.rs"));
            assert_eq!(
                rows[0].6, None,
                "Import (file-to-file) edge persists NULL to_entity_id, unchanged"
            );

            // Call edge: a.rs -> unresolved, kind distinguishable.
            assert_eq!(rows[1].2, EdgeKind::Call.as_i64());
            assert_eq!(rows[1].3, 0, "unresolved persists with resolved=0");
            assert_eq!(
                rows[1].1, None,
                "Unknown target persists as NULL to_file_id"
            );
            assert_eq!(rows[1].4, "a.rs");
            assert_eq!(rows[1].5, None);
            assert_eq!(
                rows[1].6, None,
                "unresolved edge persists NULL to_entity_id"
            );
        }

        // The tripwire is a `debug_assert!`, compiled out under `--release`, so
        // this `#[should_panic]` test can only fire in a debug build. Gate it on
        // `debug_assertions` rather than let it fail under `cargo test --release`.
        #[cfg(debug_assertions)]
        #[test]
        #[should_panic(expected = "dropped entity kind")]
        fn call_site_referencing_dropped_kind_fails_loudly() {
            // A Call edge whose from_entity points at a Literal (a dropped
            // kind) would dereference the -1 sentinel in entity_ids; the
            // tripwire must fire instead of silently persisting an FK to
            // nothing. Literal is flat index 1 (Function is 0), so
            // entity_ids[1] holds -1 after write_entities.
            let db_path = temp_db("dropped-from-entity");
            let mut lit = entity(0, "42");
            lit.kind = EntityKind::Literal;
            let output = vec![ExtractOutput {
                entities: vec![entity(0, "helper"), lit],
                symbols: vec![],
                diagnostics: vec![],
                files: vec!["a.rs".to_string()],
                file_meta: vec![dummy_meta()],
            }];
            let graph = ResolvedGraph {
                nodes: vec![FileNode {
                    path: "a.rs".to_string(),
                    community_id: None,
                    fan_in: 0,
                    fan_out: 0,
                }],
                edges: vec![ResolvedEdge {
                    from: 0,
                    to: EdgeTarget::Unknown,
                    kind: EdgeKind::Call,
                    resolved: false,
                    from_entity: Some(1), // Literal's flat index
                }],
                communities: vec![],
                clone_bands: vec![],
            };
            persist(
                &db_path,
                &output,
                &graph,
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist must panic before returning");
        }

        #[test]
        fn entity_target_resolves_to_its_file() {
            let db_path = temp_db("edges-entity");
            let mut graph = graph_with_edges();
            // Replace the unknown call target with an entity target.
            graph.0.edges[1] = ResolvedEdge {
                from: 0,
                to: EdgeTarget::Entity(0), // the `helper` function in a.rs
                kind: EdgeKind::Call,
                resolved: true,
                from_entity: None,
            };

            persist(
                &db_path,
                &graph.1,
                &graph.0,
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let (to_fid, path, to_entity_id): (i64, String, Option<i64>) = conn
                .query_row(
                    "SELECT e.to_file_id, f.path, e.to_entity_id FROM resolved_edges e JOIN files f ON f.id = e.to_file_id WHERE e.kind = ?1",
                    [EdgeKind::Call.as_i64()],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
                )
                .expect("row reads");
            assert_eq!(path, "a.rs", "entity target maps to the declaring file");
            assert!(to_fid > 0);

            let entity_id: i64 = conn
                .query_row("SELECT id FROM entities WHERE name = 'helper'", [], |r| {
                    r.get(0)
                })
                .expect("entity row reads");
            assert_eq!(
                to_entity_id,
                Some(entity_id),
                "entity target's to_entity_id round-trips to the actual entity row id"
            );
        }
    }

    mod communities_membership_and_denormalization {
        use super::*;
        use crate::resolve::{Community, FileNode};

        fn graph_with_communities() -> (ResolvedGraph, Vec<ExtractOutput>) {
            let graph = ResolvedGraph {
                nodes: vec![
                    FileNode {
                        path: "a.rs".to_string(),
                        community_id: Some(0),
                        fan_in: 1,
                        fan_out: 2,
                    },
                    FileNode {
                        path: "b.rs".to_string(),
                        community_id: Some(0),
                        fan_in: 3,
                        fan_out: 0,
                    },
                    FileNode {
                        path: "c.rs".to_string(),
                        community_id: Some(1),
                        fan_in: 0,
                        fan_out: 4,
                    },
                ],
                edges: vec![],
                communities: vec![
                    Community {
                        id: 0,
                        members: vec!["a.rs".to_string(), "b.rs".to_string()],
                    },
                    Community {
                        id: 1,
                        members: vec!["c.rs".to_string()],
                    },
                ],
                clone_bands: vec![],
            };
            let output = output(&["a.rs", "b.rs", "c.rs"]);
            (graph, output)
        }

        #[test]
        fn communities_membership_and_denormalization() {
            let db_path = temp_db("communities");
            let (graph, output) = graph_with_communities();

            persist(
                &db_path,
                &output,
                &graph,
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            assert_eq!(
                row_count(&conn, "communities"),
                2,
                "exactly K rows for K communities"
            );
            assert_eq!(
                row_count(&conn, "community_members"),
                3,
                "one row per (community, file) pair"
            );

            // Every membership row references existing communities.id/files.id,
            // and the labels carry the upstream ids.
            let memberships: Vec<(i64, i64, String, String)> = {
                let mut stmt = conn
                    .prepare(
                        "SELECT cm.community_id, cm.file_id, c.label, f.path
                         FROM community_members cm
                         JOIN communities c ON c.id = cm.community_id
                         JOIN files f ON f.id = cm.file_id
                         ORDER BY f.path",
                    )
                    .expect("query prepares");
                stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))
                    .expect("maps")
                    .map(|r| r.expect("row ok"))
                    .collect()
            };
            assert_eq!(memberships.len(), 3);
            for (cid, fid, label, path) in &memberships {
                assert!(*cid > 0, "community_id references an existing row");
                assert!(*fid > 0, "file_id references an existing row");
                assert!(
                    label.starts_with("community-"),
                    "label derived from upstream id"
                );
                assert!(["a.rs", "b.rs", "c.rs"].contains(&path.as_str()));
            }

            // files.community_id equals the community that lists the file.
            let fid_a: i64 = conn
                .query_row("SELECT id FROM files WHERE path='a.rs'", [], |r| r.get(0))
                .unwrap();
            let fid_b: i64 = conn
                .query_row("SELECT id FROM files WHERE path='b.rs'", [], |r| r.get(0))
                .unwrap();
            let fid_c: i64 = conn
                .query_row("SELECT id FROM files WHERE path='c.rs'", [], |r| r.get(0))
                .unwrap();
            let a_com: i64 = conn
                .query_row("SELECT community_id FROM files WHERE id=?1", [fid_a], |r| {
                    r.get(0)
                })
                .unwrap();
            let b_com: i64 = conn
                .query_row("SELECT community_id FROM files WHERE id=?1", [fid_b], |r| {
                    r.get(0)
                })
                .unwrap();
            let c_com: i64 = conn
                .query_row("SELECT community_id FROM files WHERE id=?1", [fid_c], |r| {
                    r.get(0)
                })
                .unwrap();
            assert_eq!(a_com, b_com, "a.rs and b.rs share community 0");
            assert_ne!(a_com, c_com, "c.rs is in a different community");
            let memberships_for = |fid: i64| -> Vec<i64> {
                let mut stmt = conn
                    .prepare("SELECT community_id FROM community_members WHERE file_id = ?1")
                    .expect("query prepares");
                stmt.query_map([fid], |r| r.get(0))
                    .expect("maps")
                    .map(|r| r.expect("row ok"))
                    .collect()
            };
            assert!(
                memberships_for(fid_a).contains(&a_com),
                "files.community_id must be listed in community_members"
            );
            assert!(memberships_for(fid_b).contains(&b_com));
            assert!(memberships_for(fid_c).contains(&c_com));

            // fan_in/fan_out copied from FileNode, not recomputed.
            let (a_fi, a_fo): (i64, i64) = conn
                .query_row(
                    "SELECT fan_in, fan_out FROM files WHERE id=?1",
                    [fid_a],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .unwrap();
            let (c_fi, c_fo): (i64, i64) = conn
                .query_row(
                    "SELECT fan_in, fan_out FROM files WHERE id=?1",
                    [fid_c],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .unwrap();
            assert_eq!((a_fi, a_fo), (1, 2));
            assert_eq!((c_fi, c_fo), (0, 4));
        }
    }

    mod clone_bands_membership {
        use super::*;
        use crate::resolve::CloneBand;

        fn output_with_entities() -> Vec<ExtractOutput> {
            // a.rs entity (idx 0) and b.rs entity (idx 1), distinct spans.
            let mut e0 = entity(0, "dup_a");
            e0.span = Span {
                start_byte: 0,
                end_byte: 8,
                start_line: 1,
                start_col: 0,
                end_line: 2,
                end_col: 4,
            };
            let mut e1 = entity(1, "dup_b");
            e1.span = Span {
                start_byte: 20,
                end_byte: 30,
                start_line: 4,
                start_col: 0,
                end_line: 5,
                end_col: 6,
            };
            vec![ExtractOutput {
                entities: vec![e0, e1],
                symbols: vec![],
                diagnostics: vec![],
                files: vec!["a.rs".to_string(), "b.rs".to_string()],
                file_meta: vec![dummy_meta(), dummy_meta()],
            }]
        }

        #[test]
        fn bands_and_membership_with_correlation() {
            let db_path = temp_db("clone-bands");
            let output = output_with_entities();
            let graph = ResolvedGraph {
                nodes: vec![],
                edges: vec![],
                communities: vec![],
                clone_bands: vec![
                    CloneBand {
                        id: 0,
                        members: vec![0], // entity in a.rs
                    },
                    CloneBand {
                        id: 1,
                        members: vec![1], // entity in b.rs
                    },
                ],
            };

            persist(
                &db_path,
                &output,
                &graph,
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            assert_eq!(
                row_count(&conn, "clone_bands"),
                2,
                "exactly P rows for P bands"
            );
            assert_eq!(
                row_count(&conn, "clone_band_members"),
                2,
                "one row per (band, entity) pair"
            );

            // Each membership row references a valid entities.id, correlated
            // via (file_id, start_byte, end_byte).
            let rows: Vec<(i64, i64, String, String, i64, i64)> = {
                let mut stmt = conn
                    .prepare(
                        "SELECT cbm.band_id, cbm.entity_id, cb.label, f.path, e.start_byte, e.end_byte
                         FROM clone_band_members cbm
                         JOIN clone_bands cb ON cb.id = cbm.band_id
                         JOIN entities e ON e.id = cbm.entity_id
                         JOIN files f ON f.id = e.file_id
                         ORDER BY cbm.band_id",
                    )
                    .expect("query prepares");
                stmt.query_map([], |r| {
                    Ok((
                        r.get(0)?,
                        r.get(1)?,
                        r.get(2)?,
                        r.get(3)?,
                        r.get(4)?,
                        r.get(5)?,
                    ))
                })
                .expect("maps")
                .map(|r| r.expect("row ok"))
                .collect()
            };
            assert_eq!(rows.len(), 2);
            // Band 0 -> entity (a.rs, bytes 0..8).
            assert_eq!(rows[0].2, "clone-band-0");
            assert_eq!(rows[0].3, "a.rs");
            assert_eq!((rows[0].4, rows[0].5), (0, 8));
            // Band 1 -> entity (b.rs, bytes 20..30).
            assert_eq!(rows[1].2, "clone-band-1");
            assert_eq!(rows[1].3, "b.rs");
            assert_eq!((rows[1].4, rows[1].5), (20, 30));
            // Entity ids are valid: join above already proves existence; check > 0.
            assert!(rows[0].1 > 0 && rows[1].1 > 0);
        }
    }

    mod complexity_persisted {
        use super::*;

        #[test]
        fn complexity_written_to_matching_files_row() {
            let db_path = temp_db("complexity");
            let mut e0 = entity(0, "fn_a");
            e0.kind = EntityKind::ControlFlow;
            let mut e1 = entity(0, "fn_b");
            e1.kind = EntityKind::ControlFlow;
            let mut e2 = entity(1, "fn_c");
            e2.kind = EntityKind::Function;
            let output = vec![ExtractOutput {
                entities: vec![e0, e1, e2],
                symbols: vec![],
                diagnostics: vec![],
                files: vec!["a.rs".to_string(), "b.rs".to_string()],
                file_meta: vec![dummy_meta(), dummy_meta()],
            }];

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let a: i64 = conn
                .query_row("SELECT complexity FROM files WHERE path='a.rs'", [], |r| {
                    r.get(0)
                })
                .expect("a.rs row has complexity");
            let b: i64 = conn
                .query_row("SELECT complexity FROM files WHERE path='b.rs'", [], |r| {
                    r.get(0)
                })
                .expect("b.rs row has complexity");
            assert_eq!(
                a, 3,
                "base 1 + 2 ControlFlow entities, written to the a.rs row"
            );
            assert_eq!(b, 1, "no ControlFlow -> exactly 1");
        }
    }

    mod churn_persisted {
        use super::*;

        #[test]
        fn churn_written_to_matching_files_row() {
            // A real, long-lived, git-tracked file in this crate: it has a
            // known non-zero commit history and the value must land on ITS
            // files row. Deliberately NOT a resolve fixture — those get moved
            // around, and an uncommitted rename shows zero history at the new
            // path, which would flake this test.
            let db_path = temp_db("churn");
            let file = format!("{}/Cargo.toml", env!("CARGO_MANIFEST_DIR"));
            let mut e = entity(0, "fn_a");
            e.kind = EntityKind::Function;
            let output = vec![ExtractOutput {
                entities: vec![e],
                symbols: vec![],
                diagnostics: vec![],
                files: vec![file.clone()],
                file_meta: vec![dummy_meta()],
            }];

            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let churn: i64 = conn
                .query_row("SELECT churn FROM files WHERE path = ?1", [&file], |r| {
                    r.get(0)
                })
                .expect("files row has churn");
            let raw = crate::churn::commit_count(&file);
            assert!(raw > 0, "fixture file has git history");
            assert_eq!(
                churn,
                i64::from(raw),
                "persisted churn matches git log count"
            );
        }
    }

    mod full_rebuild_atomic_and_idempotent {
        use super::*;
        use crate::resolve::{CloneBand, Community, EdgeKind, EdgeTarget, FileNode, ResolvedEdge};

        fn realistic_input() -> (Vec<ExtractOutput>, ResolvedGraph) {
            let output = vec![ExtractOutput {
                entities: vec![entity(0, "fn_a"), entity(1, "fn_b"), entity(0, "flow")],
                symbols: vec![symbol(0, "fn_a")],
                diagnostics: vec![diagnostic(2, "skipped")],
                files: vec!["a.rs".to_string(), "b.rs".to_string(), "c.rs".to_string()],
                file_meta: vec![dummy_meta(), dummy_meta(), dummy_meta()],
            }];
            let graph = ResolvedGraph {
                nodes: vec![
                    FileNode {
                        path: "a.rs".to_string(),
                        community_id: Some(0),
                        fan_in: 1,
                        fan_out: 1,
                    },
                    FileNode {
                        path: "b.rs".to_string(),
                        community_id: Some(0),
                        fan_in: 0,
                        fan_out: 0,
                    },
                ],
                edges: vec![ResolvedEdge {
                    from: 0,
                    to: EdgeTarget::File(1),
                    kind: EdgeKind::Import,
                    resolved: true,
                    from_entity: None,
                }],
                communities: vec![Community {
                    id: 0,
                    members: vec!["a.rs".to_string(), "b.rs".to_string()],
                }],
                // Band 0 covers the fn_a entity (a.rs) and fn_b entity (b.rs),
                // so clone_bands/clone_band_members get rows too.
                clone_bands: vec![CloneBand {
                    id: 0,
                    members: vec![0, 1],
                }],
            };
            (output, graph)
        }

        fn all_table_counts(conn: &rusqlite::Connection) -> Vec<(String, i64)> {
            [
                "files",
                "entities",
                "symbols",
                "diagnostics",
                "resolved_edges",
                "communities",
                "community_members",
                "clone_bands",
                "clone_band_members",
            ]
            .iter()
            .map(|t| (t.to_string(), row_count(conn, t)))
            .collect()
        }

        #[test]
        fn all_tables_populated_in_one_commit() {
            let db_path = temp_db("tx-all");
            let (output, graph) = realistic_input();

            persist(
                &db_path,
                &output,
                &graph,
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let counts = all_table_counts(&conn);
            for (table, count) in counts {
                assert!(count > 0, "table {table} must be populated (got {count})");
            }
        }

        #[test]
        fn interrupted_write_rolls_back_to_prior_state() {
            let db_path = temp_db("tx-rollback");
            let (output_a, graph_a) = realistic_input();
            persist(
                &db_path,
                &output_a,
                &graph_a,
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("first persist commits");
            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let before = all_table_counts(&conn);
            drop(conn);

            // Simulate a second run interrupted mid-write: begin a
            // transaction, rebuild the schema, write files + entities, then
            // drop the transaction without committing (rollback).
            let mut conn = crate::db::open(&db_path).expect("db opens");
            {
                let tx = conn.transaction().expect("tx begins");
                crate::db::rebuild_schema(&tx).expect("schema rebuilds");
                let file_ids = write_files(&tx, &output_a).expect("files write");
                let _ = write_entities(&tx, &output_a, &file_ids).expect("entities write");
                // Interruption: tx dropped without commit.
            }

            let after = all_table_counts(&conn);
            assert_eq!(
                before, after,
                "rolled-back transaction must leave the prior committed state intact"
            );
            let files: Vec<String> = {
                let mut stmt = conn
                    .prepare("SELECT path FROM files ORDER BY path")
                    .expect("query prepares");
                stmt.query_map([], |r| r.get(0))
                    .expect("maps")
                    .map(|r| r.expect("row ok"))
                    .collect()
            };
            assert_eq!(files, vec!["a.rs", "b.rs", "c.rs"], "prior files intact");
        }

        #[test]
        fn second_run_leaves_only_second_runs_data() {
            let db_path = temp_db("tx-replace");
            let (output_a, graph_a) = realistic_input();
            persist(
                &db_path,
                &output_a,
                &graph_a,
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("first run commits");

            let output_b = vec![ExtractOutput {
                entities: vec![entity(0, "fn_z")],
                symbols: vec![],
                diagnostics: vec![],
                files: vec!["z.rs".to_string()],
                file_meta: vec![dummy_meta()],
            }];
            let graph_b = ResolvedGraph {
                nodes: vec![],
                edges: vec![],
                communities: vec![],
                clone_bands: vec![],
            };
            persist(
                &db_path,
                &output_b,
                &graph_b,
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("second run commits");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let files: Vec<String> = {
                let mut stmt = conn
                    .prepare("SELECT path FROM files ORDER BY path")
                    .expect("query prepares");
                stmt.query_map([], |r| r.get(0))
                    .expect("maps")
                    .map(|r| r.expect("row ok"))
                    .collect()
            };
            assert_eq!(files, vec!["z.rs"], "exactly the second run's file");
            assert_eq!(row_count(&conn, "entities"), 1);
            assert_eq!(row_count(&conn, "resolved_edges"), 0);
        }

        #[test]
        fn delta_replaces_changed_rows_and_preserves_unchanged_rows() {
            let db_path = temp_db("delta-replace");
            let initial_output = output(&["changed.rs", "unchanged.rs"]);
            let initial_graph = ResolvedGraph {
                nodes: vec![
                    FileNode {
                        path: "changed.rs".to_string(),
                        community_id: Some(1),
                        fan_in: 0,
                        fan_out: 1,
                    },
                    FileNode {
                        path: "unchanged.rs".to_string(),
                        community_id: Some(2),
                        fan_in: 1,
                        fan_out: 0,
                    },
                ],
                edges: vec![ResolvedEdge {
                    from: 0,
                    to: EdgeTarget::File(1),
                    kind: EdgeKind::Import,
                    resolved: true,
                    from_entity: None,
                }],
                communities: vec![
                    Community {
                        id: 1,
                        members: vec!["changed.rs".to_string()],
                    },
                    Community {
                        id: 2,
                        members: vec!["unchanged.rs".to_string()],
                    },
                ],
                clone_bands: vec![
                    CloneBand {
                        id: 1,
                        members: vec![0],
                    },
                    CloneBand {
                        id: 2,
                        members: vec![1],
                    },
                ],
            };
            persist(
                &db_path,
                &initial_output,
                &initial_graph,
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("initial persist succeeds");

            let conn = crate::db::open(&db_path).expect("db opens");
            let changed_file_id: i64 = conn
                .query_row(
                    "SELECT id FROM files WHERE path = 'changed.rs'",
                    [],
                    |row| row.get(0),
                )
                .expect("changed file exists");
            let unchanged_entity_id: i64 = conn
                .query_row(
                    "SELECT id FROM entities WHERE file_id = (SELECT id FROM files WHERE path = 'unchanged.rs')",
                    [],
                    |row| row.get(0),
                )
                .expect("unchanged entity exists");
            let unchanged_symbol_id: i64 = conn
                .query_row(
                    "SELECT id FROM symbols WHERE file_id = (SELECT id FROM files WHERE path = 'unchanged.rs')",
                    [],
                    |row| row.get(0),
                )
                .expect("unchanged symbol exists");
            let unchanged_community_id: i64 = conn
                .query_row(
                    "SELECT id FROM communities WHERE label = 'community-2'",
                    [],
                    |row| row.get(0),
                )
                .expect("unchanged community exists");
            let unchanged_band_id: i64 = conn
                .query_row(
                    "SELECT id FROM clone_bands WHERE label = 'clone-band-2'",
                    [],
                    |row| row.get(0),
                )
                .expect("unchanged clone band exists");

            let changed_output = vec![ExtractOutput {
                entities: vec![entity(0, "fresh_fn")],
                symbols: vec![symbol(0, "fresh_symbol")],
                diagnostics: vec![diagnostic(0, "fresh diagnostic")],
                files: vec!["changed.rs".to_string()],
                file_meta: vec![dummy_meta()],
            }];
            let changed_graph = ResolvedGraph {
                nodes: vec![FileNode {
                    path: "changed.rs".to_string(),
                    community_id: Some(10),
                    fan_in: 0,
                    fan_out: 0,
                }],
                edges: vec![],
                communities: vec![Community {
                    id: 10,
                    members: vec!["changed.rs".to_string()],
                }],
                clone_bands: vec![CloneBand {
                    id: 10,
                    members: vec![0],
                }],
            };

            persist_delta(
                &conn,
                &[changed_file_id],
                &changed_output,
                &changed_graph,
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("delta persist succeeds");

            let fresh_name: String = conn
                .query_row(
                    "SELECT name FROM entities WHERE file_id = ?1",
                    [changed_file_id],
                    |row| row.get(0),
                )
                .expect("fresh entity exists");
            assert_eq!(fresh_name, "fresh_fn");
            assert_eq!(
                row_count(&conn, "entities"),
                2,
                "changed entity replaced, unchanged entity preserved"
            );
            assert_eq!(
                row_count(&conn, "symbols"),
                2,
                "changed symbol replaced, unchanged symbol preserved"
            );
            assert_eq!(row_count(&conn, "diagnostics"), 1);
            assert_eq!(row_count(&conn, "resolved_edges"), 0);
            assert_eq!(row_count(&conn, "communities"), 2);
            assert_eq!(row_count(&conn, "community_members"), 2);
            assert_eq!(row_count(&conn, "clone_bands"), 2);
            assert_eq!(row_count(&conn, "clone_band_members"), 2);

            let retained_ids: (i64, i64) = conn
                .query_row(
                    "SELECT entities.id, symbols.id
                     FROM entities
                     JOIN symbols ON symbols.file_id = entities.file_id
                     WHERE entities.file_id = (SELECT id FROM files WHERE path = 'unchanged.rs')",
                    [],
                    |row| Ok((row.get(0)?, row.get(1)?)),
                )
                .expect("unchanged rows remain");
            assert_eq!(retained_ids, (unchanged_entity_id, unchanged_symbol_id));
            let retained_community_id: i64 = conn
                .query_row(
                    "SELECT id FROM communities WHERE label = 'community-2'",
                    [],
                    |row| row.get(0),
                )
                .expect("unchanged community remains");
            assert_eq!(retained_community_id, unchanged_community_id);
            let retained_band_id: i64 = conn
                .query_row(
                    "SELECT id FROM clone_bands WHERE label = 'clone-band-2'",
                    [],
                    |row| row.get(0),
                )
                .expect("unchanged clone band remains");
            assert_eq!(retained_band_id, unchanged_band_id);
        }
    }
    mod entities_is_async {
        use super::*;
        use crate::extract;
        use crate::model::EntityKind;
        use crate::parse::parse_source;

        fn function_entities(lang: ast_grep_language::SupportLang, source: &str) -> Vec<Entity> {
            let parsed = parse_source(&lang, source);
            assert!(!parsed.has_error(), "fixture must parse cleanly: {source}");
            extract::extract(&parsed, 0)
                .entities
                .into_iter()
                // type-hierarchy: unchanged (test helper isolates Function entities for async-flag assertions)
                .filter(|e| e.kind == EntityKind::Function)
                .collect()
        }

        #[test]
        fn extract_marks_async_and_sync_functions_per_language() {
            // TypeScript: async function vs sync function vs arrow.
            let ts = function_entities(
                ast_grep_language::SupportLang::TypeScript,
                r#"
async function fetchData(): Promise<void> {}
function render(): void {}
"#,
            );
            let ts_async: Vec<&Entity> = ts.iter().filter(|e| e.is_async == Some(true)).collect();
            let ts_sync: Vec<&Entity> = ts.iter().filter(|e| e.is_async == Some(false)).collect();
            assert_eq!(ts_async.len(), 1, "async fn flagged: {ts:?}");
            assert_eq!(ts_async[0].name, "fetchData");
            assert_eq!(ts_sync.len(), 1, "sync fn flagged false: {ts:?}");
            assert_eq!(ts_sync[0].name, "render");

            // Rust: async fn vs plain fn.
            let rust = function_entities(
                ast_grep_language::SupportLang::Rust,
                r#"
async fn fetch_data() {}
fn render() {}
"#,
            );
            assert_eq!(
                rust.iter().filter(|e| e.is_async == Some(true)).count(),
                1,
                "rust async fn flagged: {rust:?}"
            );
            assert_eq!(
                rust.iter().filter(|e| e.is_async == Some(false)).count(),
                1,
                "rust sync fn flagged false: {rust:?}"
            );

            // Python: async def vs def.
            let python = function_entities(
                ast_grep_language::SupportLang::Python,
                "async def fetch_data():
    pass

def render():
    pass
",
            );
            assert_eq!(
                python.iter().filter(|e| e.is_async == Some(true)).count(),
                1,
                "python async def flagged: {python:?}"
            );
            assert_eq!(
                python.iter().filter(|e| e.is_async == Some(false)).count(),
                1,
                "python sync def flagged false: {python:?}"
            );
        }

        #[test]
        fn extract_leaves_non_function_entities_async_none() {
            let parsed = parse_source(
                &ast_grep_language::SupportLang::TypeScript,
                "import * as fs from 'fs';
",
            );
            assert!(!parsed.has_error());
            let entities = extract::extract(&parsed, 0).entities;
            let import = entities
                .iter()
                // type-hierarchy: unchanged (test asserts Import entities have no async flag; unrelated to Extends/Implements)
                .find(|e| e.kind == EntityKind::Import)
                .expect("import entity present");
            assert_eq!(
                import.is_async, None,
                "imports have no async flag: {import:?}"
            );
        }

        #[test]
        fn persist_round_trips_is_async_column() {
            let db_path = temp_db("is-async");
            let mut async_fn = entity(0, "fetch_data");
            async_fn.is_async = Some(true);
            let mut sync_fn = entity(0, "render");
            sync_fn.is_async = Some(false);
            let mut import = entity(1, "fs");
            import.kind = EntityKind::Import;

            let output = vec![ExtractOutput {
                entities: vec![async_fn, sync_fn, import],
                symbols: vec![],
                diagnostics: vec![],
                files: vec!["a.rs".to_string(), "b.rs".to_string()],
                file_meta: vec![dummy_meta(), dummy_meta()],
            }];
            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            // Raw column values: async → 1, sync → 0, non-function → NULL.
            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let rows: Vec<(String, Option<bool>)> = conn
                .prepare(
                    "SELECT e.name, e.is_async FROM entities e JOIN files f ON f.id = e.file_id ORDER BY e.name",
                )
                .expect("prepare")
                .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
                .expect("maps")
                .map(|r| r.expect("row"))
                .collect();
            assert_eq!(
                rows,
                vec![
                    ("fetch_data".to_string(), Some(true)),
                    ("fs".to_string(), None),
                    ("render".to_string(), Some(false)),
                ]
            );

            // Read path: query_persisted_state maps the column back onto Entity.
            let state = query_persisted_state(&conn, true).expect("state loads");
            let fetch_data = state
                .entities
                .iter()
                .find(|e| e.name == "fetch_data")
                .expect("fetch_data entity");
            assert_eq!(fetch_data.is_async, Some(true));
            let fs_entity = state
                .entities
                .iter()
                .find(|e| e.name == "fs")
                .expect("fs entity");
            assert_eq!(fs_entity.is_async, None);
        }

        #[test]
        fn variables_and_parameters_are_persisted_but_literals_are_dropped() {
            // Audit S3 root cause: `declaration_kinds()` (behind symbols_in_file
            // / get_symbol / filter_symbols) lists Variable and Parameter, so
            // they must survive persistence — dropping them made every field /
            // property / constant / parameter invisible. Literal stays dropped.
            let db_path = temp_db("keep-var-param");
            let mut field = entity(0, "address");
            field.kind = EntityKind::Variable;
            let mut param = entity(0, "owner");
            param.kind = EntityKind::Parameter;
            let mut lit = entity(0, "42");
            lit.kind = EntityKind::Literal;

            let output = vec![ExtractOutput {
                entities: vec![entity(0, "helper"), field, param, lit],
                symbols: vec![],
                diagnostics: vec![],
                files: vec!["a.rs".to_string()],
                file_meta: vec![dummy_meta()],
            }];
            persist(
                &db_path,
                &output,
                &empty_graph(),
                Path::new(env!("CARGO_MANIFEST_DIR")),
            )
            .expect("persist succeeds");

            let conn = rusqlite::Connection::open(&db_path).expect("db opens");
            let names: Vec<String> = conn
                .prepare("SELECT name FROM entities ORDER BY name")
                .expect("prepare")
                .query_map([], |r| r.get(0))
                .expect("maps")
                .map(|r| r.expect("row"))
                .collect();
            assert!(
                names.contains(&"address".to_string()),
                "Variable persisted: {names:?}"
            );
            assert!(
                names.contains(&"owner".to_string()),
                "Parameter persisted: {names:?}"
            );
            assert!(
                !names.contains(&"42".to_string()),
                "Literal still dropped: {names:?}"
            );
        }
    }

    #[test]
    fn function_metrics_persist_evidence_and_replace_changed_files() {
        let db_path = temp_db("function-metrics");
        let mut function = entity(0, "read");
        function.owner_type = Some("Reader".to_string());
        function.span = Span {
            start_byte: 0,
            end_byte: 100,
            start_line: 1,
            start_col: 0,
            end_line: 10,
            end_col: 1,
        };
        let mut outer = entity(0, "if_statement");
        outer.kind = EntityKind::ControlFlow;
        outer.span = Span {
            start_byte: 20,
            end_byte: 80,
            start_line: 3,
            start_col: 0,
            end_line: 8,
            end_col: 1,
        };
        let mut inner = entity(0, "while_expression");
        inner.kind = EntityKind::ControlFlow;
        inner.span = Span {
            start_byte: 30,
            end_byte: 50,
            start_line: 4,
            start_col: 0,
            end_line: 5,
            end_col: 1,
        };
        let initial = vec![
            ExtractOutput {
                entities: vec![function, outer, inner],
                symbols: vec![],
                diagnostics: vec![],
                files: vec!["src/read.rs".to_string()],
                file_meta: vec![dummy_meta()],
            },
            ExtractOutput {
                entities: vec![entity(0, "render")],
                symbols: vec![],
                diagnostics: vec![],
                files: vec!["src/render.py".to_string()],
                file_meta: vec![dummy_meta()],
            },
        ];
        persist(
            &db_path,
            &initial,
            &empty_graph(),
            Path::new(env!("CARGO_MANIFEST_DIR")),
        )
        .expect("initial metrics persist");

        let conn = crate::db::open_incremental(&db_path).expect("db opens");
        let rust_metric: (String, i64, i64, i64, i64, i64, String, String, i64) = conn
            .query_row(
                "SELECT identity, start_byte, end_byte, cyclomatic, cognitive,
                        max_nesting, confidence, confidence_reasons, metric_version
                 FROM function_metrics
                 WHERE file_id = (SELECT id FROM files WHERE path = 'src/read.rs')",
                [],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                        row.get(6)?,
                        row.get(7)?,
                        row.get(8)?,
                    ))
                },
            )
            .expect("Rust metric exists");
        assert_eq!(
            rust_metric,
            (
                "Reader::read".to_string(),
                0,
                100,
                3,
                3,
                1,
                "high".to_string(),
                "[]".to_string(),
                FUNCTION_METRIC_VERSION,
            )
        );
        let python_confidence: (String, String) = conn
            .query_row(
                "SELECT confidence, confidence_reasons FROM function_metrics
                 WHERE file_id = (SELECT id FROM files WHERE path = 'src/render.py')",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .expect("Python metric exists");
        assert_eq!(python_confidence.0, "high");
        assert_eq!(python_confidence.1, "[]");

        let changed_file_id: i64 = conn
            .query_row(
                "SELECT id FROM files WHERE path = 'src/read.rs'",
                [],
                |row| row.get(0),
            )
            .expect("changed file exists");
        let changed = vec![ExtractOutput {
            entities: vec![entity(0, "replacement")],
            symbols: vec![],
            diagnostics: vec![Diagnostic {
                file_id: Some(0),
                path: "src/read.rs".to_string(),
                message: "syntax error — partial extract kept".to_string(),
                severity: "warning".to_string(),
            }],
            files: vec!["src/read.rs".to_string()],
            file_meta: vec![dummy_meta()],
        }];
        let changed_graph = ResolvedGraph {
            nodes: vec![FileNode {
                path: "src/read.rs".to_string(),
                community_id: None,
                fan_in: 0,
                fan_out: 0,
            }],
            edges: vec![],
            communities: vec![],
            clone_bands: vec![],
        };
        persist_delta(
            &conn,
            &[changed_file_id],
            &changed,
            &changed_graph,
            Path::new(env!("CARGO_MANIFEST_DIR")),
        )
        .expect("changed metrics replace");

        assert_eq!(row_count(&conn, "function_metrics"), 2);
        let replaced: (String, String, String) = conn
            .query_row(
                "SELECT identity, confidence, confidence_reasons
                 FROM function_metrics WHERE file_id = ?1",
                [changed_file_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .expect("replacement metric exists");
        assert_eq!(replaced.0, "replacement");
        assert_eq!(replaced.1, "low");
        assert!(replaced.2.contains("syntax_diagnostic"));
    }

    #[test]
    fn every_supported_language_has_a_complexity_profile() {
        for extension in [
            "sh", "c", "cpp", "cs", "dart", "ex", "go", "hs", "java", "js", "kt", "lua", "php",
            "py", "rb", "rs", "scala", "sol", "swift", "tsx", "ts",
        ] {
            let path = std::path::PathBuf::from(format!("src/sample.{extension}"));
            assert!(
                has_certified_complexity_profile(&path),
                "missing profile for {extension}"
            );
        }
        assert!(!has_certified_complexity_profile(Path::new(
            "src/sample.unknown"
        )));
    }
}
