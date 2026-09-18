# Scan and triage

Treat scan findings as candidates requiring classification.
Every finding becomes either real or not real.

1. Build a fresh index when source changed.
2. Run `varde-code scan` without `--apply`.
3. Group findings by rule identifier.
4. Read each reported source location directly.
5. Record every verdict with one concise reason.
6. Fix real findings using normal change safeguards.
7. Re-run scans and relevant project tests.

```bash
varde-code build --json '{"repoRoot":"<repo>"}'
varde-code scan --json '{"repoRoot":"<repo>"}'
```

Read the rule definition before judging uncertain findings.
Messages and evidence are hints, never final proof.

Use `scan --apply` only for confirmed safe rewrites.
Never bypass dirty-tree safeguards without explicit user approval.
