---
type: reference
status: active
title: "varde-code resolution graph API"
related: ["2026-08-12-varde-code-rust-port/resolution-graph-algorithms"]
---

# varde-code resolution graph API reference

Contract reference for the resolution phase of varde-code (the Rust
code-intelligence core): cross-file call/import resolution, dependency graph,
fan metrics, Louvain communities, and MinHash/LSH clone bands — all in-memory
(persistence belongs to the `sqlite-persistence` phase).

Source of truth: `crates/varde-code/src/resolve.rs` (+ `resolve/graph.rs`,
`resolve/community.rs`, `resolve/clones.rs`). Cross-check with
`cargo doc -p varde-code --no-deps`.

## Entry point

```rust
pub fn resolve(entities: &[Entity], symbols: &[Symbol]) -> Result<ResolvedGraph>
```

(`Result` is `anyhow::Result`, as in the source.)

- Consumes the `parsing-extraction` handoff structure: flat `Vec<Entity>` /
  `Vec<Symbol>` (no pre-built indices).
- `symbols` is accepted (plan-mandated signature) but currently unconsumed:
  call resolution matches `Call` entities by callee name rather than symbol
  references. Reserved for later phases (e.g. query-surface).
- Deterministic: node order is sorted by path; edge/band order follows input
  order. Unresolved references are left dangling (`resolved == false`) and
  reported via `tracing` diagnostics — the run always continues.
- Stages (each behind a `tracing` span): `resolve`, `import_resolution`,
  `call_resolution`, `graph_construction`, `community_detection`,
  `clone_detection`.

## ResolvedGraph

| field | type | notes |
|---|---|---|
| `nodes` | `Vec<FileNode>` | one node per distinct input file, sorted by path |
| `edges` | `Vec<ResolvedEdge>` | call + import edges (resolved and dangling) |
| `communities` | `Vec<Community>` | Louvain partition of the file graph |
| `clone_bands` | `Vec<CloneBand>` | near-duplicate function groups |

## FileNode

| field | type | notes |
|---|---|---|
| `path` | `String` | file path; node index in `nodes` is the `FileId` |
| `community_id` | `Option<u32>` | community id assigned by community detection |
| `fan_in` | `u32` | incoming resolved-edge count (imports targeting this file; calls invoking an entity declared here) |
| `fan_out` | `u32` | outgoing resolved-edge count |

## ResolvedEdge

| field | type | notes |
|---|---|---|
| `from` | `FileId` (`u32`) | file id of the referencing file |
| `to` | `EdgeTarget` | resolved target, or `Unknown` when dangling |
| `kind` | `EdgeKind` | `call` or `import` (snake_case) |
| `resolved` | `bool` | false when the reference stays dangling |

### EdgeTarget

`File(FileId)` — target file (import edges) · `Entity(u32)` — target entity id
(call edges; the invoked entity) · `Unknown` — no resolvable target.
JSON: `{"target": "file", ...}`, `{"target": "entity", ...}`,
`{"target": "unknown"}`.

## Community

| field | type | notes |
|---|---|---|
| `id` | `u32` | stable id (renumbered by lex-smallest member path) |
| `members` | `Vec<String>` | member file paths |

## CloneBand

| field | type | notes |
|---|---|---|
| `id` | `u32` | stable id |
| `members` | `Vec<u32>` | function entity ids grouped as near-duplicates |

## Entity id space

Entity ids referenced by `EdgeTarget::Entity` and `CloneBand::members` are
indices into the input `&[Entity]` slice, in input order.

## Resolution semantics

- Import resolution: same-language only. The normalized module specifier
  (quotes and `crate::`/`self::`/`super::`/`./`/`../` prefixes stripped) is
  matched whole against file stems, then with trailing path segments dropped
  one at a time; relative paths resolve against the importing file's
  directory first. Ambiguous matches stay unresolved.
- Call resolution: same-file pass (exact name, then last-path-segment), then
  an imported-module pass over the file's resolved import edges. A call
  resolves only when exactly one (module, entity) candidate matches.
- Fan metrics count only `resolved == true` edges.
- Communities: Louvain (greedy modularity via local moving, resolution = 1.0),
  faithful port of varde's TS `louvain()`.
- Clone bands: MinHash + LSH banding over shingled (size 5) function body
  tokens — 16 hash functions, 4 bands of 4 rows, deterministic FNV-1a.
