//! Query surface: varde-code's read-side access to the persisted SQLite
//! store (`sqlite-persistence`'s schema).
//!
//! 20 query modes, one function per mode, all sharing one JSON envelope
//! contract:
//!
//! - success: `{"schema_version": 1, "ok": true, "outcome": "success",
//!   "data": <mode payload>, "meta": <output policy>}`
//! - failure: `{"schema_version": 1, "ok": false, "outcome": "tool-error",
//!   "data": {"error": {"code": "<stable code>", "message": "<human-readable
//!   message>"}}, "meta": <output policy>}`
//!
//! Every mode except `find_pattern` reads directly from the persisted schema;
//! nothing re-derives in-memory structures. This module owns the envelope and
//! the mode dispatcher; the mode implementations live in the submodules.

use anyhow::Result;
use rusqlite::Connection;
use serde_json::Value;

/// Version of the machine-readable envelope contract.
pub const ENVELOPE_SCHEMA_VERSION: u64 = 1;

/// A stable machine-readable error code paired with a human message.
#[derive(Debug, Clone)]
pub struct ApiError {
    pub code: &'static str,
    pub message: String,
}

impl ApiError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    /// NotFound error for a missing/unknown symbol or file.
    pub fn not_found(what: impl std::fmt::Display) -> Self {
        Self::new("not_found", format!("not found: {what}"))
    }
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for ApiError {}

/// Render a mode result as the JSON envelope string.
///
/// Render a result with default, un-compacted output metadata.
pub fn render(result: Result<serde_json::Value, ApiError>) -> String {
    render_with_meta(result, crate::query::output::OutputMeta::default())
}

/// Render one machine-readable result as the shared versioned envelope.
pub fn render_with_meta(
    result: Result<Value, ApiError>,
    meta: crate::query::output::OutputMeta,
) -> String {
    render_value_with_meta(result, meta).to_string()
}

/// Build one machine-readable result envelope as a typed JSON value.
///
/// Keeping construction typed lets callers add envelope metadata without
/// serializing and parsing the payload again.
pub fn render_value_with_meta(
    result: Result<Value, ApiError>,
    meta: crate::query::output::OutputMeta,
) -> Value {
    match result {
        Ok(data) => {
            let outcome = data
                .get("outcome")
                .and_then(Value::as_str)
                .unwrap_or("success");
            serde_json::json!({
                "schema_version": ENVELOPE_SCHEMA_VERSION,
                "ok": true,
                "outcome": outcome,
                "data": data,
                "meta": meta,
            })
        }
        Err(err) => serde_json::json!({
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "ok": false,
            "outcome": "tool-error",
            "data": { "error": { "code": err.code, "message": err.message } },
            "meta": meta,
        }),
    }
}

/// Render a batch child envelope, including the mode tag added to each call.
pub(crate) fn render_batch_value(
    result: Result<Value, ApiError>,
    meta: crate::query::output::OutputMeta,
    mode: Option<&str>,
) -> Value {
    let mut envelope = render_value_with_meta(result, meta);
    envelope["mode"] = mode.map_or(Value::Null, Value::from);
    envelope
}

/// Process-wide SQL statement trace hook, applied to every connection
/// `open_db` creates. Diagnostics/test support (e.g. verifying that graph
/// traversals issue a constant number of statements).
static TRACE_HOOK: std::sync::Mutex<Option<fn(&str)>> = std::sync::Mutex::new(None);

/// Install (or clear) the SQL statement trace hook applied by [`open_db`].
pub fn set_trace_hook(hook: Option<fn(&str)>) {
    *TRACE_HOOK.lock().expect("trace hook lock") = hook;
}

thread_local! {
    /// The base index a query read, when its repo root is a linked worktree
    /// with no index of its own (see [`crate::db::path::base_index_for`]).
    ///
    /// [`open_db_impl`] records it; [`dispatch_mode_with_meta`] consumes it
    /// into the envelope's `base_index` note. Every dispatch and every
    /// freshness check clears it first, so a note always describes the call
    /// that just ran rather than a previous one (notably a batch sibling).
    static BASE_INDEX: std::cell::RefCell<Option<crate::db::path::BaseIndex>> =
        const { std::cell::RefCell::new(None) };
}

/// Consume the recorded base index, if any.
fn take_base_index() -> Option<crate::db::path::BaseIndex> {
    BASE_INDEX.with(|slot| slot.borrow_mut().take())
}

/// The base index a query may read: `Some` only when the query names a
/// `repoRoot` with no index of its own (and no explicit `dbPath`) and the
/// main checkout that root belongs to has an index. Read-only; nothing is
/// built or written.
fn base_index_for_input(input: &serde_json::Value) -> Option<crate::db::path::BaseIndex> {
    if input.get("dbPath").is_some() {
        return None;
    }
    let root = std::path::Path::new(opt_str(input, "repoRoot")?);
    if crate::db::path::repo_db_path(root).is_file() {
        return None;
    }
    crate::db::path::base_index_for(root)
}

/// The envelope note for a query answered by the main checkout's index.
fn base_index_note(base: crate::db::path::BaseIndex) -> Value {
    serde_json::json!({
        "main_checkout_hash": base.main_checkout_hash,
        "note": "answers come from the main checkout's index and may not reflect files this worktree changed",
    })
}

/// Rewrite base-index answer paths from the main checkout root onto the
/// querying worktree's root, so a worker in a task worktree never reads or
/// edits main-checkout files. Every string under the main root is rewritten;
/// see `output::rewrite_repo_paths`.
fn rewrite_base_paths(data: &mut Value, base: &crate::db::path::BaseIndex, input: &Value) {
    let Some(worktree) = opt_str(input, "repoRoot") else {
        return;
    };
    crate::query::output::rewrite_repo_paths(
        data,
        &base.main_checkout_root,
        std::path::Path::new(worktree.trim_end_matches(std::path::MAIN_SEPARATOR)),
    );
}

/// Map a query's absolute paths under the querying worktree onto the main
/// checkout's rows before lookup, mirroring [`rewrite_base_paths`]. A linked
/// worktree with no index of its own is answered from the main checkout's
/// index, whose rows name main-checkout paths; an absolute `<worktree>/...`
/// input would otherwise fail every lookup. `None` when the mode never reads
/// that index or no base index applies.
fn map_base_input(mode: &str, input: &Value) -> Option<Value> {
    if !mode_reads_base_index(mode) {
        return None;
    }
    // Only when the main checkout's base index would answer this query.
    let base = base_index_for_input(input)?;
    let worktree = opt_str(input, "repoRoot")?;
    let worktree_given = std::path::Path::new(worktree.trim_end_matches(std::path::MAIN_SEPARATOR));
    let worktree_canonical =
        std::fs::canonicalize(worktree_given).unwrap_or_else(|_| worktree_given.to_path_buf());
    // Rows keep the spelling the build used, which can differ from the
    // canonical main root (macOS `/var` vs `/private/var`), so an exact-row
    // lookup must try the caller's spelling beside the canonical one, plus
    // the build-time spelling recovered from an indexed row.
    let mut main_roots = vec![
        base.main_checkout_root.clone(),
        given_main_root(
            worktree_given,
            &worktree_canonical,
            &base.main_checkout_root,
        ),
    ];
    // A read-only connection resolves each mapped path against an indexed row
    // exactly. If it cannot be opened, paths stay unmapped, which is the
    // pre-existing behaviour.
    let conn = crate::db::open_read_only(&base.db_path).ok()?;
    if let Some(root) = build_time_main_root(&conn, &base.main_checkout_root) {
        main_roots.push(root);
    }
    let mut mapped = input.clone();
    rewrite_input_paths(
        &mut mapped,
        worktree_given,
        &worktree_canonical,
        &main_roots,
        &conn,
    );
    Some(mapped)
}

/// The main checkout root in the same spelling the caller gave for the
/// worktree, for indexes whose rows kept the build-time spelling.
///
/// The given worktree path carries the caller's spelling, so the canonical
/// worktree-to-main relationship is re-spelled onto it: a sibling
/// (`<parent>/main` beside `<parent>/worktree`) keeps the given parent, and a
/// worktree nested under the main root keeps the given prefix. Any other
/// layout falls back to the canonical root.
fn given_main_root(
    worktree_given: &std::path::Path,
    worktree_canonical: &std::path::Path,
    main_canonical: &std::path::Path,
) -> std::path::PathBuf {
    if let Ok(rel) = worktree_canonical.strip_prefix(main_canonical) {
        let given = worktree_given.to_string_lossy();
        let rel = rel.to_string_lossy();
        if let Some(root) = given.strip_suffix(rel.as_ref())
            && (root.is_empty() || root.ends_with(std::path::MAIN_SEPARATOR))
        {
            return std::path::PathBuf::from(root);
        }
    }
    if worktree_canonical.parent() == main_canonical.parent()
        && let (Some(parent), Some(name)) = (worktree_given.parent(), main_canonical.file_name())
    {
        return parent.join(name);
    }
    main_canonical.to_path_buf()
}

/// Whether `mode` reads the persisted index and so can be answered from the
/// main checkout's base index. `find_pattern` parses live and never is.
fn mode_reads_base_index(mode: &str) -> bool {
    FRESHNESS
        .iter()
        .any(|(name, slices, _)| *name == mode && !slices.is_empty())
}

/// Replace every string that names a path under `worktree_root` with the
/// main-checkout row path it denotes, in place. The base index stores each
/// file as `<main root>{sep}{relative}`, so an absolute form that matches a
/// row exactly resolves the file even when a nested file shares its basename
/// (`main.py` vs `a/main.py`); the bare relative form is kept only when
/// neither main-root spelling has the row. `repoRoot` and `dbPath` are left
/// alone: they must keep naming the querying worktree.
fn rewrite_input_paths(
    input: &mut Value,
    worktree_root: &std::path::Path,
    worktree_canonical: &std::path::Path,
    main_roots: &[std::path::PathBuf],
    conn: &Connection,
) {
    let prefix = format!("{}{}", worktree_root.display(), std::path::MAIN_SEPARATOR);
    rewrite_input_value(input, &prefix, worktree_canonical, main_roots, conn);
}

fn rewrite_input_value(
    v: &mut Value,
    worktree_prefix: &str,
    worktree_root: &std::path::Path,
    main_roots: &[std::path::PathBuf],
    conn: &Connection,
) {
    match v {
        Value::Array(items) => items.iter_mut().for_each(|item| {
            rewrite_input_value(item, worktree_prefix, worktree_root, main_roots, conn)
        }),
        Value::Object(map) => {
            for (key, value) in map.iter_mut() {
                if key == "repoRoot" || key == "dbPath" {
                    continue;
                }
                rewrite_input_value(value, worktree_prefix, worktree_root, main_roots, conn);
            }
        }
        Value::String(path) => {
            if let Some(rest) = worktree_relative(path, worktree_prefix, worktree_root) {
                *path = main_row_path(conn, &rest, main_roots).unwrap_or(rest);
            }
        }
        _ => {}
    }
}

/// The part of a path under the worktree, or `None` when it names no path
/// there. The given prefix is tried first; as in `output::rewrite_value`, the
/// worktree may be spelled differently from the caller's `repoRoot` (`/var`
/// vs `/private/var`), so a canonicalization-based match is the fallback for
/// absolute strings.
fn worktree_relative(
    path: &str,
    worktree_prefix: &str,
    worktree_root: &std::path::Path,
) -> Option<String> {
    if let Some(rest) = path.strip_prefix(worktree_prefix) {
        return Some(rest.to_string());
    }
    if std::path::Path::new(path).is_absolute()
        && let Ok(canonical) = std::fs::canonicalize(path)
        && let Ok(rest) = canonical.strip_prefix(worktree_root)
    {
        return Some(rest.display().to_string());
    }
    None
}

/// The indexed row path for `rest`, under whichever main-root spelling the
/// base index stored. `None` keeps `rest` itself, preserving the suffix match
/// a relative `filePath` already used.
fn main_row_path(
    conn: &Connection,
    rest: &str,
    main_roots: &[std::path::PathBuf],
) -> Option<String> {
    main_roots.iter().find_map(|main_root| {
        let candidate = main_root.join(rest);
        let candidate = candidate.to_str()?;
        indexed_path_exists(conn, candidate).then(|| candidate.to_string())
    })
}

/// The main-root spelling the index's rows were built with, recovered from one
/// indexed row.
///
/// Rows store `<build-time main root>{sep}<relative>`, and neither the
/// canonical root nor the caller's spelling always matches it (an index built
/// through `/tmp` beside a canonical `/private/tmp` root). Canonicalizing a
/// row resolves the real path, whose part relative to the canonical root is
/// the row's suffix; stripping that suffix from the raw row path leaves the
/// build-time root. Rows whose own path traverses a symlink inside the repo
/// yield no such root, so a later row is tried.
fn build_time_main_root(
    conn: &Connection,
    main_canonical: &std::path::Path,
) -> Option<std::path::PathBuf> {
    let mut stmt = conn
        .prepare("SELECT path FROM files ORDER BY path LIMIT 16")
        .ok()?;
    let rows = stmt.query_map([], |row| row.get::<_, String>(0)).ok()?;
    for row in rows.flatten() {
        let Ok(canonical) = std::fs::canonicalize(&row) else {
            continue;
        };
        let Ok(rel) = canonical.strip_prefix(main_canonical) else {
            continue;
        };
        let suffix = format!("{}{}", std::path::MAIN_SEPARATOR, rel.display());
        if let Some(root) = row.strip_suffix(&suffix) {
            return Some(std::path::PathBuf::from(root));
        }
    }
    None
}

/// Whether the base index has a file row whose path is exactly `path`.
fn indexed_path_exists(conn: &Connection, path: &str) -> bool {
    conn.query_row("SELECT 1 FROM files WHERE path = ?1", [path], |_| Ok(()))
        .is_ok()
}

/// Open an existing index read-only. Indexed modes require a source root even
/// when the caller overrides the database location.
pub fn open_db(input: &serde_json::Value) -> std::result::Result<Connection, ApiError> {
    open_db_impl(input, true)
}

pub fn open_db_diagnostic(input: &serde_json::Value) -> std::result::Result<Connection, ApiError> {
    open_db_impl(input, false)
}

fn open_db_impl(
    input: &serde_json::Value,
    require_root: bool,
) -> std::result::Result<Connection, ApiError> {
    let root = opt_str(input, "repoRoot");
    if require_root && root.is_none() {
        return Err(ApiError::new(
            "invalid_input",
            "missing string field \"repoRoot\"",
        ));
    }
    let path = match input.get("dbPath").and_then(|v| v.as_str()) {
        Some(p) => std::path::PathBuf::from(p),
        None => {
            let root = std::path::Path::new(
                root.ok_or_else(|| ApiError::new("invalid_input", "missing repoRoot or dbPath"))?,
            );
            let own = crate::db::path::repo_db_path(root);
            match base_index_for_input(input) {
                Some(base) => {
                    // A linked worktree with no index of its own reads the
                    // main checkout's index read-only; nothing is built or
                    // written for the worktree.
                    BASE_INDEX.with(|slot| *slot.borrow_mut() = Some(base.clone()));
                    base.db_path
                }
                None => own,
            }
        }
    };
    if !path.is_file() {
        return Err(ApiError::new(
            "index_missing",
            format!(
                "index missing at {}; the coordinator can build it with `varde setup watch --ensure --repo <repo-root>`; find_pattern needs no index",
                path.display()
            ),
        ));
    }
    let mut conn =
        crate::db::open_read_only(&path).map_err(|e| ApiError::new("db_error", format!("{e}")))?;
    if let Some(hook) = *TRACE_HOOK.lock().expect("trace hook lock") {
        #[allow(deprecated)] // rusqlite 0.40: trace_v2 changes the hook signature
        conn.trace(Some(hook));
    }
    Ok(conn)
}

/// Map a `rusqlite::Error` to the standard `db_error` [`ApiError`]. Shared by
/// every query submodule that talks to SQLite directly.
pub(crate) fn db_err(e: rusqlite::Error) -> ApiError {
    ApiError::new("db_error", e.to_string())
}

/// Required string field from a mode input object.
pub fn req_str<'a>(
    input: &'a serde_json::Value,
    field: &str,
) -> std::result::Result<&'a str, ApiError> {
    input
        .get(field)
        .and_then(|v| v.as_str())
        .ok_or_else(|| ApiError::new("invalid_input", format!("missing string field {field:?}")))
}

/// Optional string field from a mode input object.
pub fn opt_str<'a>(input: &'a serde_json::Value, field: &str) -> Option<&'a str> {
    input.get(field).and_then(|v| v.as_str())
}

/// Every implemented query mode, in the canonical order the CLI registers
/// them. The coverage-parity harness requires its checklist to cover exactly
/// this set — an unlisted mode fails loudly.
pub const QUERY_MODES: [&str; 23] = [
    "batch",
    "symbols_in_file",
    "symbols_in_files",
    "get_symbol",
    "tests_for_file",
    "find_imports",
    "filter_symbols",
    "dependencies",
    "dependents",
    "blast_radius",
    "symbol_blast_radius",
    "type_hierarchy",
    "explore",
    "map_file",
    "map_symbol",
    "map_path",
    "detect_changes",
    "hotspots",
    "clusters",
    "find_pattern",
    "slice_state",
    "context_pack",
    "nav_map",
];

/// A scope resolver for one query mode: given the mode input, return the
/// source scope whose persisted state must be checked.
type ScopeResolver = fn(&serde_json::Value) -> Option<crate::slice::Scope>;

/// One [`FRESHNESS`] row: mode name, the slices it reads, and how to resolve
/// the checked source scope from the mode input.
type FreshnessEntry = (&'static str, &'static [crate::slice::Slice], ScopeResolver);

/// Mode → slice freshness mapping, the single place a query mode's
/// read-only preflight contract lives. Each indexed mode checks its required
/// slices against source and the revision ledger before reading results.
///
/// `find_pattern` is deliberately absent — it is the "no slice, live parse"
/// mode and is explicitly exempted by the coverage-parity harness.
/// `detect_changes` and `slice_state` are present as no-op entries so a new
/// mode must consciously decide its freshness story (the harness requires a
/// table entry for every mode except `find_pattern`).
pub const FRESHNESS: &[FreshnessEntry] = &[
    // raw: per-file structural slice (symbols_in_file / get_symbol /
    // filter_symbols reparse only the requested file when a path is given).
    (
        "symbols_in_file",
        &[crate::slice::Slice::Raw],
        raw_file_scope,
    ),
    // symbols_in_files checks each requested file individually (looping
    // `freshen_for_mode("symbols_in_file", ...)` per path inside the mode
    // function itself, since one Scope can only name one file) rather than
    // through this table's resolver — never_scope here is a no-op placeholder
    // so the coverage-parity harness sees every mode consciously wired.
    ("symbols_in_files", &[crate::slice::Slice::Raw], never_scope),
    (
        "get_symbol",
        &[crate::slice::Slice::Raw],
        raw_file_or_repo_scope,
    ),
    (
        "filter_symbols",
        &[crate::slice::Slice::Raw],
        raw_file_or_repo_scope,
    ),
    // raw + churn: hotspots scores complexity + churn over the whole repo.
    (
        "hotspots",
        &[crate::slice::Slice::Raw, crate::slice::Slice::Churn],
        repo_scope,
    ),
    // imports: resolved import edges (tests_for_file / find_imports filter to
    // Import kind only; resolution needs the whole file set).
    (
        "tests_for_file",
        &[crate::slice::Slice::Imports],
        repo_scope,
    ),
    ("find_imports", &[crate::slice::Slice::Imports], repo_scope),
    // edges: graph traversals load all resolved edges with no kind filter.
    ("dependencies", &[crate::slice::Slice::Edges], repo_scope),
    ("dependents", &[crate::slice::Slice::Edges], repo_scope),
    ("blast_radius", &[crate::slice::Slice::Edges], repo_scope),
    (
        "symbol_blast_radius",
        &[crate::slice::Slice::Edges],
        repo_scope,
    ),
    ("type_hierarchy", &[crate::slice::Slice::Edges], repo_scope),
    ("explore", &[crate::slice::Slice::Edges], repo_scope),
    ("map_symbol", &[crate::slice::Slice::Edges], repo_scope),
    ("map_path", &[crate::slice::Slice::Edges], repo_scope),
    // global: map_file reads community_id + fan.
    ("map_file", &[crate::slice::Slice::Global], repo_scope),
    // global: clusters reads the persisted communities/community_members
    // partition (+ resolved edges for cohesion).
    ("clusters", &[crate::slice::Slice::Global], repo_scope),
    // scan (rules engine): reads global (communities, clone bands) + churn.
    (
        "scan",
        &[crate::slice::Slice::Global, crate::slice::Slice::Churn],
        repo_scope,
    ),
    // edges + churn: context_pack seeds off files/entities, expands one hop
    // over resolved edges, and ranks with the same complexity+churn score
    // hotspots uses.
    (
        "context_pack",
        &[crate::slice::Slice::Edges, crate::slice::Slice::Churn],
        repo_scope,
    ),
    // No freshness gate (deliberate): detect_changes diffs the persisted store
    // against current source, so updating raw rows first would zero out
    // the very diff it reports; slice_state is a diagnostic dump.
    ("detect_changes", &[], never_scope),
    ("slice_state", &[], never_scope),
    // batch has no slices of its own — each indexed child checks itself
    // via its own FRESHNESS entry when it runs.
    ("batch", &[], never_scope),
    // nav_map spans every other section's data source (raw entities for
    // entrypoints, edges for module_layers/symbols/flows, global for
    // subsystems, raw+churn for hotspots) — check the union.
    (
        "nav_map",
        &[
            crate::slice::Slice::Raw,
            crate::slice::Slice::Edges,
            crate::slice::Slice::Global,
            crate::slice::Slice::Churn,
        ],
        repo_scope,
    ),
];

/// Whole-repository source scope for indexed modes.
fn repo_scope(input: &serde_json::Value) -> Option<crate::slice::Scope> {
    opt_str(input, "repoRoot").map(|_| crate::slice::Scope::Repo)
}

/// `Scope::File(path)` when a `repoRoot` is present; `None` otherwise.
fn raw_file_scope(input: &serde_json::Value) -> Option<crate::slice::Scope> {
    let root = opt_str(input, "repoRoot")?;
    opt_str(input, "filePath").map(|p| {
        let path = resolve_scope_path(root, p);
        if std::path::Path::new(&path).is_file() {
            crate::slice::Scope::File(path)
        } else {
            crate::slice::Scope::Repo
        }
    })
}

/// `Scope::File(path)` when a path is given, else `Scope::Repo`, but only
/// when a `repoRoot` is present.
fn raw_file_or_repo_scope(input: &serde_json::Value) -> Option<crate::slice::Scope> {
    let root = opt_str(input, "repoRoot")?;
    match opt_str(input, "filePath").or_else(|| opt_str(input, "file")) {
        Some(p) => {
            let path = resolve_scope_path(root, p);
            if std::path::Path::new(&path).is_file() {
                Some(crate::slice::Scope::File(path))
            } else {
                Some(crate::slice::Scope::Repo)
            }
        }
        None => Some(crate::slice::Scope::Repo),
    }
}

fn resolve_scope_path(repo_root: &str, path: &str) -> String {
    let path = std::path::Path::new(path);
    if path.is_absolute() {
        path.display().to_string()
    } else {
        std::path::Path::new(repo_root)
            .join(path)
            .display()
            .to_string()
    }
}

/// A scope resolver for diagnostic modes that read as-is by design.
fn never_scope(_input: &serde_json::Value) -> Option<crate::slice::Scope> {
    None
}

thread_local! {
    /// Within a [`batch`] call, the set of freshen plans (repo_root + slices +
    /// scope) already brought up to date this batch. `None` outside a batch, so
    /// standalone queries never memoize and behave exactly as before. Lets a
    /// batch of repeated same-scope modes (e.g. five graph traversals, all
    /// `Edges`@`Repo`) pay the repo-walk change-detection once instead of once
    /// per call — the batch is a single filesystem snapshot. Thread-local, so a
    /// mode that spawns worker threads is unaffected; `batch` dispatches its
    /// calls sequentially on the one thread that owns this memo.
    static BATCH_FRESHEN_MEMO: std::cell::RefCell<Option<std::collections::HashSet<String>>> =
        const { std::cell::RefCell::new(None) };
}

/// RAII guard that enables batch freshen memoization for its lifetime and
/// clears it on drop (including on panic / early return). Batches never nest
/// (`batch` rejects a nested `batch` call), so a flat set/clear is sufficient.
///
/// The memo is an intra-batch dedup optimization only, not a transactional
/// record: it is discarded unconditionally on drop, so a batch that errors or
/// panics partway leaves nothing behind and a retry re-freshens every slice
/// from scratch. Freshening is idempotent, so this re-work is safe, just not
/// free. The memo never spans batches.
struct BatchFreshenScope;

/// Test-only counter of freshen runs that actually executed `ensure_fresh`
/// (memo misses). Racy against any other freshen-driving test, so the batch
/// memo test reads a before/after delta under [`crate::HOME_TEST_LOCK`].
#[cfg(test)]
pub(crate) static FRESHEN_RUN_CALLS: std::sync::atomic::AtomicUsize =
    std::sync::atomic::AtomicUsize::new(0);

impl BatchFreshenScope {
    fn enter() -> Self {
        BATCH_FRESHEN_MEMO.with(|m| *m.borrow_mut() = Some(std::collections::HashSet::new()));
        BatchFreshenScope
    }
}

impl Drop for BatchFreshenScope {
    fn drop(&mut self) {
        BATCH_FRESHEN_MEMO.with(|m| *m.borrow_mut() = None);
    }
}

/// Stable key for a freshness check in the batch memo. Include the database
/// override so two indexes for the same source root cannot share a result.
fn freshen_memo_key(
    slices: &[crate::slice::Slice],
    repo_root: &str,
    db_path: Option<&str>,
    scope: &crate::slice::Scope,
) -> String {
    let slice_part = slices
        .iter()
        .map(|s| s.as_str())
        .collect::<Vec<_>>()
        .join(",");
    let scope_part = match scope {
        crate::slice::Scope::File(p) => p.as_str(),
        crate::slice::Scope::Repo => "\u{2}repo",
    };
    format!(
        "{repo_root}\u{1}{}\u{1}{slice_part}\u{1}{scope_part}",
        db_path.unwrap_or("")
    )
}

/// Check the slice(s) an indexed query mode reads, per [`FRESHNESS`].
///
/// No-op when the mode is absent (find_pattern: live parse), the resolver
/// returns `None` (diagnostic mode). Missing or stale state is reported
/// without acquiring a writer lock or changing the index.
///
/// Inside a [`batch`], a successful check for the same scope is reused. A
/// failed check is never memoized, so later children report their own errors.
/// The public name is retained for existing library callers.
pub fn freshen_for_mode(
    mode: &str,
    input: &serde_json::Value,
) -> std::result::Result<(), ApiError> {
    let Some((_, slices, resolve_scope)) = FRESHNESS.iter().find(|(m, _, _)| *m == mode) else {
        return Ok(());
    };
    if slices.is_empty() {
        return Ok(());
    }
    let repo_root = req_str(input, "repoRoot")?;
    let Some(scope) = resolve_scope(input) else {
        return Ok(());
    };

    let key = freshen_memo_key(slices, repo_root, opt_str(input, "dbPath"), &scope);
    let already_fresh =
        BATCH_FRESHEN_MEMO.with(|m| m.borrow().as_ref().is_some_and(|set| set.contains(&key)));
    if already_fresh {
        return Ok(());
    }

    // Test-only counter of *actual* freshen runs (the expensive repo-walk
    // detection): a memo hit returns above without incrementing, so a batch
    // regression test can assert each distinct plan freshens exactly once.
    #[cfg(test)]
    FRESHEN_RUN_CALLS.fetch_add(1, std::sync::atomic::Ordering::Relaxed);

    // Clear any earlier record so the check below describes this call only;
    // `open_db` re-records the base index when it serves one.
    let _ = take_base_index();
    let conn = open_db(input)?;
    if BASE_INDEX.with(|slot| slot.borrow().is_some()) {
        // The answer comes from the main checkout's index, which cannot be
        // validated against this worktree's files; the envelope's
        // `base_index` note warns the caller (changed-file overlay deferred).
        return Ok(());
    }
    if opt_str(input, "dbPath").is_some()
        && crate::persist::slice_meta_value(&conn, "source_root")
            .ok()
            .flatten()
            != Some(crate::db::path::repo_identity(std::path::Path::new(
                repo_root,
            )))
    {
        return Err(ApiError::new(
            "index_stale",
            "dbPath index was built for another source root or predates source-root validation",
        ));
    }
    let fresh = crate::slice::check_fresh(&conn, slices, repo_root, &scope)
        .map_err(|e| ApiError::new("index_stale", format!("cannot verify index freshness: {e}")))?;
    if !fresh {
        return Err(ApiError::new(
            "index_stale",
            "index is stale for this source root; the coordinator can refresh it with `varde setup watch --ensure --repo <repo-root>`; find_pattern needs no index",
        ));
    }

    BATCH_FRESHEN_MEMO.with(|m| {
        if let Some(set) = m.borrow_mut().as_mut() {
            set.insert(key);
        }
    });
    Ok(())
}

/// Run one query mode against a JSON input string, returning the envelope.
///
/// The mode is dispatched by name; unknown modes and malformed inputs render
/// as error envelopes (never a process-level failure).
pub fn run_mode(mode: &str, input: &str) -> String {
    let value: serde_json::Value = match serde_json::from_str(input) {
        Ok(v) => v,
        Err(e) => {
            return render(Err(ApiError::new(
                "invalid_input",
                format!("input is not valid JSON: {e}"),
            )));
        }
    };
    let result = dispatch_mode_with_meta(mode, &value, None);
    let meta = result
        .as_ref()
        .map(|(_, meta)| meta.clone())
        .unwrap_or_default();
    render_with_meta(result.map(|(data, _)| data), meta)
}

/// Dispatch one mode by name against an already-parsed input object.
///
/// The single routing table shared by [`run_mode`] (top-level CLI/API entry)
/// and [`batch`] (per-call routing inside a batch request) — adding a mode
/// here wires it into both.
fn dispatch_mode_with_meta(
    mode: &str,
    value: &serde_json::Value,
    mode_tag: Option<&str>,
) -> Result<(serde_json::Value, crate::query::output::OutputMeta), ApiError> {
    // A base-index record describes what THIS dispatch read, never a previous
    // call's or a batch sibling's.
    let _ = take_base_index();
    // An absolute path under the querying worktree must be mapped onto the
    // main checkout root before the handler looks it up in the base index;
    // the answer is mapped back the other way below.
    let mapped = map_base_input(mode, value);
    let input = mapped.as_ref().unwrap_or(value);
    dispatch_mode_inner(mode, input).and_then(|mut data| {
        let base = take_base_index();
        if let Some(base) = &base {
            rewrite_base_paths(&mut data, base, value);
        }
        let pagination =
            crate::query::output::paginate_query_with_mode_tag(mode, value, &mut data, mode_tag)?;
        // Single output boundary for every mode (and, via `batch`, each of its
        // sub-calls): repo-relative paths (F5) + line-only spans (F6). Both
        // transforms are idempotent, so a `batch` payload seeing this twice —
        // once per sub-call with that call's own `repoRoot`, once for the
        // aggregate — is harmless.
        let mut meta = crate::query::output::assemble_metadata(&mut data, value, pagination);
        meta.base_index = base.map(base_index_note);
        Ok((data, meta))
    })
}

fn dispatch_mode_inner(
    mode: &str,
    value: &serde_json::Value,
) -> Result<serde_json::Value, ApiError> {
    type Handler = fn(&serde_json::Value) -> Result<serde_json::Value, ApiError>;
    const HANDLERS: &[(&str, Handler)] = &[
        ("symbols_in_file", crate::query::simple::symbols_in_file),
        ("symbols_in_files", crate::query::simple::symbols_in_files),
        ("get_symbol", crate::query::simple::get_symbol),
        ("tests_for_file", crate::query::simple::tests_for_file),
        ("find_imports", crate::query::simple::find_imports),
        ("filter_symbols", crate::query::simple::filter_symbols),
        ("dependencies", crate::query::graph::dependencies),
        ("dependents", crate::query::graph::dependents),
        ("blast_radius", crate::query::graph::blast_radius),
        (
            "symbol_blast_radius",
            crate::query::graph::symbol_blast_radius,
        ),
        ("type_hierarchy", crate::query::graph::type_hierarchy),
        ("explore", crate::query::graph::explore),
        ("map_file", crate::query::mapping::map_file),
        ("map_symbol", crate::query::mapping::map_symbol),
        ("map_path", crate::query::mapping::map_path),
        ("detect_changes", crate::query::mapping::detect_changes),
        ("hotspots", crate::query::mapping::hotspots),
        ("clusters", crate::query::mapping::clusters),
        ("context_pack", crate::query::mapping::context_pack),
        ("nav_map", crate::query::nav_map::nav_map),
        ("find_pattern", crate::query::find_pattern::find_pattern),
        ("slice_state", slice_state),
        ("batch", batch),
    ];

    let handler = HANDLERS
        .iter()
        .find_map(|(name, handler)| (*name == mode).then_some(*handler))
        .ok_or_else(|| ApiError::new("unknown_mode", format!("unknown query mode {mode:?}")))?;
    handler(value)
}

/// `--why` style slice freshness dump for a repo (see [`crate::slice::dump_state`]).
fn slice_state(value: &serde_json::Value) -> Result<serde_json::Value, ApiError> {
    crate::slice::dump_state(value).map_err(|e| ApiError::new("db_error", format!("{e}")))
}

/// batch — run several query modes in one call, sharing one JSON envelope.
///
/// Inputs: `calls` (required array of `{mode, ...mode-specific fields}`
/// objects). Each call inherits the batch's `repoRoot`/`dbPath` when it
/// doesn't specify its own. `mode: "batch"` may not nest. Output: an array,
/// one entry per call in order, each a `{mode, ok, data, meta}` envelope. One
/// call's failure never fails the batch. Calls dispatch through the same
/// [`dispatch_mode_with_meta`] every mode function
/// calls its own `freshen_for_mode` from, but for the duration of the batch a
/// freshen plan (slices + scope) is brought up to date at most once: the batch
/// is a single filesystem snapshot, so five graph traversals pay the
/// repo-walk change-detection once, not five times (see [`BatchFreshenScope`]
/// / [`freshen_for_mode`]).
fn batch(input: &serde_json::Value) -> Result<serde_json::Value, ApiError> {
    let calls = input
        .get("calls")
        .and_then(|v| v.as_array())
        .ok_or_else(|| ApiError::new("invalid_input", "missing array field \"calls\""))?;

    // Memoize freshen plans across this batch's calls (cleared on drop).
    let _freshen_scope = BatchFreshenScope::enter();

    let mut results = Vec::with_capacity(calls.len());
    for call in calls {
        let Some(mode) = call.get("mode").and_then(|v| v.as_str()) else {
            results.push(batch_result(
                None,
                Err(ApiError::new(
                    "invalid_input",
                    "batch call missing string field \"mode\"",
                )),
            ));
            continue;
        };
        if mode == "batch" {
            results.push(batch_result(
                Some(mode),
                Err(ApiError::new(
                    "invalid_input",
                    "batch calls cannot nest \"batch\"",
                )),
            ));
            continue;
        }
        let merged = merge_repo_context(input, call);
        results.push(batch_result(
            Some(mode),
            dispatch_mode_with_meta(mode, &merged, Some(mode)),
        ));
    }
    Ok(serde_json::Value::Array(results))
}

fn batch_result(
    mode: Option<&str>,
    result: Result<(serde_json::Value, crate::query::output::OutputMeta), ApiError>,
) -> serde_json::Value {
    let meta = result
        .as_ref()
        .map(|(_, meta)| meta.clone())
        .unwrap_or_default();
    render_batch_value(result.map(|(data, _)| data), meta, mode)
}

/// A batch call's own `repoRoot`/`dbPath` wins; otherwise it inherits the
/// batch request's, so callers don't have to repeat it on every call.
fn merge_repo_context(input: &serde_json::Value, call: &serde_json::Value) -> serde_json::Value {
    let mut merged = call.clone();
    if merged.get("repoRoot").is_none()
        && let Some(root) = input.get("repoRoot")
    {
        merged["repoRoot"] = root.clone();
    }
    if merged.get("dbPath").is_none()
        && call.get("repoRoot").is_none()
        && let Some(db) = input.get("dbPath")
    {
        merged["dbPath"] = db.clone();
    }
    merged
}

// Mode submodules (implemented by subsequent tasks).
pub mod entrypoints;
pub mod find_pattern;
pub mod flows;
pub mod foundational_files;
pub mod graph;
pub mod mapping;
pub mod module_layers;
pub mod nav_map;
pub mod noise_filter;
pub mod output;
pub mod simple;
pub mod subsystems;
mod symbol_impact;
pub mod symbols_section;
#[cfg(test)]
mod test_support;

#[cfg(test)]
mod batch_freshen_tests {
    use super::*;
    use crate::query::test_support::test_support::with_isolated_home;
    use std::sync::atomic::Ordering;

    fn temp_root(label: &str) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "varde-query-batch-{label}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock after epoch")
                .as_nanos()
        ));
        std::fs::create_dir_all(&path).expect("temp root creates");
        path
    }

    /// A batch freshens each distinct plan (slices + scope) exactly once, not
    /// once per call: three `Edges`@`Repo` graph calls + one `Raw`@`File` call
    /// must run `ensure_fresh` twice total. Contrast: the same calls dispatched
    /// standalone freshen once each.
    #[test]
    fn batch_freshens_each_plan_once() {
        with_isolated_home("query-batch", "freshen-once", || {
            let root = temp_root("freshen-once");
            std::fs::write(root.join("a.py"), "import b\n\ndef fa():\n    return 1\n")
                .expect("write a.py");
            std::fs::write(root.join("b.py"), "def fb():\n    return 2\n").expect("write b.py");
            crate::build::run_with_force(root.to_str().unwrap(), true).expect("full build");

            let rr = root.to_str().unwrap();
            let a = root.join("a.py").to_str().unwrap().to_string();
            let b = root.join("b.py").to_str().unwrap().to_string();
            let calls = serde_json::json!({
                "repoRoot": rr,
                "calls": [
                    {"mode": "blast_radius", "filePath": a},        // Edges@Repo
                    {"mode": "dependents", "filePath": b},          // Edges@Repo (memoized)
                    {"mode": "symbols_in_file", "filePath": a},     // Raw@File(a) — distinct plan
                    {"mode": "blast_radius", "filePath": b},        // Edges@Repo (memoized)
                ],
            });

            let before = FRESHEN_RUN_CALLS.load(Ordering::Relaxed);
            let out = batch(&calls).expect("batch runs");
            let batch_runs = FRESHEN_RUN_CALLS.load(Ordering::Relaxed) - before;
            assert_eq!(
                batch_runs, 2,
                "batch must freshen the two distinct plans (Edges@Repo, Raw@File) once each"
            );
            assert_eq!(
                out.as_array().map(Vec::len),
                Some(4),
                "all four calls dispatched"
            );
            assert!(
                out.as_array()
                    .unwrap()
                    .iter()
                    .all(|r| r["ok"].as_bool() == Some(true)),
                "every call ok: {out}"
            );

            // Standalone (no batch memo): each call freshens on its own.
            let before = FRESHEN_RUN_CALLS.load(Ordering::Relaxed);
            for call in calls["calls"].as_array().unwrap() {
                let mut merged = call.clone();
                merged["repoRoot"] = serde_json::json!(rr);
                let _ = dispatch_mode_with_meta(call["mode"].as_str().unwrap(), &merged, None);
            }
            let standalone_runs = FRESHEN_RUN_CALLS.load(Ordering::Relaxed) - before;
            assert_eq!(
                standalone_runs, 4,
                "standalone dispatch freshens once per call (no memo)"
            );

            let db = crate::db::path::repo_db_path(&root);
            let _ = std::fs::remove_file(&db);
            let _ = std::fs::remove_dir_all(&root);
        });
    }
}

#[cfg(test)]
mod read_only_contract_tests {
    use super::*;
    use crate::query::test_support::test_support::with_isolated_home;

    #[test]
    fn indexed_queries_preserve_db_bytes_and_report_missing_or_stale() {
        with_isolated_home("query-read-only", "states", || {
            let root = std::env::temp_dir().join(format!("varde-read-only-{}", std::process::id()));
            std::fs::create_dir_all(&root).unwrap();
            let file = root.join("main.py");
            std::fs::write(&file, "def first():\n    return 1\n").unwrap();
            let input = serde_json::json!({"repoRoot": root, "filePath": file});
            let missing: Value =
                serde_json::from_str(&run_mode("symbols_in_file", &input.to_string())).unwrap();
            assert_eq!(missing["data"]["error"]["code"], "index_missing");
            let db = crate::db::path::repo_db_path(&root);
            assert!(!db.exists(), "query did not create an index");

            crate::build::run(root.to_str().unwrap()).unwrap();
            let before = std::fs::read(&db).unwrap();
            let fresh: Value =
                serde_json::from_str(&run_mode("symbols_in_file", &input.to_string())).unwrap();
            assert_eq!(fresh["ok"], true, "{fresh}");
            assert_eq!(std::fs::read(&db).unwrap(), before);

            std::fs::write(&file, "def second():\n    return 2345\n").unwrap();
            let stale: Value =
                serde_json::from_str(&run_mode("symbols_in_file", &input.to_string())).unwrap();
            assert_eq!(stale["data"]["error"]["code"], "index_stale");
            assert_eq!(std::fs::read(&db).unwrap(), before);
            std::fs::remove_dir_all(root).unwrap();
        });
    }

    #[test]
    fn db_override_requires_source_root_and_batch_inherits_per_child() {
        with_isolated_home("query-read-only", "batch", || {
            let root =
                std::env::temp_dir().join(format!("varde-read-only-batch-{}", std::process::id()));
            std::fs::create_dir_all(&root).unwrap();
            let file = root.join("main.py");
            std::fs::write(&file, "def first():\n    return 1\n").unwrap();
            crate::build::run(root.to_str().unwrap()).unwrap();
            let db = crate::db::path::repo_db_path(&root);
            let no_root = serde_json::json!({"dbPath": db, "filePath": file});
            let invalid: Value =
                serde_json::from_str(&run_mode("symbols_in_file", &no_root.to_string())).unwrap();
            assert_eq!(invalid["data"]["error"]["code"], "invalid_input");
            let other =
                std::env::temp_dir().join(format!("varde-read-only-other-{}", std::process::id()));
            std::fs::create_dir_all(&other).unwrap();
            std::fs::write(other.join("main.py"), "def other():\n    return 2\n").unwrap();
            let wrong_root = serde_json::json!({"repoRoot": other, "dbPath": db, "filePath": other.join("main.py")});
            let mismatch: Value =
                serde_json::from_str(&run_mode("symbols_in_file", &wrong_root.to_string()))
                    .unwrap();
            assert_eq!(mismatch["data"]["error"]["code"], "index_stale");
            let batch = serde_json::json!({"repoRoot": root, "dbPath": db, "calls": [
                {"mode": "symbols_in_file", "filePath": file},
                {"mode": "symbols_in_file", "repoRoot": "/missing-repo", "filePath": file},
                {"mode": "slice_state", "dbPath": db}
            ]});
            let result: Value =
                serde_json::from_str(&run_mode("batch", &batch.to_string())).unwrap();
            assert_eq!(result["data"][0]["ok"], true, "{result}");
            assert_eq!(result["data"][1]["data"]["error"]["code"], "index_missing");
            assert_eq!(result["data"][2]["ok"], true, "{result}");
            std::fs::remove_dir_all(other).unwrap();
            std::fs::remove_dir_all(root).unwrap();
        });
    }

    #[test]
    fn derived_slice_ledger_is_checked_without_repair() {
        with_isolated_home("query-read-only", "ledger", || {
            let root =
                std::env::temp_dir().join(format!("varde-read-only-ledger-{}", std::process::id()));
            std::fs::create_dir_all(&root).unwrap();
            let file = root.join("main.py");
            std::fs::write(&file, "def first():\n    return 1\n").unwrap();
            crate::build::run(root.to_str().unwrap()).unwrap();
            let db = crate::db::path::repo_db_path(&root);
            let conn = rusqlite::Connection::open(&db).unwrap();
            conn.execute("DELETE FROM slice_state WHERE slice = 'edges'", [])
                .unwrap();
            drop(conn);
            let before = std::fs::read(&db).unwrap();
            let input = serde_json::json!({"repoRoot": root, "filePath": file});
            let result: Value =
                serde_json::from_str(&run_mode("dependencies", &input.to_string())).unwrap();
            assert_eq!(result["data"]["error"]["code"], "index_stale");
            assert_eq!(std::fs::read(&db).unwrap(), before);
            std::fs::remove_dir_all(root).unwrap();
        });
    }

    #[test]
    fn db_override_rejects_a_different_empty_repository() {
        with_isolated_home("query-read-only", "identity", || {
            let base =
                std::env::temp_dir().join(format!("varde-empty-identity-{}", std::process::id()));
            let first = base.join("first");
            let second = base.join("second");
            std::fs::create_dir_all(&first).unwrap();
            std::fs::create_dir_all(&second).unwrap();
            crate::build::run(first.to_str().unwrap()).unwrap();
            let db = crate::db::path::repo_db_path(&first);
            let input = serde_json::json!({"repoRoot": second, "dbPath": db});
            let result: Value =
                serde_json::from_str(&run_mode("nav_map", &input.to_string())).unwrap();
            assert_eq!(result["data"]["error"]["code"], "index_stale");
            std::fs::remove_dir_all(base).unwrap();
        });
    }
}
