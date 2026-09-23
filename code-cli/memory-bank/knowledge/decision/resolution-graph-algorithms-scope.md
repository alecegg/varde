---
status: accepted
title: Resolution + graph algorithms phase scope, including clone-detection bands
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
The `resolution-graph-algorithms` phase computes: call resolution, import resolution,
dependency-graph construction, community detection, fan-in/fan-out metrics, and entity
fingerprinting/clone-detection band computation (in-memory only). It consumes the
`parsing-extraction` phase's handoff structure (flat `Vec<Entity>`/`Vec<Symbol>` per file,
no pre-built indices) as-is.

## Why
Clone-detection band computation is pure in-memory work consistent with this phase's role as
the last purely in-memory phase before `sqlite-persistence`; only writing bands to disk belongs
to `sqlite-persistence`.

## Constraints
- No dependency from varde-code back onto varde during development.
- Superset parity, verified via coverage-parity checklist, not diffed against TS output.
- Operates entirely on `parsing-extraction`'s extracted entity/symbol data — no re-parsing or
  grammar concerns.
