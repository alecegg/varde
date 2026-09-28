---
type: decision
description: Truncated find_pattern results use a compact toz preview handle with deferred search indexing.
generated: { by: codex/gpt-6, at: 2026-09-25T13:45:14Z }
paths:
  - clis/code/crates/varde-code/src/query/find_pattern.rs
  - clis/code/crates/varde-code/src/toz.rs
  - clis/toz/crates/toz-core/src/store.rs
---

## What

When `find_pattern` is truncated, store each match's file, kind, span, and first 160 characters in toz. Keep full text and captures available through `matchesOffset` or `fullMatches`. Toz stores these rows in its existing chunks table and indexes them on the first term search.

## Why

Full automatic capture took 0.54 seconds on the representative search. The preview and deferred indexing path took 0.0761 seconds versus 0.0422 seconds for ast-grep, meeting code-cli's 2x limit.

## Constraints

- code-cli calls the toz binary; it does not write to toz's database.
- The handle searches previews and locations, not complete match bodies.
- Line-range reads work before indexing. A first term search requires a writable store and builds the search indexes.
