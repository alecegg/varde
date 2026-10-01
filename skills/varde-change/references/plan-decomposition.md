# Task decomposition

Break a settled spec and its plan-level acceptance criteria (`plan.md`, or the
minimal plan synthesized for ad-hoc work) into `tasks/<task-id>.md` files from
`assets/TASK-TEMPLATE.md`. Run once while finalizing a plan, or at build for
an ad-hoc plan without tasks; a single bounded outcome writes one task directly from that template instead
(plan AC → its Verification), skipping the edge-case checks below.

## 1. Check the edge cases

Check these:

| The goal | Decompose as |
|---|---|
| Names a shared symbol, type, or interface (with `varde-code`, run `symbol_blast_radius` rather than guessing from package structure) | Wide refactor: expand, N migrate batches, contract, plus an integrate task if batches can't stay green |
| Deletes a generated or intermediate file another task may read | Deletion: grep draft task bodies for the path, tests for hardcoded paths under the deleted dir, and dependents/importers of the deleted source |
| Creates or renames a path another task body mentions | File pointer: grep draft task bodies for the new path and add `depends_on` |
| Has an unsettled interface | Stop decomposing and hand off to `varde-change plan` |

Investigate codebase unknowns directly; `kind: research` is only for lasting
external output. Add a doc task (writing `<knowledge>/reference/` or
`<knowledge>/flows/`, depending on all implementation tasks) only when asked.

## 2. Build the breakdown

Require per task (no step count or named test function):

- an observable outcome;
- expected files touched, if known; otherwise say so and let the executor find
  them;
- dependencies and risks;
- the `assert:`/`retrieve:` checks proving the slice works;
- `#### Test approach`: one profile (`tdd`, `regression`,
  `characterization`, `smoke`, or `not-applicable`) and a one-line rationale.

Profile authority, highest first:

1. Direct user instructions.
2. Repository policy.
3. The default: test-first for behavior changes.

Name the directive in the rationale when one set the profile. Any other
alternative (characterization for fragile legacy code, smoke for packaging)
needs independent reviewer approval per `references/review-gates.md`.

## 3. Declare ownership

- Declare every written path in `modifies`, `creates`, and `renames` (each
  rename as `old/path -> new/path`).
- Name every shared database, snapshot, or other external state the task or
  its checks use or change in `verification_resources`.
- The plan lists generated outputs and their generator commands; no task owns
  them.
- Use `[]` for an empty category; omit a field whose contents are unknown so
  automatic scheduling stays serial.
- A `spike` posture task owns no paths by design: set `kind: spike` with
  empty `modifies`/`creates`/`renames` so `varde-workflow transition` skips
  the ownership check instead of rejecting it.

## 4. Check each task's size

A task is the smallest execution-safe unit. Rewrite and re-check any task that
fails one of these:

- Exactly one public behavior or workflow rule changes, with one observable
  outcome and no open choices.
- Estimated peak context is 100k or less: `20k + 3 × (bytes of files it must
  read ÷ 4) + 5k per verification run`. Include each estimate in the breakdown
  table.
- A schema/persistence change names the file where the schema lives, found by
  reading, not analogy.

## 5. Present and record

1. Interactive: show the breakdown as a table and pause once for missing,
   wrong-scoped, or badly split tasks. Unattended runs skip the pause.
2. Write each task from `assets/TASK-TEMPLATE.md` in the plan's `tasks/`
   directory, with populated `modifies`, `creates`, `depends_on`, and
   `status: todo`. Task IDs are kebab-case with no date prefix, unique across
   every plan's `tasks/*.md`. Readiness is computed live from `depends_on`,
   never stored.
