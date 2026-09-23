---
id: decision/rule-rewrite-capture-data-already-available
status: accepted
type: decision
generated:
  by: human:unspecified
  at: 2026-08-15T09:03:25.813Z
paths: []
enriched_at_commit: null
_version: 431239b37c636fa032038cff4bff6f4bece66499ce4358a53379f93f9ec02323
---

## What

Pattern-rule matches already expose a full `captures` map (name → matched node's kind/text/span) by the time a `Finding` is constructed — see `crates/varde-code/src/query/find_pattern.rs` (`match_file`, `collect_captures`, `bind_sequence`) and `crates/varde-code/src/rules/finding.rs` (`match_to_finding`, which copies `captures` into `Finding.evidence`). This data is not yet interpolated into any output string, but is fully accessible at the finding-construction boundary.

## Why

Confirms the `rewrite` field (decided in `rule-rewrite-field-separate-from-fix`) can be implemented as string interpolation over the existing `captures` map at or near `match_to_finding` — no new capture-plumbing is needed through the matcher itself.

## Constraints

Implementation should interpolate `rewrite` template `$VAR`/`$$$VAR` tokens against `Finding.evidence` (or the pre-finding `captures` map) using the same binding semantics already proven by the `two_meta_variables_in_one_statement_bind_separately` test.
