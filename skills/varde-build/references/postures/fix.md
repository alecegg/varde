# Fix Posture

## Purpose

Targeted feature addition or behavior change with explicit scope. The agent makes deliberate, verified changes within a well-defined boundary, checkpointing after each verification check instead of committing once at the end.

## Cadence

1. Confirm the scope from the task's `#### Verification` and `#### Out of scope` sections.
2. Write a failing test for one verification check at a time — not all checks up front.
3. Implement the smallest change that satisfies that one check.
4. Run verification. If it passes, commit before moving to the next check.
5. Repeat until every check is satisfied, then follow `references/EXECUTION.md`'s Completion step to mark the step done.

## Verification

- Every `#### Verification` check has at least one named test function that passes.
- All existing tests continue to pass after each checkpoint commit.
- No `#### Out of scope` boundary is crossed.

## When to use

- Tasks with multiple independent verification checks where per-check checkpoints reduce the risk of a large, hard-to-bisect diff.
- When the task's diff is expected to touch several files and a single end-of-task commit would obscure which change satisfied which check.
