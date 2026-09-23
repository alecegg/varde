---
id: decision/rule-autofix-scoped-to-pattern-rules
status: accepted
type: decision
generated:
  by: human:unspecified
  at: 2026-08-15T09:03:25.491Z
paths: []
enriched_at_commit: null
_version: 2a5060b81f0a1e12b11b74d29330f6e48ef2935d2843840d654ec55007f33bc3
---

## What

Automated rewrite ("autofix") applies only to pattern rules (AST-based `find_pattern` matches). SQL rules keep their existing `fix` field as remediation-guidance text for an agent, unchanged — they do not gain mechanical rewrite.

## Why

Pattern rules match a specific AST node/span with captured meta-variables, so a meta-variable-substituted replacement is well-defined. SQL rules query the persisted graph and aren't anchored to a single source span in the same way, so a mechanical rewrite target isn't well-defined for them without new plumbing that's out of scope here.

## Constraints

None yet — deferred to the plan's implementation.
