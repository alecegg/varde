# Sequential Task Execution

Load this before running a plan's tasks. It covers how ready tasks are derived,
when a task benefits from a subagent, the commit-per-task rule, bounded retry,
blocker handling, and the resume gate.
There is no batching, no parallel dispatch, and no cross-task integration stage:
tasks run one at a time, in dependency order, committing into the shared build
location.

## Execution location

`SKILL.md` step 3 uses the current checkout by default. It records
`location: local` in the run-state file
(`memory-bank/working/plans/<plan-id>/run-state.md`). When isolation is chosen,
record the worktree path and branch instead. Every task commits in the selected
location. The local checkout keeps the live diff available to the user.

## Deriving the next ready task

Readiness is always computed live from `depends_on`, never read from a stored
`ready` field. A task (`status: backlog`) is ready only when every task in its
`depends_on` list has `status: done`. After each task completes, re-derive the
next ready task. Walk ready tasks in dependency order (stable topological sort
by task id; treat a dependency cycle as a hard failure). Continue until every
remaining task is `done` or `blocked`.

## Executing one task

Execute tasks directly in the selected location by default. Delegate one task
only when unfamiliar code, independent research, or a large bounded
investigation benefits from fresh context. A delegated task gets its briefing,
`#### Verification` checks, change scope (`modifies`/`creates`), and bounded
context. Acceptance criteria remain plan-level. Every executor loads
`EXECUTION.md` before its first tool call, then runs
`execute -> /varde-simplify -> verify` against its uncommitted changes. The
orchestrator records the outcome in the run-state file and derives the next
task.

`/varde-simplify` is diff-scoped and edits inline — the lightweight, task-local
counterpart to the full `/varde-review` + `/varde-review-fix` pass, which runs
once at the plan level (`PLAN-RUN.md` Section F), not per task. The per-task
simplify writes nothing under the shared plan directory
(`memory-bank/working/plans/<plan-id>/`) beyond the task's own file.

## Commit-per-task

When a task's `#### Verification` checks pass, its executor commits source
changes together with its own `tasks/<task-id>.md`
in one commit in the selected execution location
(`git add <source-paths> memory-bank/working/plans/<plan-id>/tasks/<task-id>.md
&& git commit -m "task: <task-id> done"`). Per-task commits — not per-task
branches — provide the run's granularity: history shows one commit per task, and
a failed run can be resumed or reset at a commit boundary. The task file must
never sit uncommitted after the task is done. The executor never commits
`plan.md` (orchestrator-owned).

## Bounded retry and blocker handling

Per-task retries are bounded by `MAX_TASK_RETRIES = 2` targeted retries. If the
Verify step keeps failing after `/varde-simplify`'s own per-file revert, retry
with the specific failure, current diff, the task's `#### Verification` checks,
and prior progress. Use a fresh subagent only when fresh context could change
the investigation; never blindly rerun the same pass.
Count each attempt and log it in the run-state file. After the retry limit is
exhausted:

- Mark the task `blocked` (edit that task's own `status:` field directly — never
  `plan.md`), append the reason to its `#### Progress` section, and log it.
- **Halt the run fail-closed.** In a sequential unattended run there is no
  parallel work to continue; leave the selected working state as-is (partial, uncommitted
  changes for the failed task included) for the human, and report where and why
  the run stopped. Do not merge or clean up an optional worktree.

A task-specific blocker (this task's `#### Verification` can't pass) is owned by
the task worker. A plan-wide blocker (the whole plan's assumptions no longer
hold, e.g.
found during the Plan Staleness Check before dispatch) is owned by the
orchestrator: edit `plan.md` frontmatter `status:` to `blocked` and stop.

## Resume gate

Before resuming, read the execution location from the run-state file. For
`location: local`, resume in the current checkout after inspecting its diff.
For a recorded worktree, confirm its branch and path still exist before using
it. A missing recorded worktree is a blocker; do not silently recreate it.

Then, since progress lives in each task's frontmatter, derive state directly:
every `done` task is complete when its commit exists in the selected location;
the next
ready task is the first `backlog` task whose `depends_on` are all `done`. If a
task is `done` but has no matching commit on the branch, or has commits but no
completion entry in its `#### Progress` section, stop and surface it rather than
inferring the outcome — a human decides whether to retry, confirm done, or mark
it blocked.
