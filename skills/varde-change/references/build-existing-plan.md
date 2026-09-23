# Build an existing plan

Use the named plan directly.
Never create a replacement plan.
Do not load other build references for simple plans.

## Prepare

1. Read `plan.md` and every existing `tasks/*.md`.
2. Use the current checkout unless isolation was requested.
3. Announce `execution=auto` and the task count.
4. When the plan is backlog, move it active.
   Prefer `varde-workflow transition <plan.md> active --json`.

## Decompose only when needed

Keep existing task files.
When none exist, inspect the specification and acceptance criteria.

For one bounded outcome, create one task directly.
Use type, parent, status `todo`, dependencies, modifies, and creates.
Add Test approach, Out of scope, Verification, and Progress sections.
Set its outcome, paths, risks, and boundaries.
Choose one testing profile with a one-line rationale.
Convert plan criteria into focused assert or retrieve checks.
Keep acceptance criteria only within `plan.md`.
Commit the initial task file when plan storage is tracked.

For multiple outcomes, unclear design, or edge cases, read
`references/build-decomposition.md` instead.

## Execute

One simple task runs inline using the rules below.
Move it from todo to in_progress.
Prefer `varde-workflow transition <task.md> in_progress --json`.
Inspect its target and nearby tests.
For existing target paths, combine the `varde-code` index build and
`varde-code batch` within one shell call.
Request scoped symbols and covering tests together.
Skip indexing when every target is newly created.
Fall back when unavailable or unsuccessful.
Follow its declared testing profile.
Implement only its bounded outcome.
Run `varde-review simplify` on uncommitted changes.
Run every Verification check and inspect retrieved evidence.
Retry targeted failures at most twice.

On success, append one exact evidence marker:
`- evidence: profile=<profile>; checks=<checks>; result=pass; note=<result>`.
Validate it using `scripts/validate-task-evidence.sh <task.md>`.
Move the task done through `varde-workflow` when available.
Commit only task-owned paths.
Batch independent reads, checks, and status inspection.

On failure, mark the task blocked and stop.
Leave partial changes intact and report the reason.

For multiple, risky, research, or resumed tasks, read
`references/build-execution.md` and `references/build-dispatch.md`.
Run tasks sequentially in dependency order.

## Finish

If the user requested deferred completion, report implementation complete.
Then stop before finishing the plan.

Otherwise run one report-only `varde-review report` pass.
Run one `varde-review fix mode=build` round when findings exist.
Pass the review ID and plan context.
Do not re-review.
Stop when companion plans remain.

Run every acceptance criterion's exact evidence check.
Check only confirmed criteria.
Refresh declared observed specifications through `varde-docs spec`.
Conclude using `varde-workflow conclude <plan.md> --json`.
Without that CLI, stop before conclusion mutations.
Then run `varde-knowledge reflect` with a completion handoff.
Record conclusion actions when required.

Show the local diff.
Only load interview and worktree guidance when isolation occurred.
