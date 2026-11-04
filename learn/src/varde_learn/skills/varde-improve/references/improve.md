<!-- kind: procedure -->
# Propose a friction improvement

Use this route when a timer starts an agent to review recurring friction, for example a cron job.

## Outcomes

- Evidence comes from `varde learn friction list --status open --json` (items inspected with `friction show <ID>`) and `varde learn friction recurrence --json`. Historical reports are reports, not proof a problem remains; do not infer recurrence from `meta.skipped_invalid_timestamps`.
- A group is selected only when at least two real occurrences share an obstacle and improvement target. It also requires verifying the evidence, current source and guidance. If evidence is insufficient, report that and stop, proposing nothing.
- The plan or skill-edit proposal contains (validate: each is present):
  - source IDs and occurrence evidence for the shared failure;
  - exact target and proposal, expected impact, risks, items to promote;
  - a removal option, four audit answers from `references/options.md`, and one outcome tag per proposal.
- The proposal is presented and the run stops for human approval; no file is edited and no adoption is recorded before approval.
