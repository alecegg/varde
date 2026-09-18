# Debug Posture

A discipline for hard bugs: build a feedback loop before hypothesizing,
reproduce and minimize before instrumenting, rank hypotheses before testing
them, and lock the fix down with a regression test. Skip a phase only with a
stated justification. Minimal isolated changes, verified aggressively between
each.

## Phase 1 — Build a feedback loop

**This is the posture.** Everything else is mechanical. With a tight pass/fail
indicator — one that goes red on _this_ bug — bisection, hypothesis-testing, and
instrumentation all just consume it. Without one, no amount of staring at code
will save you. Spend disproportionate effort here.

Reach for a failing test first, then a CLI or curl invocation diffed against a
known-good snapshot, a headless browser script, a replayed trace, a throwaway
harness around the one code path, a property or fuzz loop for wrong-output bugs,
a bisection harness when the bug appeared between two known states, or a
differential loop across two configs. Human-in-the-loop is the last resort: if a
human must click to reproduce, still capture their output and feed it back into
the same red/green check rather than debugging from memory of what they said.

**Tighten the loop** once you have one — faster, sharper (assert the specific
symptom, not "didn't crash"), and deterministic (pin time, seed RNG, isolate
filesystem, freeze network). A 30-second flaky loop is barely better than none;
a 2-second deterministic one is a superpower.

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

## Phase 3 — Hypothesize

Generate 3–5 ranked hypotheses before testing any of them — generating one
anchors you on the first plausible idea. Each must be falsifiable: "if `<X>` is
the cause, changing `<Y>` makes the bug disappear." A hypothesis with no
prediction is a vibe; sharpen it or discard it.

Show the ranked list to the user before testing. They often re-rank it instantly
or know what has already been ruled out. Proceed with your own ranking if they
are unavailable.

## Phase 4 — Instrument

Each probe maps to a specific prediction from Phase 3, changing one variable at
a time. Prefer debugger or REPL inspection where the environment supports it —
one breakpoint beats ten logs — otherwise target the boundaries that distinguish
hypotheses.

Tag every debug log with a unique prefix (e.g. `[DEBUG-a4f2]`) so cleanup is a
single grep.

**Perf branch:** for performance regressions, logs are usually the wrong tool.
Establish a baseline (timing harness, profiler, query plan) first, then bisect.

## Phase 5 — Fix and regression test

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

## Phase 6 — Cleanup and post-mortem

Required before declaring done:

- [ ] Original repro no longer reproduces (re-run the Phase 1 loop).
- [ ] Regression test passes, or the absence of a correct seam is documented.
- [ ] All `[DEBUG-...]` instrumentation removed (`grep` the prefix).
- [ ] Throwaway prototypes deleted.
- [ ] The hypothesis that proved correct is stated in the commit message, so the
      next debugger learns.

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
