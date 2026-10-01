# Build a plan or larger change

## Boundaries

- **Git scope:** the plan runner controls the sequence but never edits source
  files. Tasks commit in the selected location, one commit per task, however
  the wave ran; unrelated edits survive. Never push or run `git reset --hard`
  in the shared tree; merge a worktree only through the finish.
- **Unattended failure:** a command failing unexpectedly after retry, a task
  blocking, or the plan entering `blocked` stops execution immediately. Leave
  the working state as-is, report where and why, and merge or clean up nothing.

## 1. Choose a starting action

| The request is | Start |
|---|---|
| An ask to build an existing plan, with no plan named | Read the "Select a plan" section below, present the options, then run the selected plan. |
| A named plan | Build it. |
| An ad-hoc request with dependent outcomes | Create a minimal plan with a best-guess Problem/Solution and a few plan-level Given/When/Then acceptance criteria, confirm it once, then decompose and run it. |
| An uncertain change | Hand off to `varde-change plan`. |

Interactive builds pause for user choices. Unattended builds run a named plan
without pauses, including work dispatched through the orchestrator.

## 2. Load references

Read `references/varde-code-cli.md` only for discovery or relationship
questions.

## 3. Choose the execution location

1. Default to the current checkout.
2. Run `git check-ignore -q <working>/plans/<plan-id>/plan.md` once: ignored
   plan files stay local and never enter a commit; tracked ones follow the
   execution worktree into scoped commits.
3. Isolate other tasks per `references/build-worktree.md` only when the user asks or
   a concrete concurrent-edit risk makes the checkout unsafe; state the reason
   first. Its `created=` result decides who merges.
4. Take `execution=<serial|auto|inline>` for dispatch (default `auto`).

## 4. Decompose and state a posture

If the plan has no task files, decompose per
`references/plan-decomposition.md`, which owns the pause rule. Select each
task's posture from its title, context, and `#### Out of scope` section, state
it, and pass it in the dispatch brief.

| Posture | Select when |
|---|---|
| plan-execution | Default |
| spike | The goal is answering one design question, not implementing it |
| debug | A known bug or regression is the only goal |
| refactor | Behavior-preserving restructuring, the task's `#### Out of scope` section forbids behavior change, or complexity/readability review findings |

## 5. Run tasks

Read `references/build-execution.md` whenever `execution=inline` or no
`varde-executor` agent is available; the task cycle still runs.

1. Read each `tasks/<task-id>.md`; the `id` is the filename.
2. Move the plan to `active` before the first task only when it is `backlog`
   (resume must not run `active` to `active`); commit that transition when plan
   storage is tracked.
3. Run the resume check in the "Dispatch tasks" section below; handle any `blocked`
   task per its Blocked task section before selecting a wave.
4. Resolve and run task waves per the "Dispatch tasks" section below, repeating
   until every task is `done` or `blocked`, or `next_wave` is empty.
   Summarize `done` and `blocked` task IDs, omitting empty categories;
   report remaining `todo` tasks as `blocked_by_dep`. Keep the plan active
   and resumable while any task is not done.

## 6. Finish

When all tasks are done, follow `references/build-finish.md` unless the user
asks to stop before this step.

## Select a plan

1. **List.** Run `scripts/select-plans.py --working <working>`; it keeps
   selectable plans (no groups, drafts, incomplete
   `depends_on` chains or `dependency_cycle` plans), backlog first.
   - `planning_ready` reports dependency availability; `implementation_ready`
     also includes review approval.
   - Keep a plan with a missing review selectable, report that blocker, and
     do not dispatch implementation until its start or resume check passes.
   - `degraded: true` means `varde-workflow` failed for `degraded_plans`, which
     were filtered only by `depends_on` status; say cycles and review blockers
     may be missed.
2. **Report.** Report `excluded_by_dependency`. If `plans` is empty, say
   `No backlog or active plans available. Nothing to run.` and stop.
3. **Present.** Present each option as `<id> - <title>`.

## Dispatch tasks

Read this before running a plan's tasks. Executors run in the background so
the orchestrator stays available to the user. Only `execution=inline` or the
absence of an executor uses the current agent.

### Check drift once

Before the first wave, skim the plan's scope for changes since its baseline
(`detect_changes`, or `git log --oneline -- <paths>`):

- **Baseline:** a tracked plan's authoring commit (`git log -n1 --format=%H --
  <plan-path>`), else the HEAD the run started from.
- **Benign drift:** proceed.
- **Drift that invalidates the plan:** move `plan.md` to `blocked`.

### Choose the next wave

1. Before each wave, run `scripts/resolve-execution-wave.py --repo-root
   <checkout> <plan-dir>` and report its `blocked_by_dep` and `reasons`. Exit
   3 is a dependency cycle, a hard failure.
2. Run any subset of `next_wave` together, never more: never combine tasks
   from different resolver runs or pair tasks named in `conflicts`.
3. A wave task with `requires_signoff: true` (set only by the plan author)
   needs explicit sign-off before dispatch; unattended runs halt.

### Choose a strategy

| Strategy | Use when | Who executes |
|---|---|---|
| `parallel` | `execution=auto` (the default) and `next_wave` holds two or more tasks | one background executor per task, per `wave_mode` in `references/build-parallel.md`; refactor posture uses worktrees |
| `serial` | `execution=serial`, or auto with one task | one background executor at a time in the current checkout; refactor posture uses its [dedicated worktree procedure](build-posture-refactor.md) |
| `inline` | `execution=inline`, or no executor is available | the current agent, one task at a time |

Announce each wave's strategy and task ids.

### Task-file ownership

- **Serial or inline, in the owning approval checkout:** the executor owns its
  task file (status, `#### Progress`, evidence).
- **Parallel executors:** return evidence; the orchestrator records their task
  files.
- **Orchestrator:** alone touches `plan.md` and other tasks, and reads each
  result, including obstacles, before the next wave.

### Tasks in another checkout

Register the task's owned scope per `references/build-worktree.md` before dispatch
and add its binding context to the brief. The parent performs transitions at
the approval checkout; workers return evidence and source commits.

### Dispatch an executor

1. Obtain any missing pre-edit verdict per `references/review-gates.md`;
   material drift returns to that gate.
2. Move the task to `in_progress` (`varde-workflow transition <task.md>
   in_progress --json` when on PATH; legal from `todo` or `blocked`).
3. Brief the executor with:
   - the task file path and posture (`plan-execution` | `spike` | `debug` |
     `refactor`);
   - its `#### Verification` checks, `modifies`/`creates`/`renames` paths, and
     `verification_resources`;
   - the execution location and bounded context;
   - the plan's review subject id and the resolved absolute `<working>` and
     `<knowledge>` paths, used without re-resolving;
   - the independent pre-edit verdict, approved verification approach, and any
     pending aggregate implementation review;
   - `references/build-execution.md`, read before its first tool call.

After each wave, the orchestrator regenerates the plan's listed generated
outputs.

### Accept a result

- Before accepting a completed spike, confirm its question/approach/answer,
  verification evidence, and the revert of its own exploratory source edits.
  Skip the source commit/ownership audit only for spikes; preserve unrelated
  edits.
- Before accepting a completed implementation task, compare its commit with
  the task's declared paths: `scripts/check-task-ownership.py --task <task.md>
  --commit <task-commit>`. Status `stray` (exit 2) gets one corrective
  re-dispatch with the `stray` list, counting toward the bounded retry; `skipped`
  needs no action. Accept the task and start dependents only after the scope is
  corrected, preserving unrelated edits in a serial commit.

### Bounded retry

1. An executor stops after two failed attempts at one approach and reports the
   task `blocked`.
2. Re-dispatch it once with the specific failure, the current diff, its
   `#### Verification` checks, and prior progress; never rerun it blind.
3. If that fails too, the task stays `blocked`: apply
   `references/build-retry-reassessment.md` and record it in `#### Progress`
   before reporting or offering a retry. Then apply the
   [blocked-task choice](#blocked-task).

### Review checkpoints

Tasks inherit the plan's subject; never initialize one per task. Check `start`
before moving a backlog plan or task into implementation, and `resume` before
continuing an active plan or interrupted task:

```sh
varde-workflow review check --subject <subject-id> --checkpoint start --json
varde-workflow review check --subject <subject-id> --checkpoint resume --json
```

- A typed review blocker holds implementation until reviewer evidence is
  resolved or refreshed; it is not a dependency result.

### Resume check

Derive state from each task's frontmatter status and `#### Progress`
evidence, not from a log. Every `done` implementation task needs a matching
source commit. A done spike needs the acceptance evidence above. The next ready
task is the first `todo` task whose `depends_on` are all `done`.

Show these at resume rather than inferring an outcome:

- **Unproven `done`:** an implementation task with no matching source commit,
  or commits without a completion entry in `#### Progress`. Stop; a human
  decides retry, confirm done, or blocked.
- **`in_progress`:** interrupted. Show its diff and `#### Progress`; the user
  chooses resume, restart from clean, or blocked. Unattended, mark it
  `blocked` (reason: interrupted) and halt.
- **`blocked`:** show its `#### Progress`. It is unresolved; apply the
  [blocked-task choice](#blocked-task) before selecting a wave.

### Blocked task

Unattended, a blocked task is a failure state: stop and report the reason.
Interactive, present the reason and offer:

- **Retry:** move the task back to `in_progress` and re-dispatch it alone.
- **Continue** independent work: record the decision and task id in its
  `#### Progress`, leave it `blocked`, resolve a fresh wave, and run only its
  `next_wave`. Dependent tasks stay `todo`, reported as `blocked_by_dep`. With
  no ready work left, stop with the plan incomplete; a later run can retry the
  task after its cause is addressed.
- **Abort:** stop and print a partial summary.
