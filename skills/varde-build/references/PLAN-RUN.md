# Plan Run Procedures

This reference defines Plan Run behavior for both interactive (`/varde-build`
with no argument) and unattended (`/varde-build plan=<plan-id>`) modes. In
unattended mode the caller passes the plan ID explicitly — all Plan Run
procedures are owned by build, never duplicated by the caller (including
`/varde-orchestrate`, which invokes `/varde-build plan=<id>` once per plan).

Read `EXECUTION.md` before executing any step — it defines the TDD cycle,
Given/Unknowns/Plan/Verification frame, blocker handling, and execution
evidence that apply within every step. Read `DISPATCH.md` before running any
task — it owns the sequential execution loop: deriving the next ready task,
direct execution or a justified delegation in the selected location,
commit-per-task, bounded retry, and the resume gate.

---

## Git scope

**Local-first invariant:** use the current `repo_root` checkout unless the user
requests isolation or a concrete concurrent-edit risk requires a worktree.
Concretely:

- Plan Run is the orchestrator: it never edits source files and never executes a
  task directly against `repo_root`'s checked-out tree.
- Every task runs in the selected location and commits there, per
  `DISPATCH.md`. There is no per-task branch or integration stage.
- In the local default, users can inspect the live diff and interact directly.
  Preserve unrelated edits by staging only task-owned paths.
- Plan Run never pushes to a remote. A worktree run merges only through
  Section F's Merge/Stop.

**Guardrail:** never run `git reset --hard` against the shared tree. Inspect
existing changes before dispatch and preserve every path outside task scope.

---

## Failure States (unattended mode)

The following conditions **stop unattended execution immediately** (fail-closed):

1. **Command failure** — any tool invoked during Plan Run exits with an
   unexpected non-zero code after retry.
2. **Task blocked** — a task exhausts `MAX_TASK_RETRIES` or reports a blocker.
   In a sequential run there is no parallel work to continue: halt, leave the
   selected working state as-is for the human, and report where and why.
3. **Plan blocked** — the plan enters `blocked` status (e.g. Plan Staleness
   Check invalidates the whole plan).

When a Failure State is reached, Plan Run stops, notifies the caller (the user,
or `/varde-orchestrate`) with the failure reason, and executes no further steps.
It does not merge or clean up an optional worktree.

---

## Procedure: SelectPlanAndBuildOrderedTaskList(repo_root, optional_plan_id) → plan_id, ordered_task_list

### Step 1 — Discover plans

List the plan directories and read each `plan.md`'s frontmatter directly:

```bash
ls memory-bank/working/plans/
```

For each plan directory, read `plan.md` and note its `status`, `title`, and
`depends_on` fields. Filter to plans whose `status` is `backlog` or `active`,
then exclude any whose `depends_on` includes a plan not yet `completed` (treat
missing or empty `depends_on` as no dependencies). Sort backlog first, then by
plan number ascending. Report how many plans were hidden by an unsatisfied
`depends_on` chain.

If the output is empty (no backlog or active plans), output:

```
No backlog or active plans available. Nothing to run.
```

and stop before proceeding to the selection prompt.

### Step 2 — Select a plan

If `optional_plan_id` is provided, select that plan directly. If no discovered
plan matches it, stop with: "Plan <plan-id> not found."

If `optional_plan_id` is not provided, present options to the user:
- **Label**: `<id> — <title>`
- **Description**: the `goal` field value from that plan's frontmatter

### Step 3 — Load tasks for the selected plan

Find the selected plan's directory and read each `tasks/<task-id>.md` file. Each
task file's frontmatter carries `status` and `depends_on`; its `id` is the
filename without `.md`.

### Step 3a — Decompose if the plan has no task files

If the plan has a settled spec + plan-level acceptance criteria but **no**
`tasks/<task-id>.md` files, it has not been decomposed yet. Do **not** treat this
as "nothing to run" — decomposition is build's own responsibility (`SKILL.md`
step 4). Run `references/DECOMPOSITION.md` now to author the task files, then
return to Step 3 and re-read them. Skip this step only on a resume where task
files already exist (`DECOMPOSITION.md` runs once per plan, before the first
ready task is derived). A spec-only plan is the normal input to build, not a
failure state — the empty task set means *not yet decomposed*, not *nothing to
run*.

### Step 4 — Compute the initial ready set

There is no stored `ready` status. Readiness is derived live from `depends_on`,
never cached, never read off a task's `status` field. Collect tasks whose
`status` is `backlog`, then compute the ready subset whose every `depends_on`
entry resolves to a task with `status: done`. Tasks with no `depends_on` are
ready immediately. (The loop re-derives this after each task completes, per
`DISPATCH.md`.) If the ready set is empty because the plan has no task files at
all, Step 3a was skipped — decompose first rather than reporting nothing to run.

### Step 5 — Dependency-order the tasks

1. Resolve dependencies by exact ID or unique descriptor suffix.
2. Treat `done` dependencies as satisfied.
3. Add edges between tasks and their dependencies.
4. Report missing or non-done dependencies as `blocked_by_dep`.
5. Run a stable topological sort by task ID.
6. Treat dependency cycles as a hard failure.

### Step 6 — Output the ordered list and return

```
Execution order:
1. <task-id>
2. <task-id>
...
```

Return the selected `plan_id` and the `ordered` list.

---

## Procedure: RunPlan(ordered_task_list, repo_root, plan_id, finish_policy, mode)

`mode` is `interactive` when invoked via the no-argument entry point, or
`unattended` when invoked via `plan=<plan-id>` (with or without `finish=defer`,
including every `/varde-orchestrate` invocation). Steps branch on `mode` only
where noted.

### Step 0 — Confirm the execution location and check the resume gate

`SKILL.md` step 3 selected the current checkout or an optional worktree before
`RunPlan` starts. Confirm that location in the run-state file before proceeding.
Apply `DISPATCH.md`'s resume gate in full. Then derive progress from each task's
frontmatter. Surface inconsistent commit or Progress evidence rather than
inferring its outcome.

### A — Execute tasks sequentially

Apply `DISPATCH.md` to `ordered_task_list`: derive the next dependency-ready
task, execute it in the selected location, and run
`execute -> /varde-simplify -> verify` per `EXECUTION.md`. Delegate only when
the task benefits from fresh context. Record the outcome in the run-state file,
then re-derive the next ready task. Repeat until every task is `done` or
`blocked`.

Before dispatching each task, apply the fit gate. The plan targets a Claude
5-class executor. Always required per task: one named public behavior or workflow
rule changes, no hidden architecture/product/scope choice left for execution, a
small verification command set, and a clean stop condition. The task also needs
key coverage areas for its own `#### Verification` checks (find or write the
right test yourself) and an identified subsystem/module to touch (locate it via
code_query/dependents — no exact file path required). This is a defense-in-depth
re-check of what `DECOMPOSITION.md` already applied when the task was authored.

If a task fails the fit gate:
- In unattended mode, stop the Plan Run immediately as a Failure State. Report
  the failed checks and say the task must be replanned or split.
- In interactive mode, present the failed checks and ask whether to abort or
  skip that task. Do not dispatch it.

### B — Determine outcome per task

After a task executor completes, read that task's own `tasks/<task-id>.md`
frontmatter `status`:
- `blocked` → go to step C.
- `done` → go to step D.

### C — Handle a blocked task

A task blocks after `MAX_TASK_RETRIES` is exhausted or it reports a blocker
(`EXECUTION.md`).

**If `mode` is `unattended`:** this is a Failure State — stop immediately, leave
the selected working state as-is, and report to the caller (no partial summary beyond the
failure reason). There is no parallel work to continue.

**If `mode` is `interactive`:** present:

```
Task <task_id> is blocked: <reason from its Progress section>.
Options: ["Retry", "Skip this task", "Abort"]
```

- **Retry**: re-dispatch the task (back to step A for this task only).
- **Skip this task**: continue with the rest of the plan (its dependents will be
  reported as `blocked_by_dep`).
- **Abort**: stop the Plan Run; print partial summary.

### D — Handle a done task

The task executor already committed its work into the selected execution location
(`DISPATCH.md`'s commit-per-task). There is no integration stage.

**If `mode` is `unattended`:** add the task to `done_tasks` and continue — no
per-task diff review, since there is no user to ask.

**If `mode` is `interactive`:** show what the task produced and offer to
continue or revert:

```bash
git log --oneline -1
git show --stat HEAD
```

```
Task <task_id> is complete.

<log and diff output>

Options: ["Continue", "Revert"]
```

- **Continue**: add the task to `done_tasks`, continue to the next task.
- **Revert**: discard that task's commit with `git revert`; stop the Plan Run
  and print a partial summary. Preserve unrelated local changes.

### E — After the loop, print the summary

```
Plan Run complete.

Results:
- done: <task-id>, <task-id>, ...
- skipped: <task-id>, ...
- blocked: <task-id>, ...
```

(Omit any category that is empty.)

### F — Plan Wrap-up

After printing the summary, read every `tasks/<task-id>.md` file in the plan
directory — present the wrap-up only when every task's frontmatter shows
`status = "done"`.

If `finish_policy` is `defer`, output:

```
Plan implementation complete.
Finish deferred to caller.
```

Then stop without setting the plan's status to completed. (`/varde-orchestrate`
never uses `defer` — it runs each plan to completion before the next.)

Before completing the plan, run `/varde-review`. Delegate it only when the
current harness exposes a useful review agent. Pass this context:
- Review target type: `plan`
- Plan ID: `<plan-id>`
- Plan goal
- Plan-level acceptance criteria, copied verbatim (if any)
- Completed task IDs and each task's `#### Verification` evidence
- Verification evidence gathered during the Plan Run

The review validates plan-level acceptance criteria and coding standards. It
must not modify source files. Display its findings before continuing.

After the review, resolve its findings in **one bounded round** — no re-review
loop:

1. If the review produced any findings, run `/varde-review-fix mode=build`.
   Pass the review ID and `plan_context` (plan
   goal, plan-level acceptance criteria, each completed task's `creates`/`modifies`
   scope). In `mode=build` the executor attempts every finding regardless of
   label, escalating to the human only when the fix would conflict with the
   plan's AC/spec or change functionality outside the plan's scope. Wait for it
   to complete.
2. Display only the escalated findings (if any) — a gate tripped, so these need
   a human decision. Everything else has been fixed and verified. Any finding
   still open after this single round is **reported as deferred, not
   re-looped**.
3. Check whether `review-fix` created any companion action-item plans (per
   `varde-review-fix`'s `references/COMPANION-PLAN.md`). If any exist, do not
   complete this plan — report the companion plan(s). The current plan stays in
   its prior status until those are resolved.
4. If there are no findings, none escalated, and no companion action-item plans —
   proceed to completion.

Walk each `## Acceptance criteria` item in the plan `plan.md` body. For each,
verify the condition is satisfied and edit `plan.md` directly to toggle `- [ ]`
to `- [x]` for confirmed items. If any item cannot be confirmed, surface it as a
blocker and stop — do not complete a plan with unconfirmed acceptance criteria.

Completion is automatic once every gate above clears — no manual
Complete/Postpone prompt. Edit the plan's `plan.md` frontmatter `status:` to
`completed`. Stage only the plan file and commit: `git add
memory-bank/working/plans/<plan-id>/plan.md && git commit -m "plan: mark
<plan-id> completed"`.

When using the local default, show the completed diff in place. When step 3
created a worktree (`created=true`), offer **Merge** or **Stop** using
`references/INTERVIEW.md`, defaulting to Merge — the user can't see the change
in their own checkout until it's merged. Merge through `varde-worktree`, then
clean it up. Stop is the explicit opt-out: it leaves the committed worktree
isolated for later integration, and the user is told where it lives. If
`create` returned `created=false` (nested inside a caller's worktree), do
neither — the owner merges.

After local completion or a worktree merge, move any plan whose status is terminal
(`completed` or `archived`) into an `archive/` subdirectory if that's the repo's
convention, preserving its status as-is. Stage only the moved plan paths, then
commit: `git add <moved-plan-path> && git commit -m "cleanup: archive drift
fixes"`. Skip the commit if nothing changed.

---
