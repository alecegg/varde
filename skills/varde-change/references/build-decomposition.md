# Task decomposition

Break a settled spec and its plan-level acceptance criteria — `plan.md`, or the
minimal plan synthesized for ad-hoc work — into `tasks/<task-id>.md` files from
`assets/TASK-TEMPLATE.md`. Run once per plan run, before the first task.

## Check the edge cases first

Before decomposing — even for a planned change, since ad-hoc work never passed
through planning — check whether one of these applies:

- The goal names a shared symbol, type, or interface, which may affect many
  files (with `varde-code` available, run `symbol_blast_radius` rather than
  guessing from package structure): wide refactor = expand, N migrate batches,
  contract, plus an integrate task if batches can't stay green.
- The work deletes a generated or intermediate file another task may read:
  deletion = the three greps — draft task bodies for the path, tests for
  hardcoded paths under the deleted dir, and dependents/importers of the
  deleted source.

## Doc tasks

Only when asked: a doc task writing `<knowledge>/reference/` or
`<knowledge>/flows/`, depending on all implementation tasks.

## Build the breakdown

Require per task: an observable outcome; expected files touched *if already
known* — otherwise say so and let the executor find them; dependencies; risks;
the `assert:`/`retrieve:` checks proving the slice works; and
`#### Test approach` with one profile — `tdd`, `regression`,
`characterization`, `smoke`, or `not-applicable` — and a one-line rationale.
Do not require a step count or a named test function.

Profile authority: direct user instructions outrank repository policy, which
outranks the decomposition default; name a directive in the rationale when one
set the profile. Default behavior changes to test-first. Have the independent reviewer approve
any alternative with its reason and expected result per `references/review-gates.md`;
fragile legacy code may need characterization, and packaging may need smoke checks.

Declare every written path in `modifies`, `creates`, and `renames`; write each
rename as `old/path -> new/path`. List shared databases, snapshots, and other
external state the task or its checks use or change in
`verification_resources`, using stable resource names. Use `[]` when a
category is empty. If an ownership category is unknown, omit that field so
automatic scheduling stays serial.

## Research and design

Investigate directly; codebase unknowns never become research tasks —
`kind: research` is for lasting external output. Unsettled interface → Design
It Twice (`references/plan-grow-doc.md`) first.

## Size check

A task is the smallest execution-safe unit: apply this to every task, and
rewrite and re-check any that fails.

- Exactly one public behavior or workflow rule changes (one CLI subcommand
  behavior; one skill rule or decision).
- No architecture, product, or scope choice is left for execution.
- Verification is one command or a small named set, and the task stops cleanly.
- Prefer vertical slices through a public interface; use a layer slice only when
  a foundation must exist before any behavior is testable. With `varde-code`,
  narrow a task on a `hotspots` file.
- A schema/persistence change names the file where the schema lives, found by
  reading, not analogy.

Failing shapes: "wire everything"; unrelated contracts together; tests that pass
only after later tasks; core plus several adapters at once; guessed file lists.

## Present and record

Interactive: show the breakdown as a table and pause once for missing,
wrong-scoped, or badly split tasks, then proceed. An unattended run skips the
pause.

Write each task from `assets/TASK-TEMPLATE.md` with populated `modifies`,
`creates`, `depends_on`, and `status: todo`. Task IDs are kebab-case with no
date prefix; ensure uniqueness by globbing every plan's `tasks/*.md`. Author
them in the selected execution location. Commit the initial task files once
when plan storage is tracked. Pass the ordered list to
`references/build-dispatch.md`. Readiness is computed live from `depends_on`,
never stored.
