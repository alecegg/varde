# Orchestrate plan sets

Run a chosen plan set's ready plans in parallel, one background orchestrator per plan within the session's orchestrator cap; with none stated, ask once. Each plan's orchestrator owns review, conclusion and merge.

Outcomes and how to validate each:

- The user chose the plan set after seeing the unfinished sets and any exclusions. Validate: no plan launched before that choice.
- A plan starts only when no running plan blocks it: `depends_on` orders it after none. Its `shared:` list and declared task path patterns also meet no running plan's paths (a directory or glob overlaps any path under it). Validate: `varde plan readiness <plan.md> --json` reports ready.
- Plans start one at a time in the saved `queue-order.json` order, with plan-id order as fallback. Each started plan counts as running for the next check. Held plans are reported with what holds them until the conflicting plan merges or the user drops it.
- Each plan starts with its resolved absolute working and knowledge paths.
- A command interrupted by a main-agent message was not rejected by the user; rerun it.
- When a plan blocks or fails:
  - only plans that depend on or overlap it are held;
  - running plans finish;
  - nothing from the failed plan merges;
  - the report names the failed, completed and held plans with blockers.
