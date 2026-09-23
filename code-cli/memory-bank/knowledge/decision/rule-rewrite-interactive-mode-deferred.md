---
id: decision/rule-rewrite-interactive-mode-deferred
status: accepted
type: decision
generated:
  by: human:unspecified
  at: 2026-08-15T09:03:26.048Z
paths: []
enriched_at_commit: null
_version: 2a2903a4ff85812bca890458d007cbf2f27895c3782599ff42f29a33eca012fa
---

## What

Per-match interactive confirm mode (`--interactive`, reviewing/accepting each match's diff one at a time, like `sg run --interactive`) is out of scope for the `rule-autofix-rewrite` plan. It is tracked as a separate draft plan to build on top of the `rewrite`/`--apply` engine once that lands.

## Why

Interactive terminal UX (diff rendering, keypress handling, per-match confirm loop) is a distinct chunk of work from the rewrite engine itself. Shipping `--apply` (apply-all) first delivers value sooner without blocking on interactive UX design.

## Constraints

Depends on the `rewrite` field and rewrite-substitution engine from `rule-autofix-rewrite` landing first.
