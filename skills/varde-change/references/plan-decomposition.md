# Task decomposition

- Turn a settled plan's acceptance criteria into the smallest useful tasks: one task for a single bounded outcome, otherwise a dependency DAG with one observable outcome per task. Split only when a task has independent value or one builder cannot complete it safely.
- State each task as what to build, `#### Acceptance criteria` (assert preferred), `depends_on`, `owns`, `status`, and a short `#### Progress`.
- `owns` holds the coarsest directory, glob, or exact file pattern that does not overlap a same-wave task, including tests and helpers; list other paths a task may touch in plan `shared:`. Use `varde map` for consumers and generated/deleted paths and their readers, and add dependencies for
  consumers.
- Execution-wave computes overlap by glob intersection; keep genuinely overlapping tasks in separate waves.
- Keep dependency and risk context and explicit checks in each task.
- No workspace-wide or full-suite asserts in task files; the integration gate owns them.
- Follow `assets/TASK-TEMPLATE.md`; validate tasks before approval with
  `varde plan validate`.
- An unsettled interface: stop decomposing; return to the plan growth loop
  (plan mode) or hand off to `varde-change plan`.

- Use a child dependency only when the whole task needs its predecessor.
- `posture` is a builder load hint and does not affect scheduling.
- Compare ownership with active plans and serialize or split shared writes.
- Follow direct user instructions, then repository policy, then test-first for
  behavior changes.
- Before approval, check verification commands against the base and record expected failures and generated writes.
- Present the breakdown for interactive review; unattended runs skip the pause.
- Identify the longest dependency path and advance it when capacity is limited.
- Use unique kebab-case task ids.
