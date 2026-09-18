# Execution Reference

Read at the start of every plan. It captures the execution discipline for
implementing tasks.

## Task kind dispatch

A task with `kind: research` follows `references/build-research-task.md` instead
of the cycle below — it produces a lasting external output (decision record,
prototype, reference doc), so there is no failing test to write. Anything else
is an implementation task.

## Drift check

Once per plan run, before the first task, sanity-check that the plan's
assumptions still hold. Derive the baseline from git: for a tracked plan, its
authoring commit (`git log -n1 --format=%H -- <plan-path>`); otherwise the HEAD
the run started from. Skim the files named in the plan's scope for drift since
then, with `detect_changes` for symbol-level precision or
`git log --oneline -- <paths>`.

Then per task, before its execution frame: check the task's `modifies` and
`creates` against the working tree — uncommitted or unexpected changes, or a
`creates` path that already exists, are drift.

Benign drift (unrelated exports, cosmetic renames) gets a note and you proceed
with current reality. Drift that invalidates the plan's assumptions is a
blocker. This is a judgment call, not a mechanical check.

## TDD cycle

Write or update a failing test first, then implement the smallest change that
satisfies it, then verify. Failing-pattern tests are acceptable when the
production code already exists — do not invent production code just to write a
test. Refactoring is not part of this loop; it belongs to the
`varde-review simplify` stage that runs after implementation.

Before writing a new test, find what already covers the file (`tests_for_file`,
or the project's test-file convention). Use existing seams by default and follow
nearby tests. Ask the user only when test placement would choose a new public
contract or materially change the testing strategy.

Expected values come from an independent source of truth — a known-good literal,
a worked example, the spec. An assertion that recomputes its expected value the
way the code does is tautological: it passes by construction and can never
disagree with the code.

Map each of the task's `#### Verification` checks to a coverage area, then name
and write the test that best expresses it — a check does not need a test-function
name decided before you have seen the code. A check that resists any coverage at
all is the real mis-scope indicator: mark the task blocked and stop.

Plan-level acceptance criteria are the whole change's contract, verified once at
the end (`references/build-plan-run.md` Section F), not per task.

## Given / Unknowns / Plan / Verification

Before any tool call, write a short execution frame.

- **Given** — the current state of the code and test baseline. Establish it by
  reading the symbols in `modifies` before editing; that body is both your
  evidence and the targeted edit's `old_string`. Files in `creates` don't exist
  yet.
- **Unknowns** — open questions blocking a confident next step. Cap at two. More
  than two means the task is mis-scoped.
- **Plan** — the ordered tool calls you intend to make. Revise after every call
  that changes your mental model.
- **Verification** — the command that will demonstrate the task's checks pass.

Resolve one unknown fully before opening the next. If a tool call neither
resolves an unknown, writes a failing test, nor verifies completion, revise the
plan before continuing.

## Blockers

A blocker is a condition preventing the task's `#### Verification` from passing
without out-of-scope work. Set `status: blocked` in the task's own file, append
the reason to its `#### Progress`, and stop. Do not redesign inline or attempt
pre-condition fixes — the planner decides how to unblock.

When the plan's own assumptions no longer hold (found during the drift check,
before any task is dispatched), that is plan-wide: set `status: blocked` in
`plan.md` and stop. A task worker reports on its own task file and lets the
orchestrator decide whether it escalates.

If the same approach fails repeatedly — a test that will not converge after
three attempts — stop and reassess rather than trying again.

## Static analysis

Whatever lint or scan tooling the project has configured is a candidate list,
never a completion gate. Run it after source edits outside `memory-bank/`, using
the project's own scripts. Fix the real issues; skip a finding only when it is a
genuine false positive or an over-aggressive rule flagging correct code — do not
force-fix correct code to satisfy a rule.

## Completion

Verify the task's `#### Verification` checks pass — every `assert:` command
matching its stated expectation, with every `retrieve:` command's output read as
context. Only then set `status: done` in the task file and append a one-line
entry to its `#### Progress`. That line is the task's execution evidence, which a
resumed or checking run reads.

Commit the task's source paths with a message referencing the task ID, including
its `tasks/<task-id>.md` file when plan storage is tracked. Use `git revert` to
undo a completed task.

A verify-only run skips execution entirely: it loads the plan's tasks and runs
each one's `#### Verification` checks, reporting pass or fail without dispatching
work, deriving readiness, or enforcing dependency order.
