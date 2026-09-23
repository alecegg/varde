---
type: spec
status: active
title: "Pattern-rule execution engine"
related:
  - "reference/rule-pack-format"
  - "reference/sql-rule-engine"
  - "reference/scan-cli-reference"
---

# Pattern-rule execution engine

Pattern rules (`kind = "pattern"` in a rule pack) match source at scan time
using find_pattern's ast-grep matcher, filter matches by per-capture regex
constraints, correlate each surviving match against its enclosing persisted
function/method entity, and emit `Finding`s.

## Matching

The matcher is find_pattern's own (reused unchanged): flat `$VAR` /
`$$$VAR` metavariable matching, one pattern parse per rule + language, and a
parallel per-file walk. The pattern runs against every file of the target
language(s) in the repo.

## Language scoping

A rule's `languages` field (`Option<Vec<String>>`, e.g.
`languages = ["typescript", "javascript"]`) restricts the rule to those
languages. When `languages` is `None` (or empty) the rule runs against every
file whose parse succeeds — the language-agnostic default. A pattern that
fails to parse in a language it was never written for is skipped silently;
only a pattern that fails in every tried language is reported as a broken
rule.

## Constraints

`constraints` is a map of capture name → regex, ast-grep's per-metavariable
`constraints` convention:

```toml
constraints = { VAR = "^[A-Z]" }
```

A match survives only if every named constraint's regex matches its
capture's text (AND semantics); a capture named in the map but absent from
the match drops it. `$$$VAR` variadic captures bind an array of nodes — the
regex applies to the full joined text. An invalid regex is an `ApiError`,
not a panic.

## Relational context: `is_async` correlation

A match's file + byte span is looked up against persisted `entities` rows to
find the narrowest enclosing function/method entity (nested functions
resolve to the innermost). The entity's structural-fact columns are read
from that row; today that is `is_async` (whether the enclosing function
carries its language's async modifier — `async fn`, `async function`,
`async def`, C# `async`, Kotlin `suspend`). The fact rides on the finding's
`evidence.enclosing_function` as `{ "name", "is_async" }`.

## Findings

`Finding` adopts varde's `ScanFinding` shape. Fields: `id` (deterministic —
stable hash of rule id + file + span, identical across repeated scans of an
unchanged repo), `rule_id`, `severity`, `message`, `location` (file + byte/
line span), `evidence` (the match's `captures` map verbatim), `remediation`,
`certainty` (`High` for pattern matches — SQL findings always `None`), and
`agent_instructions` (sourced from the rule's `fix` field when present).

## Entrypoint

`run_pattern_rules(rules: &[Rule], repo_root: &Path, conn: &Connection) -> Result<(Vec<Finding>, Vec<Diagnostic>), ApiError>`

Filters to `kind = pattern` internally. Per-rule failures (bad pattern
syntax, unsupported language name, invalid constraint regex) are
skip-and-reported as `Diagnostic`s and the pipeline continues. A DB-level
failure (absent/unopenable/missing schema — the correlation's read source)
is a whole-pipeline `ApiError`, not a per-rule diagnostic.
