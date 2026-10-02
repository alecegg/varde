# Debug Posture

## Debug mode

Run in exactly one mode and name it to the user in plain words, such as
"Diagnosing only; I won't change code":

| Mode | Use for | Run |
|---|---|---|
| `diagnose` | diagnosis-only requests | Phases 1-4 and Phase 6 cleanup, then report the evidence |
| `fix` | a requested bug fix or regression repair | all phases |

In `diagnose`, production source is read-only: no fix, regression test, or
commit, and instrumentation stays outside production source.

## Evidence contract

Report `debug_evidence` in chat in this field order; when a task file exists,
also append it under its `#### Progress`:

- `reproduction`: the deterministic command and observed symptom, or bounded
  trace/source evidence with its origin, version or time, and reproduction
  limit.
- `hypotheses`, `experiments`, `cause`, `verification`.

Required fields:

- **`fix`:** `reproduction`, `hypotheses`, and `experiments` before any
  production edit; a completed fix adds `cause` and `verification`.
- **`diagnose`:** may leave `cause` uncertain; state the evidence limit.
- **Missing field:** stop before mutation and report it; a passing smoke check
  is no substitute.

## When progress stops

Standalone: no numeric budget. When progress is blocked or another fix
attempt would repeat a failed approach, apply
`references/build-retry-reassessment.md` before another fix and report it alongside
`debug_evidence`.

## Phase 1 — Build a feedback loop

When the failure runs locally, build one fast, deterministic pass/fail command
that asserts the user's exact symptom, run it, and show its output. Use it for
bisection, hypothesis testing, and instrumentation.

- **Without local reproduction:** name the attempts and use a bounded trace
  or versioned source path that supports the symptom, labeled
  **unreproduced**, stating its origin and what it cannot establish, and
  separating observation from what the code suggests.
- **Without either:** stop and ask for the reproducing environment, an
  artifact, or permission to add temporary instrumentation.

## Phase 2 — Reproduce and minimize

1. Confirm the loop produces the failure the **user** described, not a nearby
   one.
2. Minimize to the smallest red scenario; Phase 5's regression test uses it.

## Phase 3 — Hypothesize

1. State a falsifiable hypothesis before testing it.
2. Add distinct alternatives when evidence does not isolate the cause or the
   first test fails; rank them by supporting evidence.
3. An untested hypothesis is not evidence for a fix.

## Phase 4 — Instrument

For `fix`, initialize the review gate after Phase 3 and before the first
production edit (Phase 4 instrumentation in production source, or Phase 5);
`diagnose` needs no gate.

- Tag every debug log with a unique prefix (e.g. `[DEBUG-a4f2]`).

## Phase 5 — Fix and regression test

1. Write the regression test at a seam that exercises the bug as it occurs at
   the call site; a single-caller test for a bug needing several callers gives
   false confidence.
2. Watch it fail, apply the fix, watch it pass.
3. Rerun the Phase 1 loop against the original scenario.

With no correct test seam, obtain pre-edit approval for an alternative that
distinguishes fixed behavior from the defect, or stop and note the testability
gap for the `refactor` posture. When the original scenario cannot run locally,
use the independent verification approved in pre-edit review and report the
original symptom as unverified until checked in its environment.

## Phase 6 — Cleanup

Before declaring done:

- [ ] All `[DEBUG-...]` instrumentation removed (`grep` the prefix).
- [ ] Throwaway prototypes deleted.
- [ ] When committing, state the proven hypothesis in the commit message.

With a task file, complete through `references/build-execution.md`
Completion. A standalone `fix` finishes with the implementation review and
complete checkpoint per `references/review-gates.md` §5; commit only when
asked.
