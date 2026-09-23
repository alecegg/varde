# Scan and triage

Scan refreshes its index automatically. Choose the gate before interpreting
findings.

```sh
varde-code scan --json '{"repoRoot":"<repo>","severityThreshold":"error"}'
varde-code rules_list --json '{"repoRoot":"<repo>"}'
```

Check top-level `outcome` first. `ok: true` means execution succeeded.
Inspect `data.analysis.status` and `data.gate.status` independently.
Only `gate.status: "pass"` exits zero. A gated finding reports
`outcome: "code-quality-error"`. An incomplete scan reports
`outcome: "analysis-incomplete"` unless a blocking finding also exists.
`data.outcome_reasons` preserves both reasons. Resolve blocking diagnostics
when `analysis.status` is `incomplete`, then group findings by rule ID.
Read each location against its active rule definition before changing code.

The default finding list contains at most 100 entries. Use
`fullFindings: true` for a lossless result. Use `findingsLimit` and
`findingsOffset` for bounded pages. When truncated, follow
`data.guide.truncated.findings.request` or its `next_offset` value. Treat a
truncated list as incomplete evidence.

The default `error` gate uses certified function, file, structural, exact-clone,
and dependency budgets. A function finding needs cognitive > 15, cyclomatic
> 20, or lines > 60. Exact clones require at least three members, at least 20
tokens, and over eight lines. Dependency budgets include fan-out >= 15 with
fan-in <= 2.

`gateRules` selects explicit active IDs. It cannot accompany
`severityThreshold`, and IDs must be unique. `dependency-boundary` requires
both literal directory prefixes before it can be selected. Exactly one blank or
malformed prefix configuration makes the scan incomplete; explicit selection
fails before index writes. Both shipped prefixes are empty, so ordinary scans
leave the rule inactive.

The six informational rules are `vertical-slice-sprawl`,
`churn-complexity-hotspot`, `function-complexity-advisory`, `solid-lsp`,
`solid-isp`, and `console-log-strict`. Selecting `info` includes them in the
severity gate. They require contextual review.

Syntax rules cover 35 declared rule-language pairs. Bare `eval` includes
shadowed calls, `dbg!` matching is bare-only, and handler rules cover listed
known forms. Dependency certification covers relative source paths for
JavaScript, TypeScript, TSX, Dart, and Solidity, plus Go module package units.
Missing imports require explicit recognized source filenames. Extensionless,
ambiguous, alias, and unindexed targets are excluded. Cycles report direct
reciprocal pairs.

Use `.ignore` for intentionally excluded files. Exclusions narrow certified
scope. Suppressions remove findings before counting, but diagnostics remain
visible. `diagnostic_count` includes every normalized diagnostic.
`blocking_diagnostic_count` includes only blockers. Diagnostics expose stable
`kind`, `source`, `message`, `location`, `severity`, and `blocking` fields.
`data.policy` records the mode, active and gating rule counts, source counts,
and its stable fingerprint. Compare this fingerprint across runs.
Use `scan --apply` only for confirmed safe rewrites. Incomplete scans skip
rewrites. Never bypass dirty-file safeguards without approval.
