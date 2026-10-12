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

The built-in pack contains 127 rules: 102 `error` rules, 19 `warning` rules,
and six `info` rules.
`schema_version` is `1`. Top-level `outcome` classifies the caller-visible
result. `ok` describes execution, not whether findings block completion.
`data.analysis.status` and `data.gate.status` report independent states.

The default threshold is `error`. Certified budget rules are warning-level,
so they do not block that default threshold. A complete scan
passes without unresolved findings at or above the threshold. `warning`
includes warnings. `info` includes all severities. `gateRules` selects unique
active IDs directly and is mutually exclusive with `severityThreshold`.

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

## Warning-level budgets and policies

High-confidence function complexity findings warn above cognitive 15 or
cyclomatic 20. A function over 60 lines with both complexity metrics within
those limits also warns. A **certified function-complexity language** is one
whose conformance suite passes in CI; this definition applies only to function
complexity. Certified file complexity findings warn above total 50 and average
7.
More than 15 direct type methods, more than 3 resolved same-file interfaces,
and inheritance depth above 3 also produce warning-level findings. Inheritance
depth is reported as a lower bound.

Exact clone warnings require at least 3 members, at least 20 syntax tokens,
and more than 8 lines per member. Clone verification compares source AST leaf
kind and structure. Comments and layout are ignored; literals, operators, and
case remain significant. Bodies are compared when available, otherwise the
whole function is used. Dependency breadth warns at fan-out >= 15 and fan-in
<= 2.

Certified dependency units use file units for JavaScript, TypeScript, TSX,
Dart, Solidity, Rust, Python, C, C++, Ruby, PHP, Lua, Bash, Elixir and
Haskell; directory units for Go and Java/Kotlin/Scala; the nearest `.csproj`
for C#, and a `Sources/<Target>` directory or an Xcode `PBXNativeTarget` for
Swift. Missing facts require explicit recognized source filenames.
Extensionless missing imports, JavaScript aliases, ambiguous targets, and
unindexed targets are not certified. C and C++ certify `missing` only for `./`
and `../` specifiers; C# and Swift emit no `missing` facts, and Rust facts are
certified only across Cargo packages. The facts exclude tests, tooling,
type-only imports, unsupported resolver shapes, and non-source assets.
Reciprocal cycle checks report direct mutual pairs only.

`dependency-boundary` uses literal complete directory segments. It defaults to
`error` because a configured boundary represents an explicit architecture
decision. Both prefixes must be nonempty for an active policy. Both shipped
prefixes are empty, which leaves ordinary scans inactive. Exactly one blank or
malformed prefix produces an incomplete scan. Explicit selection of an
unconfigured boundary is rejected before index writes.

## Advisory boundaries

The six informational rules are `vertical-slice-sprawl`,
`churn-complexity-hotspot`, `function-complexity-advisory`, `solid-lsp`,
`solid-isp`, and `console-log-strict`. Partial metrics remain advisory.
Churn identifies review priorities. Line counts and name-based resolution do
not establish compiler-level LSP or ISP contracts.

## Syntax coverage

The syntax pack has 127 declared rule-language pairs. Every pair has positive
and negative CLI fixture coverage. Rule listings expose active definitions,
thresholds, languages, exclusions, and provenance. Overrides replace complete
rules by identifier. Suppressions affect findings, never diagnostics.

## Related

- [Scan CLI contract](scan-cli-reference.md)
- [Rule pack format](rule-pack-format.md)
