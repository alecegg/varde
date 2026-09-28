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

- `reproduction`: the deterministic command and observed symptom, or bounded
  trace/source evidence with its origin, version or time, and reproduction limit.
- `hypotheses`: the strongest supported, falsifiable hypothesis first;
  distinct alternatives when the evidence does not isolate the cause.
- `experiments`: the result of testing each selected hypothesis.
- `cause`: the root-cause explanation supported by the experiments.
- `verification`: the regression check and the final verification result.

For `fix`, `reproduction`, `hypotheses`, and `experiments` must be non-empty
before any production edit; a completed fix adds `cause` and `verification`.
Label evidence-backed symptoms **unreproduced** and state the evidence limits.
A `diagnose` report may leave `cause` uncertain, but must state the evidence
limit and preserve the command or artifact. If a required field is missing,
stop before mutation and report it — never substitute a passing smoke check.

## When progress stops

For a task, follow the retry budget in `references/build-dispatch.md`.
Standalone debugging has no numeric retry budget here. When progress is blocked
or another fix attempt would repeat a failed approach, stop and apply
`references/build-retry-reassessment.md` before attempting another fix.
Report the reassessment in chat alongside `debug_evidence`.

## Phase 1 — Build a feedback loop

When the failure runs locally, build a tight pass/fail check for _this_ bug;
use it for bisection, hypothesis testing, and instrumentation. Prefer: failing
test > diffed CLI run > harness/replay > fuzz/bisect; manual repro last, captured.

Make a runnable loop fast, sharp (assert the specific symptom, not "didn't crash"),
and deterministic (pin time, seed RNG, isolate filesystem, freeze network). For
a non-deterministic bug, raise the reproduction rate rather than chasing a
clean repro.

Prefer **one command**, already run with its output shown, that asserts the
user's exact symptom. If local reproduction is unavailable, name the attempts
and use a bounded trace or versioned source path that supports the symptom.
Label it **unreproduced** and distinguish what was observed from what the code
suggests. Without either, stop and ask for the reproducing environment, an
artifact, or permission to add temporary instrumentation.

## Phase 2 — Reproduce and minimize

If a loop runs, confirm it produces the failure the **user** described, not a
different one nearby. Minimize to the smallest scenario that stays red,
re-running after each cut; use it for Phase 5's regression test. Otherwise,
check how the trace or versioned source supports that symptom, keep its origin,
and state what it cannot establish. Record `reproduction` before ranking
hypotheses.

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

Normally write the regression test **before** the fix, at a seam that exercises the bug
as it occurs at the call site; a shallow seam, such as a single-caller test for
a bug that needs several, gives false confidence. Watch it fail, apply the fix,
watch it pass, then rerun the Phase 1 loop against the original scenario. If
the original scenario cannot run locally, use concrete independent verification
approved in the pre-edit review; report the original symptom as unverified
until checked in its environment. If no correct test seam exists, obtain
approval for an alternative that distinguishes fixed behavior from the defect
before editing, or stop and note the testability gap for the `refactor` posture.

Populate `cause` from the experiment that explains the symptom. Record in
`verification` which checks passed and which original symptom remains untested;
do not claim full verification without checking that symptom.

## Phase 6 — Cleanup

Before declaring done:

- [ ] All `[DEBUG-...]` instrumentation removed (`grep` the prefix).
- [ ] Throwaway prototypes deleted.
- [ ] The hypothesis that proved correct is stated in the commit message.

After the defect is verified, complete the task per `references/build-execution.md`
Completion: transition it, then commit once, stating the hypothesis that
proved correct in the commit message. Standalone (no task file): commit only
when asked.
