# Task decomposition

- Turn a settled plan into coherent tasks linked by dependencies. Each task is a feature or module part with one observable outcome; split further only when it will not fit the builder's context.
- Each task states what to build, `#### Acceptance criteria` (assert preferred), `depends_on`, `owns`, `status`, and a short `#### Progress`.

## Task rules

- `owns` is the coarsest directory (`dir/**` or `dir/`), glob, or exact file that does not overlap a same-wave task, including tests and helpers. Other paths a task may touch are in plan `shared:`; genuinely overlapping tasks are in separate waves.
- Serial plans: the gate checks the net diff against plan `scope`. Parallel waves: it checks each task's `owns`.
- Consumers and generated or deleted paths are covered by dependencies, `owns`, or `shared:`, including generated-adjacent files (help snapshots, `docs/sandbox-permissions.md`, script registrations).
- Add a child dependency only when the whole task needs its predecessor. `posture` is a builder load hint and does not affect scheduling.
- Each task keeps its dependency and risk context and explicit checks.
- No workspace-wide or full-suite asserts in task files; the integration gate owns them.
- Tasks use `references/TASK-TEMPLATE.md`; `varde plan validate <task.md>` passes before approval.
- Stop decomposition at an unsettled interface and return to the plan growth loop.
- Precedence: direct user instructions, then repository policy, then test-first for behavior changes.
- Before approval, check verification commands against the base and record expected failures and generated writes.
- Present the breakdown for interactive review; unattended runs skip the pause.
- Task ids are unique kebab-case.
