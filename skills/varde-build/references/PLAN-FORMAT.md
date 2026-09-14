# Plan Format

Plan and task state live in **plain markdown files**: the plan's `plan.md`
(spec + plan-level `## Acceptance criteria`, no `## Tasks` section) and one
`tasks/<task-id>.md` file per task. Task files are authored by this skill during
decomposition (`references/DECOMPOSITION.md`), not by `/varde-plan`. Edit plan
and task files directly with Read/Edit — there is no dedicated write operation
for plan/task field updates, and no generated `index.md`; enumerate a plan's
tasks by globbing its `tasks/*.md` files.

## Discovering actionable plans

See `references/PLAN-RUN.md` for how to enumerate plan directories, read each
plan's frontmatter, and apply the `depends_on`-gating rule (exclude any plan
whose `depends_on` includes a plan not yet in `completed` status).

Plans run unattended by default: tasks execute one at a time in dependency
order, each committing in the selected execution location. A blocker stops the run
fail-closed and marks the task (or plan) blocked.
