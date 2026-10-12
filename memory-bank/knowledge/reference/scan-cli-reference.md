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
varde scan --json '{"repoRoot":".","severityThreshold":"error"}'
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
varde scan rules seed --json '{"repoRoot":"."}'
# Edit .varde-code/rules/dependency_boundary.toml:
# Replace its strings table with:
# strings = { source_prefix = "src/core", target_prefix = "src/data" }
varde scan --json '{"repoRoot":".","gateRules":["dependency-boundary"]}'
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

The built-in pack has 127 rules: 102 errors, 19 warnings, and six informational
advisories. At the default `error` threshold, credential, eval, empty-handler,
swallow, unresolved-import, circular-import, and configured dependency-boundary
findings block. Certified budget, clone, and fan-in/fan-out findings are warnings; partial
metrics and other advisory rules remain informational. Certified function
complexity warns above cognitive 15 or cyclomatic 20. A **certified
function-complexity language** is one whose conformance suite passes in CI;
this definition applies only to function complexity. A function over 60 lines
with both metrics in bounds also warns. Exact clone warnings require 3 members,
at least 20 tokens, and more than 8 lines per member. Dependency breadth warns
at fan-out >= 15 and fan-in <= 2.

Certified dependency paths cover all 21 extraction languages. JavaScript,
TypeScript, TSX, Dart, Solidity, Rust, Python, C, C++, Ruby, PHP, Lua, Bash,
Elixir and Haskell use file units; Go and Java/Kotlin/Scala use directory
units; C# uses the nearest `.csproj` and Swift a `Sources/<Target>` directory
or an Xcode `PBXNativeTarget`. Missing imports require explicit recognized
source filenames; extensionless paths, package aliases, ambiguous targets, and
unindexed targets are excluded. C and C++ certify `missing` only for `./` and
`../` specifiers; C# and Swift emit no `missing` facts, and Rust facts are
certified only across Cargo packages. Reciprocal cycles are direct only.
Syntax rules cover 127 declared rule-language pairs. Bare `eval` includes
shadowed calls, `dbg!` matching is bare-only, and handler rules cover listed
known forms.

The six info rules are `vertical-slice-sprawl`, `churn-complexity-hotspot`,
`function-complexity-advisory`, `solid-lsp`, `solid-isp`, and
`console-log-strict`. Selecting `info` includes them in the severity gate.

## Customization

`rules_list` exposes merged definitions and provenance without requiring
an index. Each rule includes `severitySource` (`builtin`, `user-rule`,
`repo-rule`, `user-override`, or `repo-override`) and a `drifted` boolean.
Rules disabled by an `off` override remain in the list with `severity: "off"`
and `disabled: true`; scans and gates omit them.
The top-level `orphanedOverrides` array lists override IDs that are absent from
the active built-in and rule-pack set. Repository definitions replace matching
user and built-in IDs; severity overrides are applied after those definitions.

`rules_seed` creates editable repository copies. Add `--rule-id <id>` to seed
only the built-in pack containing that ID. With `--force`, only that pack is
refreshed. `varde scan rules diff <id>` shows the pack defining that rule
against the current built-in and reports `seedScope` (`repo` or `user`). A
drifted repository pack is refreshed with:

```sh
varde scan rules seed --json '{"repoRoot":"."}' --force --rule-id <id>
```

Add `--user` when `seedScope` is `user`.

Severity overrides are stored in repo scope at
`<repoRoot>/.varde-code/overrides.toml` or user scope at
`<varde config root>/code/overrides.toml`. Repo overrides win over user
overrides, then rule-file severity wins over built-in severity. Use
`severity = "off"` in `[rules.<id>]` to remove that rule from scans and gate
selection; selecting an off rule through `gateRules` returns `invalid_input`.

Parser-recognized `varde-ignore-file` and `varde-ignore-next-line` comments
suppress matching IDs before gate evaluation. Generated and vendored findings
are filtered automatically. `--apply` writes only explicit pattern rewrites.
Incomplete scans skip rewrites. `--force` permits writes to dirty files.

For thresholds and applicability, read [builtin-quality-gates.md](builtin-quality-gates.md).
