---
id: decision/rule-rewrite-overlap-handling
status: accepted
type: decision
generated:
  by: human:unspecified
  at: 2026-08-15T09:03:26.540Z
paths: []
enriched_at_commit: null
_version: 6c76d201e63595768ad5835c80a8192d6d5c47803ca0457f344c3504af8efce6
---

## What

When `--apply` produces multiple rewrite matches in the same file (from one rule or several), matches are applied in a single pass per file, sorted by span. A match whose span overlaps one already applied is skipped and reported (not applied, not a crash).

## Why

Applying overlapping spans naively would corrupt the file via double/conflicting writes over the same text region. Sorting and skipping overlaps in one pass avoids this without requiring expensive re-parse-and-rematch cycles. Matches ast-grep's own conflict-avoidance approach.

## Constraints

"Skipped" matches must still surface in `--apply` output (e.g. a distinct status/count) so the user knows a conflict occurred rather than silently dropping the fix.
