# Debug Posture

A discipline for hard bugs: build a feedback loop before hypothesizing,
reproduce and minimize before instrumenting, rank hypotheses before testing
them, and lock the fix down with a regression test. Skip a phase only with a
stated justification. Minimal isolated changes, verified aggressively between
each.

## Evidence contract

The debugging entry carries two fields alongside normal task state:

- `debug_mode`: `diagnose` or `fix`.
- `route_source`: `automatic` for a named bug or regression, or `explicit` for
  a diagnosis-only request.

It also carries `debug_evidence` with these fields:

- `reproduction`: the deterministic command, fixture, and observed symptom.
- `hypotheses`: three to five ranked, falsifiable hypotheses.
- `experiments`: the result of testing each selected hypothesis.
- `cause`: the root-cause explanation supported by the experiments.
- `verification`: the regression check and the final verification result.

For `fix`, `reproduction`, `hypotheses`, and `experiments` must be non-empty
before any production edit. A completed fix must add `cause` and `verification`.
For `diagnose`, production source is read-only. The report may leave `cause`
uncertain, but must state the evidence limit and preserve the reproduction.

## Phase 1 — Build a feedback loop

**This is the posture.** Everything else follows from it. Build a tight
pass/fail check that fails on _this_ bug. Use that check for bisection,
hypothesis testing, and instrumentation. Without it, code inspection alone is
not enough. Spend most of this phase building the check.

Reach for a failing test first, then a CLI or curl invocation diffed against a
known-good snapshot, a headless browser script, a replayed trace, a throwaway
harness around the one code path, a property or fuzz loop for wrong-output bugs,
a bisection harness when the bug appeared between two known states, or a
differential loop across two configs. Human-in-the-loop is the last resort: if a
human must click to reproduce, still capture their output and feed it back into
the same red/green check rather than debugging from memory of what they said.

**Tighten the loop** once you have one — faster, sharper (assert the specific
symptom, not "didn't crash"), and deterministic (pin time, seed RNG, isolate
filesystem, freeze network). A 30-second flaky loop is barely better than none.
Prefer a 2-second deterministic loop.

**Non-deterministic bugs:** aim for a higher reproduction rate, not a clean
repro. A 50%-flake bug is debuggable; 1% is not — raise the rate until it is.

**When you genuinely cannot build a loop:** stop and say so explicitly. List
what you tried. Ask the user for access to the reproducing environment, a
captured artifact (log dump, core dump, timestamped recording), or permission to
add temporary instrumentation. Do not proceed to hypothesize without a loop.

Phase 1 is done when you can name **one command** — already run at least once,
with its output pasted — that is red-capable (asserts the user's exact symptom,
not just "runs without erroring"), deterministic, fast, and agent-runnable. If
you catch yourself reading code to build a theory before that command exists,
stop: jumping to a hypothesis is the exact failure this phase prevents.

## Phase 2 — Reproduce and minimize

Run the loop and confirm it produces the failure the **user** described, not a
different one nearby — wrong bug, wrong fix. Capture the exact symptom so later
phases can verify the fix addresses it.

**Minimize** to the smallest scenario that still goes red, re-running the loop
after each cut. Done when removing any remaining element makes it go green. The
minimal repro shrinks Phase 3's hypothesis space and becomes Phase 5's
regression test.

Do not proceed until you have reproduced and minimized.

Record the `reproduction` field before ranking hypotheses. Do not infer a
reproduction from source inspection or a command that only exits cleanly.

## Phase 3 — Hypothesize

Generate 3–5 ranked hypotheses before testing any of them — generating one
anchors you on the first plausible idea. Each must be falsifiable: "if `<X>` is
the cause, changing `<Y>` makes the bug disappear." A hypothesis with no
prediction is a vibe; sharpen it or discard it.

Show the ranked list to the user before testing. They often re-rank it instantly
or know what has already been ruled out. Proceed with your own ranking if they
are unavailable.

Record one `experiments` result per tested hypothesis. A hypothesis without a
test result is not evidence for a fix.

## Phase 4 — Instrument

Each probe maps to a specific prediction from Phase 3, changing one variable at
a time. Prefer debugger or REPL inspection where the environment supports it —
one breakpoint beats ten logs — otherwise target the boundaries that distinguish
hypotheses.

Tag every debug log with a unique prefix (e.g. `[DEBUG-a4f2]`) so cleanup is a
single grep.

**Perf branch:** for performance regressions, logs are usually the wrong tool.
Establish a baseline (timing harness, profiler, query plan) first, then bisect.

## Diagnose completion boundary

When `debug_mode` is `diagnose`, stop after the hypothesis experiments and
report the evidence. Do not enter the fix or cleanup phases, write a regression
test, edit production source, or commit a fix. Any instrumentation must stay
outside production source. The report may leave `cause` uncertain, but must
state the evidence limit and preserve the reproduction command.

## Phase 5 — Fix and regression test

Run this phase only when `debug_mode` is `fix`.

Write the regression test **before** the fix, but only where a correct seam
exists — one that exercises the real bug pattern as it occurs at the call site.
A shallow seam, such as a single-caller test for a bug that needs several, gives
false confidence.

**If no correct seam exists, that itself is the finding.** The code's structure
is preventing the bug from being locked down. Note it and hand it to the
`refactor` posture or the user's judgment after the fix lands, rather than
restructuring inline mid-fix.

With a correct seam: turn the minimized repro into a failing test there, watch
it fail, apply the fix, watch it pass, then re-run the Phase 1 loop against the
original un-minimized scenario.

Populate `cause` from the experiment that explains the symptom. Populate
`verification` only after the regression check and original reproduction both
pass.

## Phase 6 — Cleanup and post-mortem

Run this phase only when `debug_mode` is `fix`.

Required before declaring done:

- [ ] Original repro no longer reproduces (re-run the Phase 1 loop).
- [ ] Regression test passes, or the absence of a correct seam is documented.
- [ ] All `[DEBUG-...]` instrumentation removed (`grep` the prefix).
- [ ] Throwaway prototypes deleted.
- [ ] The hypothesis that proved correct is stated in the commit message, so the
      next debugger learns.
- [ ] `debug_evidence` contains the required fields for the selected mode.

Then ask what would have prevented this bug. If the answer is structural — no
good test seam, tangled callers, hidden coupling — note it as a `refactor`
posture candidate with the specifics. After the fix is in, not before: you know
more now than when you started.

## Completion

Commit only after the defect is fully verified, then follow
`references/build-execution.md`'s Completion step to mark the step done.

## When to use

- When a known bug or regression is the only goal.
- When the task's title or context says "debug", "fix a bug", or "regression".
