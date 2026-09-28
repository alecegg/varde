---
type: spec
status: active
title: "SQL-rule execution engine"
related:
  - "reference/rule-pack-format"
  - "reference/pattern-rule-engine"
  - "reference/scan-cli-reference"
---

# SQL-rule execution engine

SQL rules (`kind = "sql"` in a rule pack) query the persisted intelligence
DB from the last `build` and emit `Finding`s per matching row. Execution
runs against an already-open read-only connection — the caller owns opening
(and staleness-checking) it; this engine never opens one itself.

## Parameter binding

A rule's `query` may reference named parameters `:key`, bound from the
rule's `thresholds` (`Option<HashMap<String, f64>>`) and `strings`
(`Option<HashMap<String, String>>`) maps — each map key becomes a `:key`
binding, so `thresholds = { limit = 3.0 }` binds `:limit` as the float
`3.0`. The binding list is built dynamically per rule (the set of params is
rule-defined, not fixed at compile time).

## Result-column convention

A query's result set must select a `file` column and a `line` column: they
populate `Finding.location` (the line becomes the span's start/end line).
Every other selected column becomes a `Finding.evidence` entry keyed by its
column name — self-documenting, no separate JSON-shaping burden on rule
authors. `Finding.agent_instructions` sources from the rule's `fix` field;
`certainty` is always `None` for SQL findings (no ast-grep match-confidence
signal to derive it from).

## Entrypoint

`run_sql_rules(rules: &[Rule], conn: &Connection) -> Result<(Vec<Finding>, Vec<Diagnostic>), ApiError>`

Filters to `kind = sql` internally; pattern rules are silently skipped.
Read-only-ness is enforced at the connection level (`OpenFlags`), never by
inspecting query text.

## Partial failure

A rule that fails — parse-time (invalid SQL syntax) or runtime (query
execution error, e.g. a nonexistent table/column), or whose result set omits
the required `file`/`line` columns — is skip-and-reported as a `Diagnostic`
(rule id populated, human-readable reason) and the pipeline continues with
the remaining rules. An all-failing rules slice therefore yields
`Ok((vec![], diagnostics))`, never `Err`: per-rule failure is not
whole-pipeline failure. Connection-open failures are the caller's `ApiError`
and out of scope here.
