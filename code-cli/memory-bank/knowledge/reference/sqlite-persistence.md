---
type: reference
status: active
title: "varde-code SQLite persistence API"
related: ["2026-08-12-varde-code-rust-port/sqlite-persistence"]
---

# varde-code SQLite persistence API reference

Contract reference for the persistence phase of varde-code (the Rust
code-intelligence core): the durability boundary that turns the in-memory
`ExtractOutput`/`ResolvedGraph` from the `parsing-extraction` and
`resolution-graph-algorithms` phases into a queryable on-disk store that
`query-surface` reads back.

Source of truth: `crates/varde-code/src/persist.rs`, `crates/varde-code/src/db.rs`,
`crates/varde-code/src/db/path.rs`, `crates/varde-code/src/complexity.rs`,
`crates/varde-code/src/churn.rs`. Cross-check with
`cargo doc -p varde-code --no-deps`.

## Entry point

```rust
pub fn persist(db_path: &Path, output: &[ExtractOutput], graph: &ResolvedGraph) -> Result<()>
```

(`Result` is `anyhow::Result`, as in the source.)

- Opens the database, wraps **everything** — schema drop/rebuild and every
  table write — in one transaction, and commits. An interruption at any point
  rolls back to the prior valid state (no partial writes, no half-rebuilt
  schema).
- Write model: **full rebuild per run**. `db::rebuild_schema` drops and
  recreates all tables/indexes, so a second `persist` against the same path
  leaves exactly the second run's data.
- Complexity and churn are computed inside `persist` (complexity folded into
  the entity write; churn via `churn::commit_counts_batch` on a background
  thread) and stored as columns at write time, keeping `query-surface` a pure
  reader.
- Tracing: one `tracing` span per stage — `persist`, `schema`, `files`,
  `entities`, `symbols`, `diagnostics`, `edges`, `communities`, `clone_bands`.
  When no subscriber is configured, a scoped (thread-local) fmt subscriber
  writes human-readable logs to stderr; an existing subscriber (CLI, caller,
  or test) is always respected.
- DB path: `~/.config/varde-code/repos/<name>-<hash>/index.db` via
  `db::path::repo_db_path` (see Resolved decisions).

## Schema

Own schema, own DB path — independent of varde's 28-table `intelligence.db`
shape. Surrogate `INTEGER PRIMARY KEY AUTOINCREMENT` rowids per table.

### files

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `path` | TEXT NOT NULL UNIQUE | one row per distinct path across entities, symbols, diagnostics |
| `complexity` | INTEGER | cyclomatic, backfilled at persist time |
| `churn` | INTEGER | 90-day commit count, backfilled at persist time |
| `fan_in` | INTEGER NOT NULL DEFAULT 0 | copied from `FileNode.fan_in` |
| `fan_out` | INTEGER NOT NULL DEFAULT 0 | copied from `FileNode.fan_out` |
| `community_id` | INTEGER | surrogate id of the community listing this file |

### entities

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `kind` | TEXT NOT NULL | snake_case `EntityKind` (`function`, `class`, ..., `control_flow`, `route`, `response`) |
| `name` | TEXT NOT NULL | |
| `file_id` | INTEGER NOT NULL | → `files.id` |
| `start_byte` / `end_byte` | INTEGER NOT NULL | span (0-based bytes) |
| `start_line` / `start_col` / `end_line` / `end_col` | INTEGER NOT NULL | span (1-based lines, 0-based cols) |
| `enclosing_function` / `method` / `path` / `status` / `body_shape` | TEXT | nullable optionals |

### symbols

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `kind` | TEXT NOT NULL | `binding` \| `reference` (snake_case `SymbolKind`) |
| `name` | TEXT NOT NULL | |
| `file_id` | INTEGER NOT NULL | → `files.id` |
| span columns (6) | INTEGER NOT NULL | as in `entities` |

### diagnostics

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `file_id` | INTEGER NOT NULL | → `files.id`; diagnostic-only files still get a `files` row |
| `message` | TEXT NOT NULL | persisted verbatim, no re-validation |
| `severity` | TEXT NOT NULL | |

### resolved_edges

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `from_file_id` | INTEGER NOT NULL | → `files.id` |
| `to_file_id` | INTEGER | → `files.id`; NULL when the edge is unresolved |
| `kind` | TEXT NOT NULL | `call` \| `import` |
| `resolved` | INTEGER NOT NULL | 0/1; unresolved edges are persisted, not dropped |

### communities + community_members

- `communities(id INTEGER PK AUTOINCREMENT, label TEXT NOT NULL)` — label is
  `community-<upstream id>` (the model carries no intrinsic label).
- `community_members(community_id INTEGER NOT NULL, file_id INTEGER NOT NULL)`
  — one row per (community, file) membership pair; `community_id` is the
  surrogate id, not the upstream `Community.id`.

### clone_bands + clone_band_members

- `clone_bands(id INTEGER PK AUTOINCREMENT, label TEXT NOT NULL)` — label is
  `clone-band-<upstream id>`.
- `clone_band_members(band_id INTEGER NOT NULL, entity_id INTEGER NOT NULL)`
  — one row per (band, entity) pair; `entity_id` references `entities.id`.

## Indexes

Built fresh each full-rebuild run (drop/rebuild alongside the batched write).
Cover `query-surface`'s O(1)/O(log N)-per-traversal acceptance criteria:

- `idx_resolved_edges_from` on `resolved_edges(from_file_id)` — `dependencies` / `blast_radius`
- `idx_resolved_edges_to` on `resolved_edges(to_file_id)` — `dependents`
- `idx_entities_file` on `entities(file_id)` — `symbols_in_file`-style lookups
- `idx_symbols_file` on `symbols(file_id)`

## Resolved decisions

The four decisions later phases must not re-derive (see
`plan.md` → Decisions so far for the full list):

1. **DB path hash scheme** — FNV-1a 64-bit over the repo root path exactly as
   passed (hex-encoded, 16 lowercase chars), under
   `~/.config/varde-code/repos/<name>-<hash>/index.db`. Chosen dependency-free;
   the hash covers the full path, so two roots sharing a basename cannot
   collide. Pure function — no filesystem I/O during computation; parent
   directory creation is `persist`'s responsibility.
2. **Fan-in/fan-out source of truth** — `resolution-graph-algorithms`'
   `FileNode.fan_in`/`fan_out` are copied verbatim onto `files.fan_in`/
   `files.fan_out`. Never recomputed from `resolved_edges`.
3. **Complexity / churn formulas** — complexity: cyclomatic McCabe-style,
   `1 + number of ControlFlow entities in the file` (a zero-control-flow file
   scores exactly 1). Churn: commit count touching the file within the last
   90 days via `git log`; 0 for untracked files, non-repo directories, or any
   git failure.
4. **Clone-band correlation key** — `CloneBand.members` holds indices into
   the flat entity vector (pre-surrogate-id). Members are joined to persisted
   `entities` rows via `(file_id, start_byte, end_byte)` — the only stable
   identity across the phase boundary.

## Deliberately not persisted

- `entities.imported_names` / `entities.body_tokens` — consumed upstream by
  resolution and clone detection; the schema has no columns for them.
- varde's dead `health_findings` / `health_markers` / `health_run_fingerprint`
  tables — confirmed dead code and removed from varde itself; excluded here.
