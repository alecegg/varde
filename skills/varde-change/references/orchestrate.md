# Orchestrate plan sets

Run a chosen plan set's ready plans in parallel, one background orchestrator per plan within the session's orchestrator cap; with none stated, ask once. A plan set is a folder grouping related plans: `varde plan status` lists them together. Each plan's orchestrator owns review, conclusion, and merge.

## Select and order

- List plan sets that have unfinished plans using `scripts/select-plans.py --working <working>`; report exclusions and wait for the user's choice. Send a named non-plan request to `varde-change build` and stop.
- `varde plan readiness <plan.md> --json` reports what is ready. Missing dependencies or cycles block affected plans.
- Start ready plans in the chosen set one at a time in id order; each started plan counts as running for the next check.
- Start a plan only when no running plan blocks it: `depends_on` does not order it after one, and neither the plan's `shared:` list nor its tasks' `owns`/`modifies`/`creates`/`renames` patterns meet a running plan's. A directory or glob overlaps any path under it.
- Hold the rest until the conflicting plan merges or the user drops it; report held plans and what holds them.
- Start a ready plan with `varde-change build` (named-plan route), passing the resolved absolute `<working>` and `<knowledge>` paths. Each plan runs under its own background orchestrator per `references/build-orchestrate-tasks.md`.

## Run the set

- If a plan blocks or fails, hold only plans that depend on or overlap the failed plan, let running plans finish, merge nothing from the failed plan, and report the failed, completed, and held plans with blockers.
- Have each plan's orchestrator finish it: arrange the independent review, run `varde plan conclude`, and integrate only after the main agent relays approval with `varde msg send --to <plan id> --kind info`. Follow `references/build-finish.md`.
- Have the orchestrator load `varde-knowledge`: use your skill tool, or read `../../varde-knowledge/SKILL.md`, and commit durable decisions or lessons with its reflect route only when they exist.
