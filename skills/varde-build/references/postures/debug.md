# Debug Posture

## Purpose

A discipline for hard bugs: build a feedback loop before hypothesizing, reproduce and minimize before instrumenting, rank hypotheses before testing them, and lock the fix down with a regression test. Skip phases only when explicitly justified. No batch writes — minimal, isolated changes with aggressive intermediate verification.

## Phase 1 — Build a feedback loop

**This is the posture.** Everything else is mechanical. If you have a **tight** pass/fail signal for the bug — one that goes red on _this_ bug — you will find the cause; bisection, hypothesis-testing, and instrumentation all just consume it. If you don't have one, no amount of staring at code will save you. Spend disproportionate effort here.

Ways to construct one — try them in roughly this order:

1. **Failing test** at whatever seam reaches the bug — unit, integration, e2e.
2. **CLI invocation or curl** against a fixture input / running dev server, diffing output against a known-good snapshot.
3. **Headless browser script** — drives the UI, asserts on DOM/console/network.
4. **Replay a captured trace** — save a real request/payload/event log, replay it through the code path in isolation.
5. **Throwaway harness** — a minimal subset of the system (one module, mocked deps) that exercises the bug's code path with a single call.
6. **Property / fuzz loop** — for "sometimes wrong output" bugs, run many random inputs and look for the failure mode.
7. **Bisection harness** — if the bug appeared between two known states (commit, dataset, version), automate "check out state X, check, repeat."
8. **Differential loop** — run the same input through old vs. new (or two configs) and diff outputs.
9. **Human-in-the-loop, last resort** — if a human must click to reproduce it, still keep the loop structured: capture their output and feed it back into the same red/green check rather than debugging from memory of what they said.

**Tighten the loop** once you have one: make it faster (skip unrelated init, narrow scope), sharper (assert the specific symptom, not "didn't crash"), and more deterministic (pin time, seed RNG, isolate filesystem, freeze network). A 30-second flaky loop is barely better than no loop; a 2-second deterministic one is a debugging superpower.

**Non-deterministic bugs:** the goal is a higher reproduction rate, not a clean repro. Loop the trigger repeatedly, add stress, narrow timing windows. A 50%-flake bug is debuggable; 1% is not — keep raising the rate until it is.

**When you genuinely cannot build a loop:** stop and say so explicitly. List what you tried. Ask the user for access to the reproducing environment, a captured artifact (log dump, core dump, recording with timestamps), or permission to add temporary instrumentation. Do not proceed to hypothesize without a loop.

Phase 1 is done when you can name **one command** — already run at least once, with its output pasted — that is red-capable (asserts the user's exact symptom, not just "runs without erroring"), deterministic, fast, and agent-runnable. If you catch yourself reading code to build a theory before this command exists, stop — jumping straight to a hypothesis is the exact failure this phase prevents.

## Phase 2 — Reproduce + minimize

Run the loop and confirm it produces the failure mode the **user** described, not a different failure that happens to be nearby — wrong bug, wrong fix. Capture the exact symptom so later phases can verify the fix addresses it.

**Minimize:** shrink the repro to the smallest scenario that still goes red. Cut inputs, callers, config, and steps one at a time, re-running the loop after each cut. Done when every remaining element is load-bearing — removing any one makes the loop go green. A minimal repro shrinks the hypothesis space in Phase 3 and becomes the regression test in Phase 5.

Do not proceed until you have reproduced and minimized.

## Phase 3 — Hypothesize

Generate 3-5 ranked hypotheses before testing any of them — single-hypothesis generation anchors on the first plausible idea. Each hypothesis must be falsifiable: "If `<X>` is the cause, then changing `<Y>` will make the bug disappear / changing `<Z>` will make it worse." If you can't state the prediction, the hypothesis is a vibe — discard or sharpen it.

Show the ranked list to the user before testing. They often have domain knowledge that re-ranks it instantly, or know hypotheses already ruled out. Don't block on it if the user is unavailable — proceed with your own ranking.

## Phase 4 — Instrument

Each probe maps to a specific prediction from Phase 3. Change one variable at a time.

Tool preference: debugger/REPL inspection where the environment supports it (one breakpoint beats ten logs), otherwise targeted logs at the boundaries that distinguish hypotheses. Never "log everything and grep."

Tag every debug log with a unique prefix (e.g. `[DEBUG-a4f2]`) so cleanup at the end is a single grep.

**Perf branch:** for performance regressions, logs are usually wrong. Establish a baseline measurement (timing harness, profiler, query plan) first, then bisect. Measure first, fix second.

## Phase 5 — Fix + regression test

Write the regression test **before** the fix, but only if there is a correct seam for it — one where the test exercises the real bug pattern as it occurs at the call site. A shallow seam (single-caller test when the bug needs multiple callers) gives false confidence.

**If no correct seam exists, that itself is the finding.** Note it — the code's structure is preventing the bug from being locked down — and hand it to `refactor` posture or the user's judgment after the fix lands, rather than restructuring inline mid-fix.

If a correct seam exists: turn the minimized repro into a failing test at that seam, watch it fail, apply the fix, watch it pass, then re-run the Phase 1 loop against the original (un-minimized) scenario.

## Phase 6 — Cleanup + post-mortem

Required before declaring done:

- [ ] Original repro no longer reproduces (re-run the Phase 1 loop).
- [ ] Regression test passes (or the absence of a correct seam is documented).
- [ ] All `[DEBUG-...]` instrumentation removed (`grep` the prefix).
- [ ] Throwaway prototypes deleted.
- [ ] The hypothesis that turned out correct is stated in the commit message, so the next debugger learns.

Then ask: what would have prevented this bug? If the answer involves a structural change (no good test seam, tangled callers, hidden coupling), note it as a candidate for `refactor` posture with the specifics — after the fix is in, not before; you have more information now than when you started.

## Completion

Commit only after the defect is fully verified, then follow `references/EXECUTION.md`'s Completion step to mark the step done.

## When to use

- When a known bug or regression is the only goal.
- When the task's title or context explicitly says "debug", "fix a bug", or "regression".
