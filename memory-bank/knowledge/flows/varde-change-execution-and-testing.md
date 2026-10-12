---
type: reference
title: varde change execution and testing
---

# Varde change execution and testing

Build tasks execute through `varde-change build` (`references/build.md`) and
the builder route (`references/build-execution.md`). Builders start from the
task file in their worktree; the task file is reference material, not state to
edit.

## Execution strategies

Ready independent tasks may run in one parallel wave. `varde plan
execution-wave` reports ready tasks, conflicts, and a next wave; tasks conflict
when their `owns` patterns intersect. Each parallel writer gets one worktree and
branch (`scripts/worktree-wave.sh start`); a serial single writer may use the
plan worktree. The integration queue runs one combined check per batch and
bisects failures to the culprit task; release removes the worker worktrees.
The orchestrator may run fewer tasks than the next wave, never more.

## Builder testing guidance

- Write the failing test first for a behavior change, then the fix.
- Test only the slice: task asserts plus tests for changed files (via the
  `tests_for_file` mode of `varde map batch`, or a package- or target-scoped
  test); never run the full suite; after a fix rerun only the failing target.
- Do not poll a running command or agent; wait on completion or use one long
  wait.
- Stop after two failed attempts at one approach; reproduce a failure the task
  calls pre-existing at the prerequisite commit.
- Check dependents before changing a shared surface; format only owned files
  and return writes outside the task's paths to the parent.
- Run the task's assert and retrieve checks with independent expected values.
  For `not-applicable`, run the named structural checks and explain why.
- Commit only verified task paths with the task ID in the message; report the
  commit, worktree, owned paths, checks, status, and blockers, and do not edit
  task or plan state.

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
