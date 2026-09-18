# Plan run procedures

Plan Run behaviour for both **interactive** mode (`varde-change build` with no
argument) and **unattended** mode (a named plan run straight through, including
every `varde-change orchestrate` invocation). Steps branch on mode only where
noted. Build owns every procedure here; no caller duplicates them.

Read `references/build-execution.md` before executing any step — it defines the
TDD cycle, the Given/Unknowns/Plan/Verification frame, and blocker handling.
Read `references/build-dispatch.md` before running any task — it owns the
sequential loop and the resume check.

## Git scope

**Local-first invariant:** use the current `repo_root` checkout unless the user
requests isolation or a concrete concurrent-edit risk requires a worktree.

Plan Run orchestrates; it never edits source files itself. Every task runs and
commits in the selected location, per `references/build-dispatch.md` — no
per-task branch, no integration stage. Stage only task-owned paths so unrelated
edits survive. Plan Run never pushes, and a worktree run merges only through
Section F. Never `git reset --hard` the shared tree — it destroys work outside
the plan's scope that nothing here can recover.

## Failure states (unattended mode)

A command failing unexpectedly after retry, a task blocking, or the plan
entering `blocked` status all stop unattended execution immediately. Leave the
working state as-is for the human and report where and why. Plan Run merges and
cleans up nothing.

## Select the plan and build the ordered task list

1. **Discover plans.** List `memory-bank/working/plans/` and read each
   `plan.md`'s frontmatter for `status`, `title`, and `depends_on`. Keep
   `backlog` and `active` plans, then exclude any whose `depends_on` names a
   plan that is not yet `completed`. Sort backlog first, then by plan number.
   Report how many plans an unsatisfied `depends_on` chain hid. If none
   survive, say `No backlog or active plans available. Nothing to run.` and
   stop before the selection prompt.
2. **Select.** With a plan ID given, select it directly; if no discovered plan
   matches, stop with `Plan <plan-id> not found.` Otherwise present each option
   as `<id> — <title>` with that plan's `goal` field as the description.
3. **Load tasks.** Read each `tasks/<task-id>.md` in the plan directory. Task
   frontmatter carries `status` and `depends_on`; the `id` is the filename.
4. **Decompose if there are no task files.** A settled spec plus plan-level
   acceptance criteria with no `tasks/*.md` means *not yet decomposed*, not
   *nothing to run* — a spec-only plan is build's normal input. Run
   `references/build-decomposition.md` now, then re-read the task files. Skip
   only on a resume where task files already exist.
5. **Order them.** Sort by `depends_on`, resolving each entry by exact ID or
   unique descriptor suffix and treating `done` dependencies as satisfied.
   Report a dependency naming a task that is missing or not done as
   `blocked_by_dep`; treat a cycle as a hard failure. Readiness is re-derived
   from this after each task completes, never stored. Print the execution order.

## Run the plan

### Step 0 — Confirm the location and resume check

Build step 3 already selected the current checkout or an optional worktree.
Apply `references/build-dispatch.md`'s resume check, then derive progress from
each task's frontmatter. Surface inconsistent commit or Progress evidence rather
than inferring an outcome from it.

### A — Execute tasks sequentially

Apply `references/build-dispatch.md` to the ordered list: derive the next ready
task, execute it in the selected location, run
`execute → varde-review simplify → verify` per `references/build-execution.md`,
then re-derive. Repeat until every task is `done` or `blocked`. Delegate only
when the task benefits from fresh context.

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

Read every `tasks/*.md` and present the wrap-up only when all are `done`.

If the caller asked for a deferred finish, say the implementation is complete and
the finish is deferred, then stop without setting the plan completed.
`varde-change orchestrate` never defers — it runs each plan to completion.

Otherwise run `varde-review report`, delegating only when the harness exposes a
useful review agent. Pass: review target type `plan`, the plan ID and goal, the
plan-level acceptance criteria verbatim, the completed task IDs with each task's
`#### Verification` evidence, and the verification evidence gathered during the
run. The review validates plan-level acceptance criteria and coding standards and
must not modify source files. Display its findings.

Resolve findings in **one bounded round** — no re-review loop:

1. If the review produced findings, run `varde-review fix mode=build`, passing
   the review ID and `plan_context` (plan goal, plan-level acceptance criteria,
   each completed task's `creates`/`modifies` scope). `mode=build` is what makes
   the fix pass attempt every finding rather than only `Label: auto-fix` ones,
   escalating to the human only when a fix would conflict with the plan's AC or
   spec, or change functionality outside the plan's scope. Wait for it.
2. Display only escalated findings — a check tripped, so those need a human
   decision. Everything else is fixed and verified. Anything still open after
   this round is **reported as deferred, not re-looped**.
3. If the fix pass created companion action-item plans, do not complete this
   plan — report them, and leave this plan in its prior status.
4. With no findings, none escalated, and no companion plans, proceed.

Walk each `## Acceptance criteria` item in `plan.md`, verify it holds, and edit
`plan.md` to toggle `- [ ]` to `- [x]`. An item that cannot be confirmed is a
blocker — stop rather than complete a plan with unconfirmed criteria.

Completion is then automatic; there is no Complete/Postpone prompt. Set the
plan's frontmatter `status: completed`, committing that edit when plan storage is
tracked.

On the local default, show the completed diff in place. When build step 3 created
the worktree, offer **Merge** or **Stop** via `references/build-interview.md`,
defaulting to Merge — the user cannot see the change in their own checkout until
it lands. Merge per `references/worktree.md`, then clean up. Stop is the explicit
opt-out: the committed worktree stays isolated and the user is told where it
lives.

Afterwards, move any plan whose status is terminal (`completed` or `archived`)
into an `archive/` subdirectory if that is the repo's convention, preserving its
status. Commit the move for tracked plans.
