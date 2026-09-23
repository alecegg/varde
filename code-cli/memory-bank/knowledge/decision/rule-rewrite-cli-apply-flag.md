---
id: decision/rule-rewrite-cli-apply-flag
status: accepted
type: decision
generated:
  by: human:unspecified
  at: 2026-08-15T09:03:25.881Z
paths: []
enriched_at_commit: null
_version: d1e0af5d1e26d8a06a694747d7e6a56bec1e8fc4f865c3bb89826261cd6da4a2
---

## What

The scan CLI gains an `--apply` flag that writes `rewrite`-substituted replacements to disk for matched pattern rules. Default behavior (no flag) is unchanged: report matches only, no file mutation.

## Why

Keeps today's read-only default behavior stable and follows least-surprise: file mutation must be explicitly opted into, not triggered implicitly by a rule having a `rewrite` field.

## Constraints

None yet — deferred to the plan's implementation.
