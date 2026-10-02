---
type: reference
title: varde change execution and testing
---

# Varde change execution and testing

Build tasks execute sequentially by default. Proven independent tasks may run
in one isolated parallel wave.

## Execution strategies

`varde-workflow execution-wave` reports facts: ready tasks, conflicts, and
a `next_wave` of tasks safe to run together. The orchestrator picks the
strategy from `execution=<auto|serial|inline>`:

- `parallel`: `auto` with two or more tasks in `next_wave`, one executor per
  task in its own worktree.
- `serial`: `execution=serial` or a one-task wave, one executor at a time.
- `inline`: `execution=inline` or no executor agent available.

The orchestrator may run fewer tasks together than `next_wave`, never more.
Announce the selected strategy before dispatch.

## Testing profiles

Each task declares one testing profile and rationale.

- `tdd` records `red,green,verify` checks.
- `regression` records `reproduce,fix,verify` checks.
- `characterization` records `characterize,verify` checks.
- `smoke` records `smoke,verify` checks.
- `not-applicable` records `not-applicable,structural` checks.

Completed tasks end `#### Progress` with one concise marker:
`- evidence: <what you ran and what it showed>`.

## Related

- [Change skill](../../../skills/varde-change/SKILL.md)
- [Task template](../../../skills/varde-change/assets/TASK-TEMPLATE.md)
