---
topic: varde-scan/quality-verdict
version: 1
summary: What triggers the per-file quality verdict and how to view one file
---

With `--vs {repo,generic,mine}`, `--changed-since`, or `"verdict": true`, scan adds a per-file `quality_verdict` (reference header plus a `fixes` list; `varde code score --file F --vs ...` shows one file as text). `--changed-since` also limits quality floor and cap findings to changed files. A verdict is advisory and report-only for all languages for now: no finding, gate, or exit-code effect, so do not triage it.
