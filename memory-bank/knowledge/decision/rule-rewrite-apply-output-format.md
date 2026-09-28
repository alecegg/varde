---
id: decision/rule-rewrite-apply-output-format
status: accepted
type: decision
generated:
  by: human:unspecified
  at: 2026-08-15T09:03:25.769Z
paths: []
enriched_at_commit: null
_version: 25dbf58e4a497f4f35e9790b529dfab8c50ba1df9d4cc7e120cf602e0f5f00c0
---

## What

`--apply` reuses the existing scan JSON envelope. Each finding gains a `rewrite_status` field (`applied`, `skipped-dirty`, `skipped-overlap`, `skipped-conflict`), plus a top-level summary count of each status. Exit code stays consistent with existing severity-gating rules — non-zero if any error-severity finding remains unapplied/unresolved after the run.

## Why

Keeps one consistent JSON shape and CI exit-code contract instead of introducing a second schema to maintain alongside the existing scan output.

## Constraints

`rewrite_status` is only present on findings from pattern rules with a `rewrite` field; findings without an applicable rewrite (SQL rules, or pattern rules without `rewrite`) omit the field entirely rather than setting it to a placeholder value.
