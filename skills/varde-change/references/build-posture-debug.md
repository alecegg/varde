# Debug Posture

## Debug mode

Run in exactly one mode, and tell the user which in plain words, such as
"Diagnosing only; I won't change code":

- `diagnose` for diagnosis-only requests: run Phases 1–4, then stop and report
  the evidence. Production source is read-only — no fix, no regression test, no
  commit, and any instrumentation stays outside production source.
- `fix` for a requested bug fix or regression repair: all phases.

Apply `references/review-gates.md` before implementation edits and at
completion. Reuse an unchanged approved plan verdict supplied by the caller.

## Evidence contract

Report `debug_evidence` in chat, in this field order; when a task file exists,
also append it under its `#### Progress`:

- `reproduction`: the deterministic command, fixture, and observed symptom.
- `hypotheses`: the strongest supported, falsifiable hypothesis first;
  distinct alternatives when the evidence does not isolate the cause.
- `experiments`: the result of testing each selected hypothesis.
- `cause`: the root-cause explanation supported by the experiments.
- `verification`: the regression check and the final verification result.

For `fix`, `reproduction`, `hypotheses`, and `experiments` must be non-empty
before any production edit; a completed fix adds `cause` and `verification`.
A `diagnose` report may leave `cause` uncertain, but must state the evidence
limit and preserve the reproduction command. If a required field is missing,
stop before mutation and report it — never substitute a passing smoke check.

## When progress stops

For a task, follow the retry budget in `references/build-dispatch.md`.
Standalone debugging has no numeric retry budget here. When progress is blocked
or another fix attempt would repeat a failed approach, stop and apply
`references/build-retry-reassessment.md` before attempting another fix.
Report the reassessment in chat alongside `debug_evidence`.

## Phase 1 — Build a feedback loop

Build a tight pass/fail check that fails on _this_ bug; use it for bisection,
hypothesis testing, and instrumentation. Prefer: failing test > diffed CLI
run > harness/replay > fuzz/bisect; manual repro last, captured.

Make the loop fast, sharp (assert the specific symptom, not "didn't crash"),
and deterministic (pin time, seed RNG, isolate filesystem, freeze network). For
a non-deterministic bug, raise the reproduction rate rather than chasing a
clean repro.

Phase 1 is done when you can name **one command**, already run with its output
shown, that asserts the user's exact symptom. If you cannot build one, stop:
list what you tried and ask for access to the reproducing environment, a
captured artifact, or permission to add temporary instrumentation.

## Phase 2 — Reproduce and minimize

Confirm the loop produces the failure the **user** described, not a different
one nearby. Minimize to the smallest scenario that still goes red, re-running
the loop after each cut. The minimal repro becomes Phase 5's regression test.
Record `reproduction` before ranking hypotheses.

## Phase 3 — Hypothesize

Start with the strongest evidence-backed hypothesis. Make it falsifiable:
"if `<X>` is the cause, changing `<Y>` makes the bug disappear." State it
before testing. Add distinct alternatives when evidence does not isolate the
cause or the first test fails, then rank them by supporting evidence. Record
one `experiments` result per tested hypothesis; an untested hypothesis is not
evidence for a fix.

## Phase 4 — Instrument

Each probe tests one Phase 3 prediction, changing one variable at a time. Tag
every debug log with a unique prefix (e.g. `[DEBUG-a4f2]`) so cleanup is a
single grep. For a performance regression, establish a baseline (timing
harness, profiler, query plan) before bisecting.

## Phase 5 — Fix and regression test

Write the regression test **before** the fix, at a seam that exercises the bug
as it occurs at the call site; a shallow seam, such as a single-caller test for
a bug that needs several, gives false confidence. Watch it fail, apply the fix,
watch it pass, then rerun the Phase 1 loop against the original scenario — a
passing command alone never proves the fix. If no correct seam exists, that is
the finding: note it for the `refactor` posture rather than restructuring
mid-fix.

Populate `cause` from the experiment that explains the symptom, and
`verification` only after the regression test and the original reproduction
both pass.

## Phase 6 — Cleanup

Before declaring done:

- [ ] All `[DEBUG-...]` instrumentation removed (`grep` the prefix).
- [ ] Throwaway prototypes deleted.
- [ ] The hypothesis that proved correct is stated in the commit message.

After the defect is verified, complete the task per `references/build-execution.md`
Completion: transition it, then commit once, stating the hypothesis that
proved correct in the commit message. Standalone (no task file): commit only
when asked.
