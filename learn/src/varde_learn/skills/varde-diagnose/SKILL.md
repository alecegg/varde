---
name: varde-diagnose
description: "Use this skill when session evidence needs analysis: diagnose an agent session, triage supplied evidence, run a multi-session retrospective or orchestrated-build wrap-up, or run a friction cycle over new sessions, and report findings and recommendations."
recommends: [varde-learn, varde-toz, varde-customize, varde-plan, varde-build]
---

# Diagnose agent sessions

| Task | Read |
|---|---|
| Triage supplied agent-session evidence without a session-wide diagnosis | `references/diagnose-quick.md` |
| Diagnose an existing or current agent session | `references/diagnose.md` |
| Run a multi-session retrospective or orchestrated-build wrap-up | `references/retro.md` |
| Run a friction cycle over new sessions | `references/cycle.md` |

This skill reports and recommends; record friction with `varde learn friction add`.

## Gotchas

- A review flag for a skipped how (a step done without its topic) is `how-skip` friction: `varde learn friction add --tag skilltrim --tag how-skip --source <skill>`.
- For truncated `varde learn` lists (`meta.truncated: true`), page with `--offset` set to `meta.next_offset` and read every page before counting or judging.
