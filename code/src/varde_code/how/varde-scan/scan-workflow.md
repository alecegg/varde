---
topic: varde-scan/scan-workflow
version: 1
summary: Run the scan, read its status fields, triage, fix and record
---

1. Run the scan without `--apply`:

   ```sh
   varde scan --json '{"repoRoot":"<repo>","severityThreshold":"error","fullFindings":true}'
   ```

   - Use `warning` to include warnings and `info` to include informational rules.
   - Set either `severityThreshold` or `gateRules`, not both.
   - For a truncated result, request all findings or follow `data.guide.truncated.findings`.
2. Read the result: check top-level `outcome` and `ok`, plus `data.analysis.status` and `data.gate.status` independently. Certify the scan only when analysis is complete and the gate passes.
3. Triage: group findings by `rule_id` and inspect each active rule and source location. Treat messages and evidence as rule-template text, not proof. Apply the severity contract.
4. Fix: fix confirmed findings in the local style, then rerun the scan and relevant project checks. Use `--apply` only for confirmed safe rewrites after recording a decision for every finding. Dirty files are skipped unless the user has authorized `--force`.
5. Record decisions in the findings ledger.
