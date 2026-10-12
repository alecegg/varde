<!-- kind: procedure -->
# Propose a friction improvement

Use this route when a timer starts an agent to review recurring friction, for example a cron job.

1. Run `varde learn friction list --status open --json`; inspect items with `friction show <ID>`.
2. Run `varde learn adopt recurrence --json`, then inspect historical reports. Treat them as reports, not proof a problem remains; do not infer recurrence from `meta.skipped_invalid_timestamps`.
3. Select a group only when at least two real occurrences share an obstacle and improvement target. Verify their evidence and inspect the current source and guidance. If evidence is insufficient, report that and stop without proposing a change.
4. Draft a varde-change plan or skill-edit proposal containing:
   - Source IDs and occurrence evidence for the shared failure.
   - Exact target and proposal; expected impact; risks; items to promote.
   - A removal option, four audit answers from [`options.md`](options.md), and one outcome tag per proposal.
5. Present the proposal and stop for human approval. Do not edit files or record adoption before approval.
