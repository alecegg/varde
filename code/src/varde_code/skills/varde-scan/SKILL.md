---
name: varde-scan
description: "Use this skill when asked to scan a repository with Varde, interpret scan findings, triage them and record decisions, choose a scan preset, or recover from an incomplete scan or an index readiness problem (index_missing, index_stale)."
requires: [varde-code]
---

# Scan code and triage findings

Run `varde scan` without `--apply` and keep a decision ledger for its findings.

## Outcomes

- The scan ran as `varde scan --json '{"repoRoot":"<repo>",...}'` with exactly one of `severityThreshold` or `gateRules`, and with `fullFindings`.
- The default `severityThreshold` is `error`; `warning` and `info` widen it. If findings are truncated, rerun with `fullFindings` or follow `data.guide.truncated.findings`.
- The scan is certified only when `data.analysis.status` is complete and `data.gate.status` passes; check them independently of top-level `ok`, which only means the command ran. A result can be incomplete even when findings are present.
- Findings are grouped by `rule_id` and each is verified at its source; rule messages and evidence are template text, not proof.
- Confirmed findings are fixed in the local style, then the scan and relevant project checks pass again.
- `--apply` runs only for confirmed safe rewrites after a decision is recorded for every finding; dirty files are skipped unless the user authorized `--force`.
- `varde scan setup` changes rule overrides: inspect the preset and scope before writing; an existing overrides file needs explicit `--force` to replace.

## Recovery

- Diagnostics from an incomplete scan are repaired before the scan is called complete; suppressions do not clear diagnostics.
- Intentionally malformed fixtures are excluded via repository `.ignore` entries and the excluded scope is recorded.
- For `index_missing` or `index_stale`, restore index readiness (scan on the main checkout; workers never build the index). If you cannot restore it, report the scan as unavailable and state the lost capability.
- A per-file quality verdict (from `--vs`, `--changed-since`, or `"verdict": true`) is report-only. It has no finding, gate, or exit-code effect, so do not triage it.

## Severity contract

- **Error:** fix the finding.
- **Warning:** fix it in code you touch; otherwise report it.
- **Info:** use it as context only.

Configured `dependency-boundary` violations are errors by default because they break an explicit architecture decision.

## Decision ledger

Resolve `<working>` once with `varde setup paths --json`; retry once with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.

Keep one line per finding in `<working>/scan/findings.md`, updated by finding ID on a repeat scan (no duplicates):

```text
<id> | <rule_id> | <path>:<line> | <severity> | <disposition>
```

Disposition is `fixed`, `not-real: <reason>`, or `left: <reason>`; keep each reason short and specific.
