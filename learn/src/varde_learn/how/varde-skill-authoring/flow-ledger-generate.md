---
topic: varde-skill-authoring/flow-ledger-generate
version: 1
summary: Flow ledger generate - second after choice; fails and stops after two bad validations, estimates
---

## Generate

1. Pick the source root, revision, entry files, and route. For a read-only or other-revision repo, export it first: `git -C <repo> archive <rev> | tar -x -C "$TMPDIR/<name>"`, and pass that directory as `--root` to every ledger command.
2. Fill `assets/flow-ledger-prompt.md` and dispatch one auditor subagent in the current harness with it. Do not edit its counting rules.
3. Run `ledger hash` on the output, then `ledger validate`. A failure other than a hash is the auditor's to fix: send the printed problems back once. If the second attempt still fails, report the problems and stop.
4. Run `ledger score` and report totals with the route and auditor model, labeled as estimates. `validate` checks structure, not completeness; paired audits have differed by up to 19%. Measure change on a committed ledger with Refresh, not by comparing fresh generations.

## Where it lives

Commit a repo skill's ledger under `learn/ledgers/<name>.json` (all repo ledgers live there; one may span skills). For another skill or repo, keep it under `$TMPDIR` and regenerate on demand.
