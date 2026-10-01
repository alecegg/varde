# Change status

Read-only: change no plan, task, or handoff. Show:

- **Plans:** every `plan.md` at any depth under `<working>/plans/` not
  `completed`; date-prefixed ids newest first, others last; top 5 plus
  remaining count. Columns Status | Plan | Tasks | Done (from `tasks/*.md`
  frontmatter only); a group's children list under it. Empty:
  `No plans in a non-terminal status.`
- **Handoffs:** `<working>/handoffs/*/handoff.md` with `status: open`, newest
  5 plus remaining count (Handoff | Description | Timestamp | Linked plan
  status). Empty: `No open handoffs.`
- **Next mode:** use `varde-workflow readiness <plan.md> --json`
  blockers/actions when available. Recommend one mode as
  `Recommended next mode: <mode>`, then stop; never run it:
  - `plan`: unplanned work, or resume a draft per
    `references/plan.md` (Resume a draft);
  - `build`: one ready plan;
  - `orchestrate`: ready group children;
  - `verify`: aggregate evidence.
