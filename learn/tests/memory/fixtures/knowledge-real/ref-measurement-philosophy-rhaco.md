---
type: reference
status: current
date: 2026-11-01
---

# Reference: RHACO measurement philosophy (Autonomous_Build_Harness_Test)

Sources (user-provided 2026-11-01; read by a Haiku explorer, not yet verified by a second reader):
- https://github.com/highsierralabs/Autonomous_Build_Harness_Test/blob/main/docs/MEASUREMENT_PHILOSOPHY.md
- https://github.com/highsierralabs/Autonomous_Build_Harness_Test/tree/main/docs/measurement-philosophy (files: `README.md`, `measurement-philosophy.md`)

## What it is
- `MEASUREMENT_PHILOSOPHY.md`: companion note on how a physics-observatory charter (Measurement Philosophy v1.4.1, not in the repo) became a software build prompt (the Corpus Explorer pilot). It records where the transfer failed. The pilot ended `BOUNDED_FAIL`; the harness evaluation said "partially supported"; the doc states n = 1 and that nothing shows the principles produce better software.
- `measurement-philosophy/measurement-philosophy.md`: the frozen, domain-neutral artifact (5,333 bytes, SHA-256 `3f9b520ba986175a923ed01bb6822ccc8eccef3e1793519362f00d6e52016820`, frozen 2026-08-16). Seven principles plus three operating rules, written as instructions to an engineering agent. No metrics.

## The principles (short)
1. Architectural acceptance: prefer a bounded result the evidence supports over a stronger result that assumes undemonstrated capability.
2. The system observes itself: inspect, do not assert; being wrong about your own state must show up as being wrong about the work.
3. Layered independence: "A stack of checks that all fail the same way is one check."
4. Differential measurement: before/after on the same state; choose the comparison so that what cancels is what does not matter.
5. Measurement defines category: revise the categories, never trim or reinterpret the observation.
6. Reasoning as artifact: evidence, assumptions, rejected alternatives, action, verification, captured when the decision is made.
7. Honest scope: label results observed, derived, inferred, assumed or unresolved; a bounded incomplete result outranks an overstated complete one.
- R1 materiality (no ceremony layers), R2 agreement between checks that share a failure mode is one observation, R3 unresolved is not automatically blocking.
- Lesson from the pilot: "four independent layers" shared build, DB, capture path and model family; fix was a shared-dependency register. "A label is a claim": a named label must resolve to a mechanism in its own section.

## Ideas possibly useful to Varde (to discuss, none adopted)
1. Count judge and check agreement by failure mode: a model-judge and a model-written test count as one observation in eval reports.
2. Paired differential skill evals (with vs without the skill, same inputs), reported as deltas.
3. Report three numbers per judged result: quality vs a reference set, change since the previous version on the same cases, component alone vs integrated.
4. Qualify a judge on known-good and known-bad fixtures before trusting it (fits person-free calibration; our seeded mutation tests are the same idea).
5. If anchors do not reproduce on known artifacts, fix the anchors; with no calibration artifacts, declare the scale ordinal and never emit PASS.
6. Explicit bounded-fail terminal state for budget exhaustion instead of a relabeled pass.
7. "Labels are claims" and materiality as checks in `varde-doc-authoring` / `varde-skill-authoring`.
- Not covered by the source: friction-driven loops, token cost, trigger evaluation. `PROMPT_EVOLUTION.md` and `LAYERS.md` are referenced but were not fetched.

## Caveats
- Qualitative; self-reported single pilot; the referenced charter and pilot records are not in the fetched files.
