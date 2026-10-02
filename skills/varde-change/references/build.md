# Build a plan or larger change

## Boundaries

- **Git scope:** the plan runner controls the sequence and, outside `inline`
  execution, never edits source files. Tasks commit in the selected location,
  one commit per task, however the wave ran; unrelated edits survive. Never
  push or run `git reset --hard` in the shared tree; merge a worktree only
  through the finish.
- **Unattended failure:** a command failing unexpectedly after retry, a task
  still blocked after its one re-dispatch (`references/build-recovery.md`), or
  the plan entering `blocked` stops execution immediately. Leave
  the working state as-is, report where and why, and merge or clean up nothing.

## 1. Choose a starting action

| The request is | Start |
|---|---|
| An ask to build an existing plan, with no plan named | Read the "Select a plan" section below, present the options, then run the selected plan. |
| A named plan | Build it. |
| An ad-hoc request with dependent outcomes | Create a minimal plan with a best-guess Problem/Solution and a few plan-level Given/When/Then acceptance criteria, confirm it once, decompose it, initialize its subject per `references/review-gate-plan.md` §1, then run it. |
| An uncertain change | Hand off to `varde-change plan`. |

Interactive builds pause for user choices. Unattended builds run a named plan
without pauses, including work dispatched through the orchestrator. Read
`references/varde-code-cli.md` only for discovery or relationship questions.

## 2. Choose the execution location

1. Default to the current checkout.
2. Run `git check-ignore -q <working>/plans/<plan-id>/plan.md` once: ignored
   plan files stay local and never enter a commit; tracked ones follow the
   execution worktree into scoped commits.
3. Isolate other tasks per `references/build-worktree.md` only when the user asks or
   a concrete concurrent-edit risk makes the checkout unsafe; state the reason
   first. Its `created=` result decides who merges.
4. Take `execution=<serial|auto|inline>` for dispatch (default `auto`).

## 3. Decompose and state a posture

If the plan has no task files, decompose per
`references/plan-decomposition.md`, which owns the pause rule and the
`posture:` field. Take each task's posture from that field, else select it
from its title, context, and `#### Out of scope` section; state it and pass
it in the dispatch brief. Never add `posture:` to an approved task file.

| Posture | Select when |
|---|---|
| plan-execution | Default |
| spike | The goal is answering one design question, not implementing it |
| debug | A known bug or regression is the only goal |
| refactor | Behavior-preserving restructuring, the task's `#### Out of scope` section forbids behavior change, or complexity/readability review findings |

## 4. Run tasks

Read `references/build-execution.md` whenever `execution=inline` or no
`varde-executor` agent is available; the task cycle still runs.

1. Read each `tasks/<task-id>.md`; the `id` is the filename.
2. Obtain any missing pre-edit verdict (Dispatch an executor, step 1), then
   run the `start` (backlog or blocked) or `resume` check per Review
   checkpoints below; then move the plan to `active` before the first task
   only when it is `backlog`, or `blocked` once its blocker is resolved
   (resume must not run `active` to `active`); commit that transition when
   plan storage is tracked.
3. Read `references/build-recovery.md` when the plan is `active` or any task is
   `in_progress`, `blocked`, or `done`, and run its resume check before
   selecting a wave. A fresh `backlog` plan with all tasks `todo` skips it.
4. Resolve and run task waves per the "Dispatch tasks" section below, repeating
   until every task is `done` or `blocked`, or `next_wave` is empty.
   Summarize `done` and `blocked` task IDs, omitting empty categories;
   report remaining `todo` tasks as `blocked_by_dep`. Keep the plan active
   and resumable while any task is not done.

## 5. Finish

When all tasks are done, follow `references/build-finish.md` unless the user
asks to stop before this step.

## Select a plan

1. **List.** Run `scripts/select-plans.py --working <working>`; it keeps
   only `planning_ready` plans (dependencies available) outside dependency
   cycles, backlog first.
   - `implementation_ready: false`: keep it selectable, report the blocker,
     and do not dispatch implementation until its start or resume check passes.
   - `degraded: true`: apply the fallback rule in
     `references/varde-workflow-cli.md` to `degraded_plans`; say cycles and
     review blockers may be missed.
2. **Report.** Report `excluded_by_dependency`. If `plans` is empty, say
   `No backlog or active plans available. Nothing to run.` and stop.
3. **Present.** Present each option as `<id> - <title>`.

## Dispatch tasks

Read `references/orchestration.md` for posture, cap, and briefs.

### Check drift once

Before the first wave, skim the plan's scope for changes since its baseline
(`detect_changes`, or `git log --oneline -- <paths>`):

- **Baseline:** a tracked plan's authoring commit (`git log -n1 --format=%H --
  <plan-path>`), else the HEAD the run started from.
- **Benign drift:** proceed.
- **Drift that invalidates the plan:** move `plan.md` to `blocked`.

### Choose the next wave

1. Before each wave, run `varde-workflow execution-wave --repo-root
   <checkout> <plan-dir> --json` and report `data.blocked_by_dep`,
   `data.reasons`, and `data.wave_mode`. Exit 3 is a dependency cycle, a
   hard failure.
2. Run any subset of `data.next_wave` together, never more: never combine tasks
   from different resolver runs or pair tasks named in `data.conflicts`.
3. Check each wave task file's frontmatter: `requires_signoff: true` (set
   only by the plan author) needs explicit sign-off before dispatch; unattended runs halt.

### Choose a strategy

| Strategy | Use when | Who executes |
|---|---|---|
| `parallel` | `execution=auto` (the default) and `next_wave` holds two or more tasks | one background executor per task, per `wave_mode` in `references/build-parallel.md`; refactor posture uses worktrees |
| `serial` | `execution=serial`, or auto with one task | one background executor at a time in the current checkout; refactor posture follows `references/build-posture-refactor.md` Bootstrap (worktree only when other work is staged) |
| `inline` | `execution=inline`, or no executor is available | the current agent, one task at a time |

Announce each wave's strategy and task ids.

### Task-file ownership

- **Serial or inline, in the owning approval checkout:** the executor owns its
  task file's `#### Progress`, evidence, and any move to `blocked`; the
  orchestrator moves it to `done` (Accept a result).
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
   in_progress --json`; legal from `todo` or `blocked`). A corrective
   re-dispatch of a task already `in_progress` skips this step.
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
- When an executor returns `blocked` or reports a failed attempt, read
  `references/build-recovery.md` and follow its retry and blocked-task rules.
- Before accepting a completed implementation task, compare its commit with
  the task's declared paths: `varde-workflow check-task-ownership --task
  <task.md> --commit <task-commit> --json`. When `data.status` is `stray` (exit 2), re-dispatch once
  with `data.stray`, counting toward the bounded retry in
  `references/build-recovery.md` (read it before that re-dispatch); `skipped`
  needs no action. The corrective executor amends the task commit only when
  `git rev-parse HEAD` in its execution branch equals that commit, else
  reports `blocked`; rerun the ownership check on the new SHA it reports.
  Shared-checkout waves check paths before committing instead. Accept the
  task only after the scope is corrected.

Accepting any task moves it to `done` and commits its task file when plan
storage is tracked, preserving unrelated edits; then start its dependents.

### Review checkpoints

Tasks inherit the plan's subject; never initialize one per task. Check `start`
before moving a backlog or blocked plan, or a task, into implementation, and
`resume` before continuing an active plan or interrupted task:

```sh
varde-workflow review check --subject <subject-id> --checkpoint start --json
varde-workflow review check --subject <subject-id> --checkpoint resume --json
```

- A typed review blocker holds implementation until reviewer evidence is
  resolved or refreshed; it is not a dependency result.
