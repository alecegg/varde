---
name: varde-dashboard
description: >
  TRIGGER: Show a quick read-only status snapshot of in-flight plans and open
  handoffs — or, when you're not sure which varde-* skill to run, help choose
  where to start and point to the right one. Read-only: it routes, never runs.
  SKIP: Skip when you already know the skill you want and are ready to plan,
  build, review, or edit directly.
  Example phrases: "show active plans", "what's in flight?", "which skill do I
  use?", "where do I start?".
---

## Assumed layout

This skill reads plan/handoff files directly off disk — no database or RPC
layer is involved. It assumes the convention used by `/varde-plan`:

- Plans live at `memory-bank/working/plans/<plan-id>/plan.md`, with YAML
  frontmatter carrying `status`.
- Handoffs live at `memory-bank/working/handoffs/<handoff-id>/handoff.md`,
  with frontmatter carrying `type: handoff`, `status` (`open`/`resumed`),
  `description`, `timestamp`, `head_sha`, and `links` (entries with
  `kind`/`target`).

If a repo's actual layout differs, adapt the globs below accordingly but
keep the same behavior.

## Entry point dispatch

Derive `REPO_ROOT` from the current working directory.

| Invocation | Action |
|---|---|
| *(default — no other query intent given)* | Show both panels: `references/LIST-PLANS.md` then `references/OPEN-HANDOFFS.md`. |
| Any modification request (update a task, create a plan, change status, review, simplify, refine standards) | Redirect via `references/CHOOSE-WORKFLOW.md`'s routing table — this skill is read-only. |

For the concrete glob/grep call shapes behind both panels, see
`references/RECIPES.md`.

## Gotchas

- This skill is read-only. Never execute the selected workflow from
  `dashboard` — always route to the target skill instead.
- Task facts (status, counts, readiness) live only in each task file's own
  frontmatter — there is no separate tasks index to query. Always read
  `tasks/*.md` directly under the relevant plan directory when computing a
  plan's task counts.
