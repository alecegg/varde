# Change status

Read current artifacts from disk.
Leave every plan, task, and handoff unchanged.
Batch both inventories and readiness checks together.

## Plans

1. Glob `<working>/plans/*/plan.md`.
2. Read frontmatter from each file.
3. Keep statuses except completed and archived.
4. Sort date-prefixed identifiers newest first.
   Put legacy numeric identifiers last.
5. Keep five plans and count remaining matches.
6. Count adjacent `tasks/*.md` files and done statuses.
7. Show Status, Plan, Tasks, and Done columns.

Report `No plans in a non-terminal status.` when empty.
Read task facts only from each task file.

## Handoffs

1. Glob `<working>/handoffs/*/handoff.md`.
2. Keep handoffs whose status is open.
3. Sort timestamps newest first and keep five.
4. Resolve every `kind: plan` link's current status.
5. Show Handoff, Description, Timestamp, and Linked plan status.

Report `No open handoffs.` when empty.
Show missing values plainly.
Report additional match counts after each table.

## Next mode

For each listed plan, run
`varde-workflow readiness <plan.md> --json` when available.
Use its blockers and actions as authoritative.

Recommend exactly one next `varde-change` mode:

- `plan` for unplanned work.
- `build` for one ready plan.
- `orchestrate` for ready group children.
- `verify` for aggregate evidence.

State `Recommended next mode: <mode>` and stop.
Never run the recommendation.
