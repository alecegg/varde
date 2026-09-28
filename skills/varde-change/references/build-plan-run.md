# Plan run procedures

Interactive mode is `varde-change build` with no argument; unattended mode is
a named plan run without pauses, including every `varde-change orchestrate`
invocation. `references/build-execution.md` defines the task cycle;
`references/build-dispatch.md` owns the loop and the resume check.

## Git scope

The plan runner controls the sequence but never edits source files. Tasks
commit in the selected location, one commit per task, however the
wave ran. Unrelated edits survive. Never push, never `git reset --hard` the shared
tree, and merge a worktree only through the wrap-up.

## Failure states (unattended mode)

A command failing unexpectedly after retry, a task blocking, or the plan
entering `blocked` stops unattended execution immediately. Leave the working
state as-is, report where and why, and merge or clean up nothing.

## Select the plan and order its tasks

1. **Discover plans.** Read every `plan.md` at any depth under
   `<working>/plans/` for `status`, `title`, and `depends_on`; skip
   `shape: group` and draft plans (id ending `-draft`, or a live
   `## Open Questions` bullet, per `references/plan-resume.md`). Keep
   `backlog` and `active` plans whose `depends_on` plans are all `completed`
   — use `varde-workflow readiness <plan.md> --json` when available.
   `planning_ready` reports dependency availability;
   `implementation_ready` also includes review approval. Do not hide a plan
   from selection just because its review is missing: report that blocker and
   do not dispatch implementation until its start or resume check passes.
   `readiness` reports only the root plan's dependency blockers, so also run
   `varde-workflow graph <sibling>/plan.md --json` once and exclude any plan
   named by a `dependency_cycle` blocker.
   Sort backlog first, then by id (oldest date prefix first), and report how many plans a
   blocked `depends_on` chain excluded. If none survive, say
   `No backlog or active plans available. Nothing to run.` and stop.
2. **Select.** With a plan ID given, select it; if nothing matches, stop with
   `Plan <plan-id> not found.` Otherwise present each option as
   `<id> — <title>`.
3. **Read tasks.** Read each `tasks/<task-id>.md`; the `id` is the filename.
   Move the plan to `active` before the first task runs only when it is
   `backlog` (resume must not run `active` → `active`), and commit that
   transition when plan storage is tracked.
4. **Check dependencies.** `depends_on` entries are exact task ids. Run the
   resolver once (`references/build-dispatch.md`): report each
   `blocked_by_dep` entry, and stop on a cycle (exit 3).

## Run the plan

1. Run the resume check in `references/build-dispatch.md`. If it finds a
   `blocked` task, handle it with step 2 before selecting another wave. Then
   resolve and run waves; repeat until every task is `done` or `blocked`, or
   the resolver returns an empty `next_wave`.
2. **Handle a blocked task**, including one found on resume. Unattended, it is a
   failure state: stop and report the reason. Interactive, present the reason
   and offer Retry (move this task back to `in_progress` and re-dispatch it
   alone), Continue independent work, or Abort (stop and print a partial
   summary). Continue leaves the failed task `blocked`: record the decision and
   task id in its `#### Progress`, resolve a fresh wave, and run only its
   `next_wave`.
   Tasks whose dependencies remain blocked stay `todo` and are reported as
   `blocked_by_dep`; Continue does not change the failed task's status. If no
   ready work remains, stop with the plan incomplete; a later run can retry the
   blocked task after its cause is addressed. A `done` task is already
   committed; continue without pausing.
3. **Summarize** `done` and `blocked` task IDs, omitting empty categories;
   report remaining `todo` tasks as `blocked_by_dep`. Keep the plan active and
   resumable while any task is not done.
4. All done → `references/build-plan-finish.md` unless completion was
   deferred.
