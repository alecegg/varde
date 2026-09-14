# Plan Execution Posture

## Purpose

The default posture. No special discipline beyond `references/EXECUTION.md` applies — follow the step's `Context`, `Design notes`, `Execution notes`, and `Test approach` fields directly and implement with the standard TDD cycle.

## Cadence

1. Read the task's `tasks/<task-id>.md` file.
2. Follow `references/EXECUTION.md`: write a failing test per `#### Verification` check, implement, verify, commit.
3. Signal completion by applying a targeted edit to the task file's own `status` (task-specific blockers also set this file's `status: blocked` — never `plan.md`), as defined in `EXECUTION.md`'s Completion and Blocker Handling sections.

## Verification

- All of the step's `#### Verification` checks are demonstrably met.
- The step's `status` is `done`, or `blocked` (task-level) or the plan's `status` is `blocked` (plan-wide, orchestrator-owned only).
- No `out_of_scope` boundary is crossed.

## When to use

- Default posture whenever no other posture more specifically fits the task.
- Use this when the task has no unusual risk profile — not a known bug, not a behavior-preserving refactor, not a throwaway exploration.
