---
status: accepted
title: varde-code is a full end-to-end Rust port of the code-intelligence subsystem
type: decision
paths: []
enriched_at_commit: null
generated:
  by: human:unknown
  at: 2026-08-12T16:37:52.000Z
verified:
  - by: human:unknown
    at: 2026-08-12T16:37:52.000Z
---

## What
`varde-code` (standalone repo at `~/source/varde-code`) is a full end-to-end port of varde's
entire code-intelligence subsystem to Rust, with its own CLI: multi-language tree-sitter
parsing, entity/symbol extraction, call/import resolution, dependency graph, community
detection, fan metrics, entity fingerprinting/clone-detection bands, SQLite persistence, and
the full query surface (every mode `code_query` currently exposes — symbols_in_file,
get_symbol, dependents, blast_radius, hotspots, type_hierarchy, find_pattern, etc.).

## Why
Profiling (2026-08-12) showed varde's current parse+extract phase runs at ~570 files/sec vs.
ast-grep's ~5300-9700 files/sec (native Rust, tree-sitter) — a 12-19x gap. The user chose to
address this by porting the entire subsystem to Rust rather than a targeted extraction-only
native module, treating varde-code as an independent CLI tool developed and shippable on its
own.

## Constraints
- Developed as a fully independent repo/CLI, not a napi-rs library embedded in varde — varde
  does not depend on varde-code during its development.
- MCP integration into varde (wrapping varde-code to serve varde's `code_query`/
  `code_intelligence_index` tools) is explicitly deferred — "non-core could wrap core in MCP
  at some point if determined necessary" — not part of this plan.
- Parity with the current TS extractor is a superset, not byte-identical: varde-code may add
  fields/precision the TS version lacks (see [[definition/varde-code-parity]]).
