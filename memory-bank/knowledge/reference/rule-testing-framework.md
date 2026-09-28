---
type: spec
status: active
title: "Rule testing framework"
related:
  - "reference/rule-pack-format"
  - "reference/rule-rewrite-autofix"
---

# Rule testing framework

Rule packs carry inline self-tests as `[[rule.test]]` array-of-tables
entries, sibling to `id`/`pattern`/`query`/`rewrite` on each rule. Test
entries are inert to `scan` — never consumed by `run_pattern_rules` or
`run_sql_rules` — and are read only by the dedicated `varde-code test`
subcommand.

## `[[test]]` field table

| Field | Type | Kind | Notes |
|---|---|---|---|
| `name` | string | both | required; identifies the test in output |
| `valid` | array of strings | pattern only | snippets expected to produce zero matches |
| `invalid` | array of strings | pattern only | snippets expected to produce ≥1 match |
| `expect_rewrite` | table (snippet → expected output) | pattern + rewrite only | asserts exact rewritten source per invalid snippet; requires the rule to also define `rewrite` |
| `fixture` | table (relative path → file content) | sql only | files written to a temp dir and indexed |
| `expect_rows` | array of tables | sql only | expected query result rows |

A malformed entry — missing `name`, a kind-mismatched field, the wrong TOML
type, or `expect_rewrite` on a rule without `rewrite` — is skip-and-report:
that one entry is dropped and reported as a `Diagnostic` naming the rule,
while the rule and its other valid test entries still load. See
[[reference/rule-pack-format]] for the full rule schema and the loader's
general skip-and-report convention for malformed rules.

### `expect_rows` comparison is order-insensitive

`expect_rows` is compared against the SQL rule's actual query result rows as
a multiset, not a sequence: every expected row must match some actual row
and every actual row must match some expected row, regardless of order. An
extra actual row or a missing expected row fails the test; row order never
matters. This matches SQL rules' lack of a guaranteed row order absent an
explicit `ORDER BY`.

## Test execution model

- Pattern-rule tests run `valid`/`invalid` snippets through the same
  `find_pattern` + constraint-application path `scan` uses, then compare
  match counts against the expected zero/nonzero outcome. `expect_rewrite`
  entries additionally run the rule's `rewrite` template through the same
  substitution logic `scan --apply` uses and compare the exact rewritten
  output string.
- SQL-rule tests write the `fixture` map to a temp directory (relative path
  → file content), index that directory through the real intelligence
  pipeline, run the rule's `query` against the resulting database, and
  compare the result rows against `expect_rows` as described above.

## `varde-code test` CLI

```text
varde-code test --json '{"rulesDir"?: string}'
```

- `rulesDir` is optional. When given, it scopes discovery to the TOML pack
  files directly inside that directory — no user/repo-scope merge, no
  built-in rules — for testing a single pack in isolation. When omitted,
  rule discovery mirrors `scan`'s normal `load_rules` resolution, using the
  process's current working directory as the repo root.
- No `repoRoot` is required or accepted — tests are self-contained and need
  no prior `build`/index step of their own beyond what SQL-rule tests set
  up internally per test case.

### Output envelope

```json
{
  "ok": true,
  "data": {
    "results": [
      {
        "rule_id": "no-console-log",
        "test_name": "flags console.log",
        "status": "pass",
        "detail": "optional, present only on fail"
      }
    ],
    "summary": { "passed": 1, "failed": 0 },
    "diagnostics": []
  }
}
```

- `results` has one entry per `[[test]]` case across every rule that
  carries at least one test entry; `detail` is present only when `status`
  is `"fail"`.
- `summary` counts passed/failed test cases across all rules.
- `diagnostics` surfaces loader diagnostics — including skip-and-report
  entries for malformed `[[test]]` cases — in the same shape `scan`
  surfaces its own loader diagnostics.
- A rule set with zero test-bearing rules is not an error: `results` is an
  empty array and `summary` is `{"passed": 0, "failed": 0}`.

### Exit code

`varde-code test` exits `0` if and only if `summary.failed == 0`. It exits
non-zero when any test case fails, and also when the invocation itself
fails — malformed input JSON or an invalid `rulesDir` — so a CI gate can
treat any non-zero exit as "tests did not pass" without inspecting the
envelope.
