---
id: decision/implementation-language-rust
type: decision
status: accepted
generated:
  by: human:unspecified
  at: 2026-08-13T20:30:18.069Z
verified: []
paths: []
enriched_at_commit: null
_version: ea32670232c0718334ffea571b1c1c75912beeadd7097f51decd3f28e2b901cf
---

## What

Implement varde-workflow in Rust, matching the `cyano-core` precedent
rather than TypeScript/Node (cyano's own stack) or Python (the OKF v0.2
reference implementation's language, per its `pyproject.toml`).

## Why

The tool talks to consumers (cyano, editors, agents) over CLI/MCP
stdio+JSON regardless of implementation language, so there is no
interop cost to picking a language different from cyano's TS core — the
process boundary already isolates it. Matching `cyano-core` gives
single-binary distribution and consistency across the two standalone,
independently-developed repos. The OKF spec itself is language-agnostic
(a markdown+frontmatter format, not a bound reference implementation),
so it does not push toward Python.

## Constraints

- Assumes this repo stays CLI/MCP-server-only and is never embedded as a
  library inside another process — if that changes, revisit.
