---
name: varde-learn
description: "Diagnose a past or current agent session, capture observed friction, reconcile evidence, distill recurring issues, track recurrence, or create and evaluate skill tests. Not for durable project notes, plans, general code changes, or reviews."
---

# Maintain friction and skill evaluations

Use `varde-learn` to manage friction in the global SQLite store and maintain
skill output evaluations and trigger query sets.

## Route

| Request | Read |
|---|---|
| Capture an observed friction event | `references/capture.md` |
| Diagnose an existing or current agent session | `references/diagnose.md` |
| Reconcile an item against evidence | `references/reconcile.md` |
| Distill recurring friction into an improvement | `references/distill.md` |
| Check whether an adopted change recurred | `references/recurrence.md` |
| Author query sets or eval cases, or run an approved evaluation | `references/evals.md` |

## Workflow

1. Select the matching request in the table above.
2. Read its reference and follow that procedure through verification.
3. Report the changed item, diagnosis report path, or verification result.

## Gotchas

- If `varde-learn` is missing from `PATH`, report that friction cannot be recorded, continue unrelated work, and do not write Markdown. On sandbox denial, retry the command unchanged once with escalated access; if it fails, report the obstacle.
- An evaluation file does not authorize billed harness sessions; get explicit approval before running them.
