# Dispatch tasks

Read this before running a plan's tasks. Executors run on a cheaper, faster
model, so the orchestrator delegates every task and implements none itself.

## Check drift once

Before the first wave, check that the plan's assumptions still hold. Baseline:
a tracked plan's authoring commit (`git log -n1 --format=%H -- <plan-path>`),
otherwise the HEAD the run started from. Skim the files in the plan's scope for
changes since then (`detect_changes`, or `git log --oneline -- <paths>`).
Proceed past benign drift; drift that invalidates the plan moves `plan.md` to
`blocked`.

## Choose the next wave

Before each wave run `scripts/resolve-execution-wave.py --repo-root <checkout>
<plan-dir>`; report `blocked_by_dep` and `reasons`; exit 3 = cycle, a hard
failure. Its `next_wave` lists tasks safe to run together; you pick the
strategy. You may run fewer of them together, never more: never combine tasks
from different resolver runs or pair tasks named in `conflicts`. Recalculate
after each wave until every task is `done` or `blocked`, or `next_wave` is
empty — that ends the loop; report any remaining `todo` tasks as
`blocked_by_dep`.

If any wave task has `requires_signoff: true`, ask for explicit sign-off before dispatch; unattended runs halt.
Absent or false means proceed without a sign-off prompt; only the plan author sets the field.

## Usage before a wave

Read `varde-workflow config get usage_limit --json` when available: a successful
`data.value` is the configured threshold (`80%` or `$520`); a `not_set`
negative result means no threshold is configured. For a genuine host usage
percentage, an unset threshold defaults to 80%. Compare each reported active
window (for example, five-hour and seven-day) with the percentage threshold.
At or above it, pause before launching the wave and report the window, observed
percentage, and reset time. Do not infer a percentage from cost or tokens.

In Claude Code, `npx -y ccusage@latest blocks --active --json` can supply an
active block's `costUSD` and `endTime` in `blocks[]`, but no quota percentage.
Compare `costUSD` only with a configured dollar threshold; at or above it,
pause and report the cost, block, and end time. With no comparable signal or
when a usage tool fails, skip the check silently. An invalid configured value
is an input error: report it and hold the wave until corrected. Recheck the
source before resuming; elapsed time alone does not clear the pause.

## Strategies

Before choosing a strategy, classify each selected task's posture from its
title, context and Out of scope section per `references/build-plan.md`. If any
selected task is a spike, run that task serially (inline when no executor is
available), then resolve a fresh wave. Never put a spike in a parallel wave;
non-spike tasks retain the normal parallel eligibility.

| Strategy | Use when | Who executes |
|---|---|---|
| `parallel` | `execution=auto` and `next_wave` holds two or more tasks | one `executor` per task, each in its own worktree: follow `references/build-parallel.md` |
| `serial` | `execution=serial`, or `next_wave` holds one task | one `executor` subagent per task, one at a time, in the current checkout; refactor posture uses its [dedicated worktree procedure](build-posture-refactor.md) |
| `inline` | `execution=inline`, or no `executor` agent is available | the current agent, one task at a time |

Announce each wave's strategy and task ids.

## Dispatch an executor

Move the task to `in_progress` (`varde-workflow transition <task.md>
in_progress --json` when on PATH; states and legal moves:
`references/varde-workflow-cli.md`). Brief the executor with the task file
path, its posture (`plan-execution` | `spike` | `debug` | `refactor`), its
`#### Verification` checks, its `modifies`/`creates`/`renames` paths and
`verification_resources`, the execution location, bounded context, and
`references/build-execution.md`. Include the resolved absolute `<working>` and
`<knowledge>` paths. The executor uses those paths and does not re-resolve them.
Include the independent pre-edit verdict, approved verification approach, and
any pending aggregate implementation review per `references/review-gates.md`.
Obtain a missing verdict before dispatch; material drift returns to that gate.

The executor reads `references/build-execution.md` before its first tool call,
runs `execute → verify`, with `varde-review simplify` between them per
build-execution Completion, and owns its task file: status,
`#### Progress`, and evidence. That ownership applies to serial and inline execution in the owning approval
checkout only; isolated workers return evidence, and a parallel wave follows `references/build-parallel.md`. The
orchestrator alone touches `plan.md` and other tasks, and reads each
executor's result, including obstacles, before the next wave.

Before accepting a completed spike, confirm its question/approach/answer and
verification evidence, and that its own exploratory source edits were reverted.
Skip the source commit/ownership audit only for spikes; preserve unrelated edits.

Before accepting a completed implementation task, compare `git diff-tree --no-commit-id
--name-only --no-renames -r <task-commit>` with the task's `modifies`,
`creates`, and both sides of each `renames` entry (repo-relative paths).
Exclude the task's own tracked task file. If ownership fields are absent,
skip this check. Any stray path gets one corrective re-dispatch with its exact
path list, counting toward the bounded retry below; do not accept the task or
start its dependents until the commit scope is corrected. Preserve unrelated
edits when correcting a serial commit.

## Bounded retry

An executor stops after two failed attempts at one approach and reports the
task `blocked`. Re-dispatch it once with the specific failure, the current
diff, its `#### Verification` checks, and prior progress — never a blind rerun.

If that fails too, the task stays `blocked`. Before reporting or offering a
retry, apply `references/build-retry-reassessment.md` and record it in
`#### Progress`. Keep the existing retry budget and build-plan-run.md controls
(unattended: halt; interactive: Retry/Continue/Abort).

## Review checkpoints

For a persisted plan, pass its `review init` subject id and the parent's
resolved `<working>`/`<knowledge>` paths to every executor. Tasks inherit that
subject; do not initialize a separate subject for a task. Before moving a
backlog plan or a task into implementation, run:

```sh
varde-workflow review check --subject <subject-id> --checkpoint start --json
```

Before continuing an active plan or interrupted task, run:

```sh
varde-workflow review check --subject <subject-id> --checkpoint resume --json
```

Do not transition an active plan to active again. The CLI also checks gated
transitions. A typed review blocker means hold implementation and resolve or
refresh reviewer evidence; do not treat it as a dependency result.
Use `readiness.data.planning_ready` to select dependency-ready work and
`readiness.data.implementation_ready` to decide whether it can start.

For a task in another checkout, load `references/worktree.md` and register its
owned scope before dispatch. Pass the returned binding ID, approval checkout,
and worker path; its start/resume check adds `--repository`, `--worktree`, and
`--binding` together. The parent performs transitions at the approval checkout;
workers return evidence and source commits rather than editing task files.

## Resume check

Status lives in each task's frontmatter; evidence lives in `#### Progress`.
Derive state directly rather than
from a log. Every `done` implementation task needs a matching source commit;
a done spike instead needs question/approach/answer, verification evidence, and
confirmation that its own exploratory source edits were reverted. The next ready task
is the first `todo` task whose `depends_on` are all `done`.

If an implementation task is `done` with no matching source commit, or has commits but no
completion entry in its `#### Progress`, stop and show it rather than inferring
the outcome. A human decides whether to retry, confirm done, or mark it blocked.

An `in_progress` task at resume was interrupted: show its diff and
`#### Progress` and let the user choose resume, restart from clean, or
blocked. Unattended, mark it `blocked` (reason: interrupted) and halt. Surface
each existing `blocked` task and its `#### Progress` at resume. It is
unresolved, not complete; handle it with `build-plan-run.md`'s blocked-task
choice before selecting a wave.
