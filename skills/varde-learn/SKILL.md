---
name: varde-learn
description: "Diagnose an agent session, run a multi-session retrospective, or briefly triage supplied session evidence; capture or reconcile friction, distill recurring issues, track recurrence, review recurring friction for improvements, or create skill tests. Not for project notes, plans, code changes, code or UI reviews (varde-review), or reviewing skill text (varde-agent-doc-authoring)."
recommends: [varde-change, varde-customize, varde-knowledge]
---

# Maintain friction and skill evaluations

## Route

| Request | Read |
|---|---|
| Capture an observed friction event | `references/capture.md` |
| Triage supplied agent-session evidence without a session-wide diagnosis | `references/diagnose-quick.md` |
| Diagnose an existing or current agent session | `references/diagnose.md` |
| Run a multi-session retrospective or orchestrated-build wrap-up | `references/retro.md` |
| Reconcile an item against evidence | `references/reconcile.md` |
| Distill recurring friction into an improvement | `references/distill.md` |
| Check whether an adopted change recurred | `references/recurrence.md` |
| Review recurring friction for an improvement proposal | `references/improve.md` |
| Author query sets or eval cases, or run an approved evaluation | `references/evals.md` |

## Gotchas

- Do not record friction in Markdown.
- For truncated `varde learn` lists (`meta.truncated: true`):
  - Repeat with `--offset` set to `meta.next_offset`.
  - Read every page before counting or judging.
- If `varde` is missing from `PATH`, report that friction cannot be recorded and continue unrelated work.
