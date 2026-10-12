# Generate or refresh a flow ledger

A flow ledger lists a skill's workflow decisions with cited source lines, so `varde doc flow ledger` can score full-flow complexity offline. An auditor subagent writes it; no API key or direct model call is involved.

Run `varde doc flow ledger <hash|validate|score|check> <ledger.json> [--root DIR] [--json]`; `score` also takes `--route NAME`. Cited paths are relative to `--root` (default: the current Git top level).

## Choose generate or refresh

| Situation | Do |
|---|---|
| No ledger yet, or an audit of an external skill or repo | Generate |
| A ledger exists and sources changed | Refresh |

`ledger check` exits 0 when no existing decision's cited lines changed. It cannot see new decisions, so refresh still inspects changed instruction files.

## Generate

1. Pick the source root, revision, entry files, and route. For a read-only or other-revision repo, export it first: `git -C <repo> archive <rev> | tar -x -C "$TMPDIR/<name>"`, and pass that directory as `--root` to every ledger command.
2. Fill `assets/flow-ledger-prompt.md` and dispatch one auditor subagent in the current harness with it. Do not edit its counting rules.
3. Run `ledger hash` on the output, then `ledger validate`. A failure other than a hash is the auditor's to fix: send the printed problems back once. If the second attempt still fails, report the problems and stop.
4. Run `ledger score` and report totals with the route and auditor model, labeled as estimates. `validate` checks structure, not completeness; paired audits have differed by up to 19%. Measure change on a committed ledger with Refresh, not by comparing fresh generations.

## Refresh

1. Run `ledger check`; each stale id names the decision and where it now sits. List the instruction files changed since the ledger's revision, even when nothing is stale.
2. Send the auditor only the stale ids, their files, and the current ledger. Ask for corrected line bounds, alternatives, units, and depth for those ids, plus any new decisions in every changed instruction file.
3. Merge the answer, then `ledger hash`, `ledger validate`, `ledger score`.

## Where it lives

For a skill in this repo, commit the ledger under `skills/ledgers/<name>.json` (it may span skills); for another skill or repo, keep it under `$TMPDIR` and regenerate on demand.
