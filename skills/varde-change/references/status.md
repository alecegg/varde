# Change status

Read-only: change no plan, task, or handoff. Batch reads and readiness calls.

**Plans:** every `plan.md` at any depth under `<working>/plans/` not
`completed`; date-prefixed ids newest first, others last; top 5 + remaining
count. Columns Status | Plan | Tasks | Done (from `tasks/*.md` frontmatter
only); a group's children list under it. Empty:
`No plans in a non-terminal status.`

**Handoffs:** `<working>/handoffs/*/handoff.md` with `status: open`, newest 5
+ remaining count. Columns Handoff | Description | Timestamp | Linked plan
status. Empty: `No open handoffs.` Show missing values plainly.

**Next mode:** use `varde-workflow readiness <plan.md> --json`
blockers/actions when available. Recommend one — `plan` (unplanned work, or resume a draft per
`references/plan-resume.md`),
`build` (one ready plan), `orchestrate` (ready group children), `verify`
(aggregate evidence) — as `Recommended next mode: <mode>`, then stop; never
run it.
