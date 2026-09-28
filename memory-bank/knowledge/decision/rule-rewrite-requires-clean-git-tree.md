---
id: decision/rule-rewrite-requires-clean-git-tree
status: accepted
type: decision
generated:
  by: human:unspecified
  at: 2026-08-15T09:03:26.645Z
paths: []
enriched_at_commit: null
_version: 3cc4de3464ea090d1719e73a3bb418296e7f2081bd5458b94b106a2e6e2a2fbf
---

## What

`--apply` checks each target file's git status before writing. A file with uncommitted changes is skipped (warned, not applied) unless `--force` is also passed.

## Why

Bulk mechanical rewrites are a hard-to-reverse, high-blast-radius action. Requiring a clean tree lets git serve as the undo mechanism (`git diff`/`git checkout`) without varde-code needing to implement its own backup/undo system, while `--force` remains an explicit escape hatch for users who accept the risk.

## Constraints

The check is per-file (git status of that specific path), not a whole-repo clean-tree requirement — files outside the dirty set should still be eligible for `--apply`.
