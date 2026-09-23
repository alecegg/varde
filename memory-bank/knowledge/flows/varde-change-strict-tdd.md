---
type: reference
title: varde change strict TDD
description: Resolves strict TDD authority and validates ordered evidence.
---

# Varde strict TDD flow

Strict TDD is opt-in. Resolve its authority before executing a task.

1. Apply a direct user instruction first. `require` selects `tdd`.
   `waive` keeps the decomposition-selected profile.
2. If the user gave no instruction, apply repository policy. `require`
   selects `tdd`. `exception` selects `not-applicable`.
3. If neither applies, keep the decomposition-selected profile.
   Existing profiles remain valid.
4. Record `profile_source` and `strict_tdd` in `#### Test approach`.

Use the [profile selector](../../../skills/varde-change/scripts/resolve-testing-profile.sh)
for deterministic selection.
The selector returns `user`, `repository`, `decomposition`, or `exception`
as the profile source.

Required strict TDD tasks record three Progress markers in order:
`tdd_evidence: stage=red`, then `stage=green`, then `stage=verify`.
Each marker needs `result=pass` and a non-empty note. The final evidence
marker still records `checks=red,green,verify`.

A policy exception requires `strict_tdd: exception`,
`profile_source: exception`, `profile: not-applicable`, and a non-empty
`exception:` reason. Its evidence uses `not-applicable,structural`.
An undeclared exception fails validation.

## Related

- [Change execution and testing](varde-change-execution-and-testing.md)
- [Task template](../../../skills/varde-change/assets/TASK-TEMPLATE.md)
- [Profile selector](../../../skills/varde-change/scripts/resolve-testing-profile.sh)
