---
type: reference
description: Built-in scan gate semantics, confidence boundaries, and coverage evidence.
generated: { by: codex/gpt-6, at: 2026-09-22T11:52:42.425553+00:00 }
paths:
  - crates/varde-code/src/scan_cli.rs
  - crates/varde-code/src/rules/builtin
  - crates/varde-code/tests/dependency_policy_gates.rs
  - crates/varde-code/tests/syntax_policy_gates.rs
---

# Built-in quality gates

The built-in pack contains 34 rules: 28 `error` rules and six `info` rules.
`schema_version` is `1`. Top-level `outcome` classifies the caller-visible
result. `ok` describes execution, not whether findings block completion.
`data.analysis.status` and `data.gate.status` report independent states.

The default threshold is `error`. A complete scan passes without unresolved
findings at or above that threshold. `warning` includes warnings. `info`
includes all severities. `gateRules` selects unique active IDs directly and is
mutually exclusive with `severityThreshold`.

`data.gate.status` is `pass`, `fail`, or `unknown`. A gated finding produces
top-level `outcome: "code-quality-error"`. Blocking diagnostics produce
`outcome: "analysis-incomplete"` when no finding blocks first. If both occur,
`data.gate.status` remains `fail` and `data.outcome_reasons` lists both.
Incomplete scans never apply rewrites. Expected unsupported, generated, and
minified skips do not count as gate diagnostics. Other rule, parse, extraction,
traversal, loading, and execution diagnostics do.

`data.gate.diagnostic_count` counts all normalized diagnostics.
`data.gate.blocking_diagnostic_count` counts only blockers. Diagnostics expose
stable `kind`, `source`, `message`, `location`, `severity`, and `blocking`
fields. The `data.policy` object records mode, active and gating rule counts,
source counts, and a stable `fnv1a64` fingerprint.

Findings are limited to 100 by default. `data.findings_summary` reports total,
shown, truncation, rule, severity, and offset counts. Use `fullFindings: true`
for every finding, or use `findingsLimit` and `findingsOffset` for pages.
Truncated results set `meta.truncated` and provide
`data.guide.truncated.findings` recovery fields.

## Certified budgets

High-confidence function metrics gate at cognitive > 15, cyclomatic > 20, or
lines > 60. Certified file complexity gates above total 50 and average 7.
Direct type methods have a maximum of 15. Classes have a maximum of 3 resolved
same-file interfaces. Inheritance depth above 3 is reported as a lower bound.

Exact clone findings require at least 3 members, at least 20 syntax tokens,
and more than 8 lines per member. Clone verification compares source AST leaf
kind and structure. Comments and layout are ignored; literals, operators, and
case remain significant. Bodies are compared when available, otherwise the
whole function is used. Dependency breadth gates at fan-out >= 15 and fan-in
<= 2.

Certified dependency units use relative source paths for JavaScript, TypeScript,
TSX, Dart, and Solidity. Go uses module-aware package-directory units. Missing
facts require explicit recognized source filenames. Extensionless missing
imports, JavaScript aliases, ambiguous targets, and unindexed targets are not
certified. The facts exclude tests, tooling, type-only imports, unsupported
resolver shapes, and non-source assets. Reciprocal cycle checks report direct
mutual pairs only.

`dependency-boundary` uses literal complete directory segments. Both prefixes
must be nonempty for an active policy. Both shipped prefixes are empty, which
leaves ordinary scans inactive. Exactly one blank or malformed prefix produces
an incomplete scan. Explicit selection of an unconfigured boundary is rejected
before index writes.

## Advisory boundaries

The six informational rules are `vertical-slice-sprawl`,
`churn-complexity-hotspot`, `function-complexity-advisory`, `solid-lsp`,
`solid-isp`, and `console-log-strict`. Partial metrics remain advisory.
Churn identifies review priorities. Line counts and name-based resolution do
not establish compiler-level LSP or ISP contracts.

## Syntax coverage

The syntax pack has 35 declared rule-language pairs. Every pair has positive
and negative CLI fixture coverage. Rule listings expose active definitions,
thresholds, languages, exclusions, and provenance. Overrides replace complete
rules by identifier. Suppressions affect findings, never diagnostics.

## Related

- [Scan CLI contract](scan-cli-reference.md)
- [Rule pack format](rule-pack-format.md)
