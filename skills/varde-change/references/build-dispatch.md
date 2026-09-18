# Sequential Task Execution

Load this before running a plan's tasks. Tasks run one at a time, in dependency
order, committing into the shared build location — no batching, no parallel
dispatch, no cross-task integration stage.

## Deriving the next ready task

A `backlog` task is ready when every task in its `depends_on` is `done`.
Re-derive after each task completes and walk them in dependency order; treat a
cycle as a hard failure. Continue until every remaining task is `done` or
`blocked`.

## Executing one task

Execute directly in the selected location by default. Delegate one task only
when unfamiliar code, independent research, or a large bounded investigation
benefits from fresh context; a delegated task gets its briefing,
`#### Verification` checks, change scope (`modifies`/`creates`), and bounded
context. Acceptance criteria remain plan-level.

Every executor loads `references/build-execution.md` before its first tool call,
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

Once exhausted, mark the task `blocked` with the reason in its `#### Progress`,
then **halt the run**. A sequential run has no parallel work to continue with:
leave the working state as-is, including the failed task's partial changes,
report where and why it stopped, and do not merge or clean up a worktree.

## Resume check

Progress lives in each task's frontmatter, so derive state directly rather than
from a log. Every `done` task needs a matching source commit; the next ready task
is the first `backlog` task whose `depends_on` are all `done`.

Confirm a recorded worktree's branch and path still exist before reusing one — a
missing worktree is a blocker, not something to silently recreate.

If a task is `done` with no matching source commit, or has commits but no
completion entry in its `#### Progress`, stop and show it rather than inferring
the outcome. A human decides whether to retry, confirm done, or mark it blocked.
