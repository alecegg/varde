---
type: reference
title: varde change execution and testing
---

# Varde change execution and testing

Build tasks execute sequentially by default. Proven independent tasks may run
in one isolated parallel wave.

## Execution strategies

`inline` keeps every task in the current executor.
`fresh` uses a new executor for every task.
`auto` keeps one-task changes inline.
It uses fresh executors for multi-task plans unless a complete manifest proves
parallel safety. `parallel` requires that manifest.

Announce the selected strategy before dispatch.
Parallel waves require disjoint ownership and verification resources.

## Testing profiles

Each task declares one testing profile and rationale.

- `tdd` records `red,green,verify` checks.
- `regression` records `reproduce,fix,verify` checks.
- `characterization` records `characterize,verify` checks.
- `smoke` records `smoke,verify` checks.
- `not-applicable` records `not-applicable,structural` checks.

Completed tasks record one concise evidence marker.
Validate it with `validate-task-evidence.sh`.

Strict TDD selection and ordered stage evidence follow the
[strict TDD flow](varde-change-strict-tdd.md). Existing profiles remain
available when no strict requirement applies.

## Related

- [Change skill](../../../skills/varde-change/SKILL.md)
- [Task template](../../../skills/varde-change/assets/TASK-TEMPLATE.md)
