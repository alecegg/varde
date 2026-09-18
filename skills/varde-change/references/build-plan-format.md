# Plan Format

Plan and task state live in **plain markdown files**: the plan's `plan.md`
(spec + plan-level `## Acceptance criteria`, no `## Tasks` section) and one
`tasks/<task-id>.md` file per task. Task files are authored by this skill during
decomposition (`references/build-decomposition.md`), not by `varde-change plan`. Edit plan
and task files directly with Read/Edit — there is no dedicated write operation
for plan/task field updates, and no generated `index.md`; enumerate a plan's
tasks by globbing its `tasks/*.md` files.

## Discovering ready plans

See `references/build-plan-run.md` for how to enumerate plan directories, read each
plan's frontmatter, and apply the `depends_on`-gating rule (exclude any plan
whose `depends_on` includes a plan not yet in `completed` status).
