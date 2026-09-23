# Plan run procedures

This file defines plan-run behavior for **interactive** mode (`varde-change build` with no
argument) and **unattended** mode (a named plan run without pauses, including
every `varde-change orchestrate` invocation). Steps branch on mode only where
noted. Build owns every procedure here. Callers do not duplicate them.

Read `references/build-execution.md` before executing any step — it defines the
TDD cycle, the Given/Unknowns/Plan/Verification frame, and blocker handling.
Read `references/build-dispatch.md` before running any task — it owns the
sequential loop and the resume check.

## Git scope

**Local-first invariant:** use the current `repo_root` checkout unless the user
requests isolation or a concrete concurrent-edit risk requires a worktree.

The plan runner controls the sequence but never edits source files. Sequential
tasks commit in the selected location. A parallel wave uses isolated worker
branches and a temporary integration branch, then stages only verified commits.
Unrelated edits survive. Plan Run never pushes, and a worktree run merges only
through Section F. Never `git reset --hard` the shared tree.

## Failure states (unattended mode)

A command failing unexpectedly after retry, a task blocking, or the plan
entering `blocked` status all stop unattended execution immediately. Leave the
working state as-is for the human and report where and why. Plan Run merges and
cleans up nothing.

## Select the plan and build the ordered task list

1. **Discover plans.** List `<working>/plans/` and read each
   `plan.md`'s frontmatter for `status`, `title`, and `depends_on`. Keep
   `backlog` and `active` plans, then exclude any whose `depends_on` names a
   plan that is not yet `completed`. With `varde-workflow` on PATH, get that
   exclusion from `varde-workflow readiness <plan.md> --json` rather than
   deriving it: a plan with a non-empty `blockers` array is held back, and its
   `actions` array is the set of states it may legally move to next. Sort
   backlog first, then by plan number.
   Report how many plans a blocked `depends_on` chain excluded. If none
   survive, say `No backlog or active plans available. Nothing to run.` and
   stop before the selection prompt.
2. **Select.** With a plan ID given, select it directly; if no discovered plan
   matches, stop with `Plan <plan-id> not found.` Otherwise present each option
   as `<id> — <title>` with that plan's `goal` field as the description.
3. **Read tasks.** Read each `tasks/<task-id>.md` in the plan directory. Task
   frontmatter carries `status` and `depends_on`; the `id` is the filename.
   Move the selected plan to `active` before the first task runs — with
   `varde-workflow` on PATH,
   `varde-workflow transition <plan.md> active --json`. A plan left in
   `backlog` cannot legally reach `completed`, so `conclude` fails at the end
   of an otherwise clean run.
4. **Decompose if there are no task files.** A settled spec plus plan-level
   acceptance criteria with no `tasks/*.md` means *not yet decomposed*, not
   *nothing to run* — a spec-only plan is build's normal input. Run
   `references/build-decomposition.md` now, then re-read the task files. Skip
   only on a resume where task files already exist.
5. **Order them.** Sort by `depends_on`, resolving each entry by exact ID or
   unique descriptor suffix and treating `done` dependencies as satisfied.
   Report a dependency naming a task that is missing or not done as
   `blocked_by_dep`; treat a cycle as a hard failure. Recalculate readiness
   after each task completes; never store it. Print the execution order.

## Run the plan

### Step 0 — Confirm the location and resume check

Build step 3 already selected the current checkout or an optional worktree.
Apply `references/build-dispatch.md`'s resume check, then read progress from
each task's frontmatter. Report inconsistent commit or Progress evidence rather
than inferring an outcome from it.

### A — Execute tasks or waves

Apply `references/build-dispatch.md` to the ordered list: choose the next ready
task, execute it in the selected location, run
`execute → varde-review simplify → verify` per `references/build-execution.md`,
then recalculate readiness. For `parallel`, dispatch one conflict-free ready
wave with isolated workers and verify its integration before continuing.
Repeat until every task is `done` or `blocked`. Announce the resolved strategy
before dispatch: `inline` keeps tasks here, `fresh` uses new executors,
`parallel` uses two workers by default, and `auto` selects parallel only from
proven manifest independence.

Before dispatching each task, re-apply the **task-size check** that
`references/build-decomposition.md` applied at authoring time. A task that fails
it is never dispatched. Unattended, that is a Failure State — stop and report
which checks failed and that the task must be replanned or split. Interactive,
present the failed checks and ask whether to abort or skip.

### B–D — Per-task outcome

Read the finished task's own frontmatter `status`.

**`blocked`** — unattended, this is a Failure State: stop and report the reason,
nothing more. Interactive, present the reason and offer Retry (re-dispatch this
task only), Skip (continue; its dependents report as `blocked_by_dep`), or Abort
(stop and print a partial summary).

**`done`** — the executor already committed; there is no integration stage.
Unattended, continue with no per-task diff review. Interactive, show
`git log --oneline -1` and `git show --stat HEAD`, then offer Continue or Revert
(discard that task's commit with `git revert`, stop, print a partial summary,
and preserve unrelated local changes).

### E — Summary

Print `done`, `skipped`, and `blocked` task IDs, omitting any empty category.

### F — Plan wrap-up

When every task is done, read `references/build-plan-finish.md`.
It owns review, acceptance checks, conclusion, reflection, and worktree closure.
When completion was deferred, report implementation complete and stop first.
