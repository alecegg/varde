---
status: accepted
title: Resolution phase extends the handoff model with Import entities and body tokens
type: decision
paths: ["crates/varde-code/src/model.rs", "crates/varde-code/src/extract/entity.rs", "crates/varde-code/src/extract/langs/rust.rs", "crates/varde-code/src/extract/langs/ts.rs", "crates/varde-code/src/extract/langs/javascript.rs", "crates/varde-code/src/resolve.rs"]
enriched_at_commit: null
generated:
  by: harness:varde-build
  at: 2026-08-13T00:00:00.000Z
verified: []
---

## What

`resolution-graph-algorithms` (executed 2026-08-13) discovered that the
`parsing-extraction` handoff data could not satisfy its acceptance criteria:
import statements were not represented (Rust `use` produced bare reference
symbols; JS/TS import bindings carried names but not the module specifier),
and function bodies were not available for clone detection. The phase
extended the superset-safe model instead of re-parsing:

- `EntityKind::Import` — one entity per import/use statement, `name` = module
  specifier, `imported_names` = bound names. Emitted by the Rust
  (`use_declaration`), TypeScript, and JavaScript (`import_statement`)
  extractors; other languages are future work.
- `Entity.body_tokens` — lowercased alphanumeric tokens of a Function entity's
  node text, computed in the shared `entity()` constructor; consumed by
  MinHash/LSH clone-band detection.
- `EntityKind::Extends`/`EntityKind::Implements` (discriminants 15/16, added by
  the `type-hierarchy-edges` plan) — one entity per extends/implements
  relationship, `name` = raw supertype/interface name, `enclosing_function`
  reused to hold the owning class/type's name. Unlike `Import` (file→file),
  these resolve to entity→entity edges in `resolved_edges` via the new
  `to_entity_id` column and `EdgeKind::Extends`/`Implements`. Emitted by all
  10 currently-supported language extractors.

## Why

- The plan's constraint "operates entirely on extracted data, no re-parsing"
  forced the data into the handoff structure.
- The model explicitly documented itself as superset-safe ("future kinds may
  be added"), so this was the designed seam — no schema break.
- Import resolution and clone detection are owned by this phase, so the
  extraction gap had to close here rather than in a future phase.

## Consequences

- Extract JSON gains optional `imported_names`/`body_tokens` fields
  (`skip_serializing_if = None`); existing fixtures/tests unaffected.
- A future `Import`-kind addition for Go/Kotlin/Swift/Python/etc. can slot in
  without resolver changes.
- Path-level gotcha (max 4 bullets):
  - tracing's callsite-interest cache is global and "AND"-joined across
    registered dispatchers; a bare `warn!`/span from another test with the
    no-op default can starve per-thread scoped subscribers under parallel
    tests. Use a process-wide `set_global_default` capture buffer keyed on
    fixture content (`tracing_capture` in `resolve.rs` tests).
  - tracing's `SCOPED_COUNT` fast path is process-wide: when any other test's
    scoped guard drops, per-thread `set_default`/`with_default` subscribers
    are silently bypassed via the global fallback — never rely on them for
    assertions in a parallel test binary.
  - Louvain/community detection must be deterministic: nodes processed in id
    order, ties broken to the smallest community id (matches varde's TS).
  - `ResolvedEdge.to` is an enum: imports target `File(file_id)`, calls target
    `Entity(entity_id)`; unresolved edges carry `Unknown`.
