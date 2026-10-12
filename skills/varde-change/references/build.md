# Build a plan or larger change

## Choose a route

| Request | Action |
|---|---|
| Build an existing plan, no plan named | Run `scripts/select-plans.py --working <working>`; report exclusions and present choices. Stop on a degraded result or when no plans qualify. |
| Named plan | Build it. |
| Ad hoc request with dependent outcomes | Create a minimal plan and acceptance criteria, confirm once, decompose it, then build it. |
| Uncertain change | Hand off to `varde-change plan`. |

Interactive builds pause for user choices. Unattended builds run the named plan
without pauses. Use map context for source discovery or relationship questions.

## Start from the approved plan

- Create the plan branch and worktree at build start with
  `scripts/worktree-create.sh`, then run `varde plan status` and show the
  plan's staleness notice. Keep plan and task files in their configured home.
- Set `branch: <plan branch>` in the plan frontmatter (no CLI setter) so
  `varde plan watch` binds it.
- Record the plan branch's `base` commit; `references/build-finish.md` uses it
  for the finish review.
- Commit that state only under authority already granted.
- Use the task's declared posture; without one, follow the default execution
  path.
- Follow `references/plan-decomposition.md` for decomposition and posture
  fields. Builders and inline work follow `references/build-execution.md`.

## Run the task graph

Use `references/build-orchestrate-tasks.md` for task delegation and
communication; it covers the related guardrails and commands.

## Finish

When tasks are complete, follow `references/build-finish.md`. Do not offer
target integration until the implementation review and plan conclusion are
complete.
