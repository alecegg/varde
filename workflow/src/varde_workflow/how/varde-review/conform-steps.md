---
topic: varde-review/conform-steps
version: 1
summary: Run task asserts, cite lines, and append SPEC findings to review.md
---

## Conformance steps

- Read the plan Solution and criteria, every task, gate output, and the diff from the plan `base` through the verified head.
- Run each task `assert:` command and compare its result with the expected behavior.
- Create `review.md` if absent, with `type: review`, `verdict: changes-requested`, reviewer, plan base, and verified head.
- Append findings after the plan-level `## Conformance` as level-two `## [SPEC-NNN]` headings, starting at 001; never reuse IDs. Keep each heading a sibling of the section heading. Do not change the review verdict or header.
- Run `varde plan validate <review.md>` after recording findings; follow the remaining report-format rules (`references/report-format.md`) yourself.
