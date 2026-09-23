# Standalone verification

Report evidence without changing files.
Never implement fixes, update statuses, or check criteria.
Batch independent reads and evidence checks together.

## Resolve the target

| Request | Target |
|---|---|
| Plan identifier or slug | Matching `<working>/plans/<plan-id>/plan.md` |
| Feature or group | Group plan and every nested child plan |
| No target | Most recent completed date-prefixed plan |

List ambiguous slug matches and ask once.
State the resolved identifier and current status.
Incomplete plans still receive partial verification.

## Verify

1. Read `## Acceptance criteria` from `plan.md`.
   Stop when that section is missing.
   Ignore checkbox state when grading.
2. Read each adjacent `tasks/*.md` status and Progress evidence.
   Do not re-grade task Verification blocks.
3. Run every criterion's `assert:` command or structural check.
   Compare its exact expected result.
   Record exit codes or match counts.
4. For every `retrieve:` clause, read only named files.
   Compare the requested outcome and record its supporting line.
5. Classify every criterion:
   - `passed`: evidence matches expectations.
   - `failed`: evidence exists but contradicts expectations.
   - `unavailable`: evidence cannot be gathered.
6. Report each criterion with its evidence.
   Finish with outcome counts and plan status.

For groups, report children before the aggregate.
Recommend `varde-change build` when fixes are needed.

## Rules

- Checked boxes are claims, not evidence.
- Unchecked boxes are not automatic failures.
- Missing commands and moved files mean unavailable.
- Never substitute a different assertion silently.
- Run broad project checks only when criteria request them.
- Leave every plan, task, checkbox, and source file unchanged.
