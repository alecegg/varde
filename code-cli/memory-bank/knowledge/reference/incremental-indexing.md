---
type: spec
status: active
title: "Incremental indexing"
related:
  - "reference/sqlite-persistence"
  - "definition/dependency-graph"
---

# Incremental indexing

Incremental indexing reuses persisted file state between builds. It reparses
only files whose source state changed, then refreshes global derived data.

## Change detection

Each persisted file records modification time, byte size, and content hash.
Metadata provides the fast comparison path. The content hash resolves cases
where metadata is unavailable. Files classify as unchanged, changed, new, or
deleted. Only changed and new files enter extraction.

## Delta persistence

Changed files replace their dependent rows within one transaction. Entities,
symbols, diagnostics, edges, and memberships are removed before replacement.
Unchanged file rows and their source data remain available. Orphaned global
community and clone-band rows are removed during cleanup.

## Global-pass recomputation

After file deltas persist, the build reads the complete stored entity and
symbol set. Resolution, communities, clone bands, fan metrics, complexity,
and churn are recomputed from that complete state. This preserves global graph
semantics when one file affects unchanged neighbors.

## `--force` flag

The build command accepts `--force` to bypass change detection. It reparses
every source file through the full rebuild path. Build output reports counts
for unchanged and reparsed files.

## Fallback behavior

Missing file-state columns or invalid stored hashes trigger a silent full
rebuild. The fallback replaces the database using the same complete output as
an ordinary full rebuild.

## Related

- [[reference/sqlite-persistence]] - stores indexed files and derived data
- [[definition/dependency-graph]] - defines persisted graph relationships
