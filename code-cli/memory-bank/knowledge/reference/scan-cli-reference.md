---
type: spec
status: active
title: "scan CLI reference"
related:
  - "reference/rule-pack-format"
  - "reference/pattern-rule-engine"
  - "reference/sql-rule-engine"
---

# scan CLI reference

Scan evaluates built-in, user, and repository rules. It refreshes the index
automatically before running them.

## Invocation

```sh
varde-code scan --json '{"repoRoot":".","severityThreshold":"error"}'
```

`repoRoot` is required. `severityThreshold` accepts `error`, `warning`, or
`info`, case-insensitive, and defaults to `error`. `gateRules` accepts a
nonempty array of unique active rule IDs. It cannot accompany
`severityThreshold`. `apply` and `force` are optional booleans, defaulting to
false. `output` is an optional string path for the envelope instead of stdout.
`fullFindings` is an optional boolean and defaults to false.
`findingsLimit` defaults to 100. `findingsOffset` defaults to zero.

`dependency-boundary` needs nonempty `source_prefix` and `target_prefix`
configuration. Its two shipped empty prefixes leave ordinary scans inactive.
Exactly one blank or malformed prefix makes the scan incomplete. Explicit
selection of an inactive or invalid boundary is rejected before index writes.

```sh
varde-code rules_seed --json '{"repoRoot":"."}'
# Edit .varde-code/rules/dependency_boundary.toml:
# Replace its strings table with:
# strings = { source_prefix = "src/core", target_prefix = "src/data" }
varde-code scan --json '{"repoRoot":".","gateRules":["dependency-boundary"]}'
```

Seeded files are whole-rule overrides and remain active until removed.

## Result and exit status

The envelope contains `schema_version`, `ok`, `outcome`, `data`, and `meta`.
`schema_version` is currently `1`. `ok` reports execution only. A successful
scan includes `findings`, `findings_summary`, `diagnostics`, `analysis`,
`gate`, and `policy`. A fired-rule legend appears only when findings remain.

`data.analysis.status` is `complete` or `incomplete`.
`data.gate.status` is `pass`, `fail`, or `unknown`. `pass` exits zero.
`fail` means unresolved findings meet the chosen gate policy.
`unknown` means blocking diagnostics prevent a gate decision.
Operation failures use `ok: false`, `outcome: "tool-error"`, and exit nonzero.
Gated findings use top-level `outcome: "code-quality-error"`.
Incomplete analysis uses `outcome: "analysis-incomplete"` unless a blocking
finding also exists. `data.outcome_reasons` preserves both reasons.
`data.outcome` mirrors the top-level scan outcome for library consumers.

Gate details include `severity_threshold`, `blocking_findings`,
`diagnostic_count`, and `blocking_diagnostic_count`. The first counts every
normalized diagnostic. The second counts only blockers. Each diagnostic adds
`kind`, `source`, `message`, `location`, `severity`, and `blocking` fields.
Explicit `gateRules` also returns `rule_ids` and a null `severity_threshold`.
Applied rewrites no longer block. Skipped rewrites do.

The `policy` object reports `mode`, `active_rule_count`, `gating_rule_count`,
`severity_threshold`, `sources`, and a stable `fnv1a64` `fingerprint`. Selected
rule mode is `selected-rules`; threshold mode is `severity-threshold`.

The default findings list is bounded at 100 entries. `findings_summary` reports
`total`, `shown`, `truncated`, `by_rule`, `by_severity`, and `offset`.
`fullFindings: true` returns all findings. Truncated results set
`meta.truncated: true` and include `data.guide.truncated.findings` with
`shown`, `total`, `offset`, `limit`, `next_offset`, and `request` recovery
fields. Consumers must not treat truncated findings as complete.

Expected unsupported, generated, and minified skips are omitted. Other rule or
source diagnostics block the gate. Suppressions remove findings before gate
counting, but never dismiss diagnostics.

## Built-in coverage

The built-in pack has 34 rules: 28 errors and six informational advisories.
The default error gate covers certified function and file budgets, structural
budgets, exact clones, and dependency policies. A function finding needs
cognitive > 15, cyclomatic > 20, or lines > 60. Exact clones require 3
members, at least 20 tokens, and more than 8 lines per member. Dependency breadth uses
fan-out >= 15 and fan-in <= 2.

Certified dependency paths cover JavaScript, TypeScript, TSX, Dart, and
Solidity relative imports. Go uses module package-directory units. Missing
imports require explicit recognized source filenames; missing extensionless paths,
package aliases, ambiguous targets, and unindexed targets are excluded. Reciprocal cycles are direct
only. Syntax rules cover 35 declared rule-language pairs. Bare `eval` includes
shadowed calls, `dbg!` matching is bare-only, and handler rules cover listed
known forms.

The six info rules are `vertical-slice-sprawl`, `churn-complexity-hotspot`,
`function-complexity-advisory`, `solid-lsp`, `solid-isp`, and
`console-log-strict`. Selecting `info` includes them in the severity gate.

## Customization

`rules_list` exposes active merged definitions and provenance without requiring
an index. Repository definitions replace matching user and built-in IDs.
`rules_seed` creates editable repository copies.

Parser-recognized `varde-ignore-file` and `varde-ignore-next-line` comments
suppress matching IDs before gate evaluation. Generated and vendored findings
are filtered automatically. `--apply` writes only explicit pattern rewrites.
Incomplete scans skip rewrites. `--force` permits writes to dirty files.

For thresholds and applicability, read [builtin-quality-gates.md](builtin-quality-gates.md).
