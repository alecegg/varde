<!-- kind: procedure -->
# Check plan conformance

Verify the plan inside the plan review, not separately; leave lint,
tests, types, and scans to the gate. Compare the plan Solution, criteria, tasks with gate output and the diff from the plan `base` through the
verified head. Compare each task `assert:` result with its expected behavior,
citing a task or plan line for missing, partial, incorrect, or unasked-for work.

## Record findings

- `review.md` has `type: review`, `verdict: changes-requested`, reviewer, plan base, and verified head.
- Findings follow the plan-level `## Conformance` as level-two `## [SPEC-NNN]` headings, starting at 001, never reusing an ID; the review verdict and header stay unchanged.
- Allowed statuses are `open`, `fixed`, `waived`, `deferred`, `dismissed`, and `asked` (`references/report-format.md`).
- `varde plan validate <review.md>` passes after recording findings.
