---
name: varde-scan
description: "Run a Varde code scan, understand its findings, and record triage decisions. Use when asked to scan a repository, interpret scan output, or resolve an index readiness problem. Not for authoring scan rules (varde-customize) or reviewing a code change (varde-review)."
requires: [varde-code]
---

# Scan code and triage findings

Run `varde scan` and keep a decision ledger for its findings. When choosing a
preset or handling incomplete-scan recovery, read `references/scan.md`.

## Workflow

1. **Run the scan without `--apply`:**

   ```sh
   varde scan --json '{"repoRoot":"<repo>","severityThreshold":"error","fullFindings":true}'
   ```

   - Use `warning` to include warnings and `info` to include informational
     rules.
   - Set either `severityThreshold` or `gateRules`, not both.
   - For a truncated result, request all findings or follow
     `data.guide.truncated.findings`.
2. **Read the result.**
   - Check top-level `outcome` and `ok`, plus
     `data.analysis.status` and `data.gate.status` independently.
   - Certify the scan only when analysis is complete and the gate passes.
3. **Triage and verify**
   - Group findings by `rule_id` and inspect each active rule and source
     location. Treat messages and evidence as rule-template text, not proof.
   - Apply the severity contract below.
4. **Fix and verify**
   - Fix confirmed findings in the local style, then rerun the scan and
     relevant project checks.
   - Use `--apply` only for confirmed safe rewrites after recording a decision
     for every finding. Dirty files are skipped unless the user has authorized
     `--force`.
5. **Record decisions.** Use the findings format below.

## Severity contract

- **Error:** fix the finding.
- **Warning:** fix it in code you touch; otherwise report it.
- **Info:** use it as context only.

By default, configured `dependency-boundary` violations are errors because they
break an explicit architecture decision.

## Findings and persistence

Record one line per finding as:

```text
<id> | <rule_id> | <path>:<line> | <severity> | <disposition>
```

Choose one disposition:

- `fixed`
- `not-real: <reason>`
- `left: <reason>`

Resolve `<working>` and `<knowledge>` once with `varde setup paths --json`; retry once with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.

- Append or update `<working>/scan/findings.md`.
- On a repeat scan, update the matching finding by ID instead of adding a
  duplicate.
- Keep each reason short and specific.

## Gotchas

- `ok: true` means the command ran; check analysis and gate status separately.
- A scan result can be incomplete even when findings are present.
- `varde scan setup` changes rule overrides. Inspect the preset and scope
  before using it.
