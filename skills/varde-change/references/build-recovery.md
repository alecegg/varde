# Recover a resumed or blocked build

## Bounded retry

1. Executors stop after two failed attempts and report the task `blocked`.
2. Re-dispatch it once, attended or unattended, with the specific failure,
   the current diff, its `#### Verification` checks, and prior progress;
   never rerun it blind.
3. If that fails too, the task stays `blocked`: apply
   `references/build-retry-reassessment.md` and record it in `#### Progress`
   before reporting or offering a retry. Then apply the
   [blocked-task choice](#blocked-task).

## Resume check

Derive state from each task's frontmatter status and `#### Progress`
evidence, not from a log. Every `done` implementation task needs a matching
source commit. A done spike needs its question/approach/answer, verification
evidence, and the revert of its exploratory source edits. The next ready task
is the first `todo` task whose `depends_on` are all `done`.

Show these at resume rather than inferring an outcome:

- **Unproven `done`:** an implementation task with no matching source commit,
  or commits without a completion entry in `#### Progress`. Stop; `done` is
  terminal, so a human decides: confirm done, or add a follow-up task.
- **`in_progress` awaiting acceptance:** a completion entry in `#### Progress`
  and a matching source commit (for a spike, its question/approach/answer and
  revert). Accept it through the plan build's Accept a result step.
- **Other `in_progress`:** interrupted. Show its diff and `#### Progress`;
  the user chooses resume, restart from clean, or blocked. Unattended, mark it
  `blocked` (reason: interrupted) and halt.
- **`blocked`:** show its `#### Progress`. It is unresolved; apply the
  [blocked-task choice](#blocked-task) before selecting a wave.

## Blocked task

Unattended, a blocked task is a failure state: stop and report the reason.
Interactive, present the reason and offer:

- **Retry:** move the task back to `in_progress` and re-dispatch it alone.
- **Continue** independent work: record the decision and task id in its
  `#### Progress`, leave it `blocked`, resolve a fresh wave, and run only its
  `next_wave`. Dependent tasks stay `todo`, reported as `blocked_by_dep`. With
  no ready work left, stop with the plan incomplete; a later run can retry the
  task after its cause is addressed.
- **Abort:** stop and print a partial summary.
