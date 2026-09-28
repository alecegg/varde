---
id: decision/rule-rewrite-load-time-validation
status: accepted
type: decision
generated:
  by: human:unspecified
  at: 2026-08-15T09:03:26.366Z
paths: []
enriched_at_commit: null
_version: b595e733db41e22cfc25994739fde71d1ebd88c2737ec15e8e92b41fe9f59a81
---

## What

The `rewrite` field is validated at rule-load time: every `$VAR`/`$$$VAR` token referenced in `rewrite` must appear as a capture in the rule's `pattern`. A rule violating this is rejected at load time (fails rule loading/scan startup), not silently skipped per-match later.

## Why

Catches rule-authoring mistakes immediately rather than producing broken or partial rewrites deep into a scan run. Consistent with the existing per-capture regex constraint validation already present in the rule pipeline (`crates/varde-code/src/rules/pattern.rs`).

## Constraints

Load-time validation is static (token-name comparison against the pattern's declared captures); it does not require running a match.
