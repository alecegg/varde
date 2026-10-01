---
name: varde-learn
description: "Diagnose an agent session or briefly triage supplied agent-session evidence; capture or reconcile friction, distill recurring issues, track recurrence, or create skill tests. Not for project notes, plans, code changes, or reviews."
---

# Maintain friction and skill evaluations

## Route

| Request | Read |
|---|---|
| Capture an observed friction event | `references/capture.md` |
| Triage supplied agent-session evidence without a session-wide diagnosis | `references/diagnose-quick.md` |
| Diagnose an existing or current agent session | `references/diagnose.md` |
| Reconcile an item against evidence | `references/reconcile.md` |
| Distill recurring friction into an improvement | `references/distill.md` |
| Check whether an adopted change recurred | `references/recurrence.md` |
| Author query sets or eval cases, or run an approved evaluation | `references/evals.md` |

## Gotchas

- When a `friction list` or `friction show` result has `meta.truncated` true, repeat with `--offset` set to `meta.next_offset`, and read every page before counting or judging.
- If `varde-learn` is missing from `PATH`, report that friction cannot be recorded, continue unrelated work, and do not record friction in Markdown. On sandbox denial, retry the command unchanged once with escalated access; if it fails, report the obstacle.
