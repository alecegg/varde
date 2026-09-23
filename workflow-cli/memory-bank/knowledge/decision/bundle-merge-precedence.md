---
id: decision/bundle-merge-precedence
type: decision
status: accepted
generated:
  by: human:unspecified
  at: 2026-08-13T20:30:17.834Z
verified: []
paths: []
enriched_at_commit: null
_version: 3cf4d30acb78802a5b0bb7a6e82e45d3c148eb06c3d38ac820e8ae7f2c9ccd62
---

## What

When a Concept with the same slug exists in both the Personal Vault and
the current Project Vault, the Project Vault's Concept wins at recall
time.

## Why

Matches typical config-layering conventions (project-local overrides
user-global). Project-scoped knowledge is more specific to the task at
hand than a cross-project default.

## Constraints

- This is silent override, not a flagged conflict — distinct from the
  contradiction-lint check, which targets semantic contradictions
  between Concepts' content, not same-slug collisions across bundle
  scope.
