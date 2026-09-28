---
type: spec
status: active
title: "Rule-pack format and loader"
related:
  - "reference/pattern-rule-engine"
  - "reference/sql-rule-engine"
  - "reference/scan-cli-reference"
  - "reference/rule-testing-framework"
---

# Rule-pack format and loader

A rule pack is a TOML file defining scan rules. Built-ins and two filesystem
scopes are parsed into `Rule` values and merged by identifier. Malformed or
duplicate rules never fail the load — each is skipped and reported as a
`Diagnostic` (`rule_id` when determinable, `file`, `reason`).
These diagnostics make the resulting scan gate incomplete.

The embedded built-ins currently contain 34 rules: 28 errors and 6 infos.
Their pattern declarations cover 35 rule/language pairs.

## Rule schema

Each rule is one `[[rule]]` array-of-tables entry. Required fields missing
from a rule make it a skip-and-report error; unrecognized extra fields are
ignored (permissive, forward-compatible).

| Field | Type | Kind | Notes |
|---|---|---|---|
| `id` | string | both | required; unique per scope |
| `kind` | `"pattern"` \| `"sql"` | both | required discriminator |
| `severity` | string | both | required; `"error"` \| `"warning"` \| `"info"` |
| `message` | string | both | required; shown with each finding |
| `verification` | `"exact-clone"` \| `"dependency-facts"` \| `"dependency-boundary"` | SQL only | optional source-aware verification |
| `name` | string | both | optional |
| `description` | string | both | optional |
| `remediation` | string | both | optional |
| `pattern` | string | pattern only | required when `kind = "pattern"`; ast-grep-style pattern (`$VAR`, `$$$VAR`) |
| `query` | string | sql only | required when `kind = "sql"`; SQL against the persisted intelligence DB |
| `thresholds` | table | sql only | optional; each key binds as the named parameter `:key` |
| `strings` | table | sql only | optional; each key binds as the named parameter `:key` |
| `constraints` | table | pattern only | optional; capture name → regex string or nonempty regex array; all constraints must pass |
| `fix` | string | both | optional; suggested-fix template, informational only |

Verification requires a repository root during scans. `exact-clone` reparses
candidate spans and compares canonical syntax trees. Defaults are
`min_tokens = 20`, `min_members = 3`, and `min_span_lines = 8`.
`dependency-facts` uses certified dependency facts. `dependency-boundary` also
requires both `strings.source_prefix` and `strings.target_prefix`, each a
normalized relative directory or `.`. Both blank leaves the policy inactive;
one blank is invalid. Boundary matching uses only explicitly configured,
recognized source and target prefixes. It does not infer a blanket unresolved
dependency prohibition.

Each constraint retains unanchored regex matching.
Anchor whole-capture checks with `^` and `$`.
Prefix each negated constraint with `!`.
Arrays combine constraints with AND semantics.
Empty arrays and invalid regexes produce execution diagnostics.
Existing single-string constraints remain supported.

## Test-case schema

Each rule may carry zero or more `[[rule.test]]` array-of-tables entries — an
inert self-test fixture consumed by the (separate) pattern/SQL test runners,
never by `scan`'s `run_pattern_rules`/`run_sql_rules`. A malformed entry
(missing `name`, a kind-mismatched field, the wrong TOML type, or
`expect_rewrite` on a rule without `rewrite`) is skip-and-report — that one
entry is dropped and reported as a `Diagnostic` (`rule_id` set), while the
rule and its other valid test entries still load.

| Field | Type | Kind | Notes |
|---|---|---|---|
| `name` | string | both | required |
| `valid` | array of strings | pattern only | snippets that must **not** match the rule's `pattern` |
| `invalid` | array of strings | pattern only | snippets that must match the rule's `pattern` |
| `expect_rewrite` | table (string → string) | pattern only | input snippet → expected rewritten output; requires the rule to also define `rewrite` |
| `fixture` | table (string → string) | sql only | inline `[rule.test.fixture]` map of relative path → file content, written to a temp dir and indexed |
| `expect_rows` | array of tables | sql only | expected final verified rows (each an array-of-tables entry under `[[rule.test.expect_rows]]`), compared as an order-insensitive multiset — every expected row must match some actual row and vice versa |

Example fixture/expect_rows shape:

```toml
[[rule.test]]
name = "flags the one over-long function"

[rule.test.fixture]
"lib.rs" = "fn f() {}\nfn g() {}\n"

[[rule.test.expect_rows]]
file = "lib.rs"
line = 1
```

## Discovery

The persisted `resolved_edges` and `clone_bands` tables are approximate
signals. Dependency-verification rules use the scan-local
`temp.dependency_facts` table, prepared only when an active rule uses
`dependency-facts` or `dependency-boundary`.
It contains `from_file_id`, `from_unit`, `to_file_id`, `to_unit`, `kind`,
`certainty`, `source_entity_id`, and `specifier`. `certainty = 'certified'`
means source and indexed targets agree; `certainty = 'missing'` means a
recognized local target is absent. The table is recreated for each scan and
never alters the index schema. Relative JS, TS, TSX, Dart, and
Solidity imports require one matching physical and indexed target. Go uses
resolved module-aware edges plus a physical target check. Test, tooling,
type-only, and ambiguous loader imports are excluded.

For `exact-clone`, the SQL query must return valid indexed function spans:
`file`, `line`, `start_byte`, `end_byte`, `end_line`, and optional
`start_col`/`end_col`. Columns populate the finding span, not evidence. The
verifier reparses candidates and returns only final verified rows.

Exact-clone candidates need `token_count >= 20`, at least 3 verified members,
and `end_line - start_line >= 8`, which spans at least 9 inclusive lines.

Two scopes are searched, in this order:

- User scope: `~/.config/varde-code/rules/` (overridable via the
  `VARDE_USER_RULES_DIR` environment variable)
- Repo scope: `<repo_root>/.varde-code/rules/`

Within each scope every `*.toml` file is loaded, sorted by path for
deterministic ordering. A missing scope directory contributes zero files and
is not an error. Other directory discovery failures produce diagnostics.

## Merge

Rules are merged by `id`, in deterministic discovery order.
Repository rules replace user rules, which replace built-ins.
Overrides replace whole definitions, not individual fields:

- Cross-scope conflict (same id in user and repo scope): the **repo-scoped**
  rule wins, silently — expected behavior, not a diagnostic.
- Same-scope conflict (duplicate id within one scope): the **first-loaded**
  rule wins; each later duplicate is skipped and reported as a `Diagnostic`
  naming the duplicate's source file.

Downstream consumers filter the merged `Vec<Rule>` by `kind` themselves;
`load_rules` returns both the merged rules and the accumulated diagnostics.
