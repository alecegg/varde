# Task Execution

Read this before running a plan's tasks. Sequential strategies run one task at a
time, in dependency order. `parallel` runs one dependency-ready wave only
when task ownership and verification resources prove independence.
Sequential runs execute one task at a time.

## Choose the next ready task or wave

A `todo` task is ready when every task in its `depends_on` is `done`.
Recalculate after each task or verified wave completes. Treat a cycle as a hard
failure. Continue until every task is `done` or `blocked`.

For `parallel`, call `scripts/resolve-execution-wave.py <manifest>`. It emits
one ordered wave, conflict reasons, and the bounded worker count. Missing
`modifies`, `creates`, `renames`, or `verification_resources` keeps `auto`
sequential. Each parallel candidate also needs at least one exact
`impact:<repo-relative-path>` resource. Shared impact resources serialize
conflicting tasks. Scheduling consumes these resources from the manifest and
does not rebuild a code index per wave. A configured limit above harness
capacity fails before dispatch.

Task states are `todo` → `in_progress` → `done`, with `blocked` reachable from
either of the first two. They are fixed by the workflow schema, not by this
skill (`references/varde-workflow-cli.md`). Move a task to `in_progress` when
its executor starts — with `varde-workflow` on PATH,
`varde-workflow transition <task.md> in_progress --json`. Skipping this step
leaves the task in `todo`, and the `done` move at completion is then rejected
as an illegal transition.

## Executing one task or wave

Execute directly in the selected location by default. Delegate one task only
when unfamiliar code, independent research, or a large bounded investigation
benefits from fresh context; a delegated task gets its briefing,
`#### Verification` checks, change scope (`modifies`/`creates`), and bounded
context. Acceptance criteria remain plan-level.

The `inline` strategy keeps each task in the current executor. The `fresh`
strategy uses a fresh executor for every task. `auto` preserves those choices
unless a complete, conflict-free manifest selects `parallel`.
The fresh strategy uses fresh executors for multi-task plans.

The `parallel` strategy dispatches one wave through
`scripts/run-parallel-wave.sh`. Each worker gets a distinct worktree and branch.
The orchestrator remains the only plan-state writer. Worker commits merge on a
temporary integration branch. The target ref advances only after wave checks
pass. Failed integration keeps recovery refs and leaves the target unchanged.

Every executor reads `references/build-execution.md` before its first tool call,
then runs `execute → varde-review simplify → verify` against its uncommitted
changes.

`varde-review simplify` is diff-scoped and edits inline — the lightweight,
task-local counterpart to the full `varde-review report` + `varde-review fix`
pass, which runs once at plan level (`references/build-plan-run.md` Section F),
not per task.

## Commit-per-task

When a task's `#### Verification` checks pass, its executor commits source
changes in the selected location, including its own `tasks/<task-id>.md` when
plan storage is tracked. Per-task commits — not per-task branches — give the run
its granularity: history shows one commit per task, and a failed run resumes at a
commit boundary.

## Bounded retry

Retries are bounded at two targeted attempts. If Verify keeps failing after
`varde-review simplify`'s own per-file revert, retry with the specific failure,
the current diff, the task's `#### Verification` checks, and prior progress — use
a fresh subagent only when fresh context could change the investigation, never a
blind rerun.

Once exhausted, mark the task or wave `blocked` with the reason in its
`#### Progress`, then **halt the run**. Leave partial worker changes and
recovery refs for diagnosis. Report where and why it stopped.

## Resume check

Progress lives in each task's frontmatter, so derive state directly rather than
from a log. Every `done` task needs a matching source commit; the next ready task
is the first `backlog` task whose `depends_on` are all `done`.

Confirm a recorded worktree's branch and path still exist before reusing one — a
missing worktree is a blocker, not something to silently recreate.

If a task is `done` with no matching source commit, or has commits but no
completion entry in its `#### Progress`, stop and show it rather than inferring
the outcome. A human decides whether to retry, confirm done, or mark it blocked.
