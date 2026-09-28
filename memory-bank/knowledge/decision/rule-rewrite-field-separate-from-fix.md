---
id: decision/rule-rewrite-field-separate-from-fix
status: accepted
type: decision
generated:
  by: human:unspecified
  at: 2026-08-15T09:03:25.944Z
paths: []
enriched_at_commit: null
_version: 71a547e95dc39f0864655e3325afdcf615cf65815c21d6cdc001d26e4bb104dc
---

## What

The mechanical, meta-variable-substituted rewrite template lives in a new `rewrite` field on pattern rules. The existing `fix` field is unchanged — it remains free-text remediation guidance for an agent. Both fields can coexist on the same rule.

## Why

Repurposing `fix` to hold a rewrite template would silently reinterpret every existing TOML rule's free-text guidance as a rewrite template, a breaking and ambiguous change. `rewrite` is also the term ast-grep itself uses for this mechanism, keeping vocabulary aligned with the benchmark tool.

## Constraints

None yet — deferred to the plan's implementation.
