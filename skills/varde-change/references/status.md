# Change status

Derive status from existing artifacts. Status is a read of what is already on
disk — the artifacts it inspects are the only record, and it leaves every one of
them exactly as found.

## Assumed layout

Status reads plan and handoff files from disk. It uses the `varde-change plan`
layout:

- Plans live at `memory-bank/working/plans/<plan-id>/plan.md`, with YAML
  frontmatter carrying `status`. Task files and review folders sit beside their
  owning plan.
- Handoffs live at `memory-bank/working/handoffs/<handoff-id>/handoff.md`,
  with frontmatter carrying `type: handoff`, `status` (`open`/`resumed`),
  `description`, `timestamp`, `head_sha`, and `links` (entries with
  `kind`/`target`).

If the repository uses another layout, adjust the globs but keep this result.

## Workflow

Derive `REPO_ROOT` from the current working directory, then show both panels.

1. **List active plans.** Follow `references/status-list-plans.md` for the glob,
   sort rule, top-5 cutoff, and table format.
2. **List open handoffs.** Follow `references/status-open-handoffs.md` for the same.
3. **Recommend one next mode.** Report active, blocked, and resumable work
   first. Then name a single `varde-change` mode that matches it: `plan` when
   the work has no plan yet, `build` when a plan is ready to execute,
   `orchestrate` when a group plan has ready children, `verify` when a plan
   needs aggregate evidence. Stop there.

## Gotchas

- Step 3 names the next mode; running it is the user's call. A modification
  request that arrives here (update a task, create a plan, change status,
  review, simplify) gets the name of the mode that owns it.
- Task facts (status, counts, readiness) live only in each task file's own
  frontmatter. There is no separate task index. Always read `tasks/*.md`
  directly under the relevant plan directory when computing a plan's task
  counts.
