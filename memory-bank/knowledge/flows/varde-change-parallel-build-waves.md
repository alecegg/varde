---
type: reference
title: varde change parallel build waves
description: Dependency-ready parallel execution with atomic integration.
---

# Varde parallel build waves

Parallel execution is opt-in. Sequential execution remains the default.

## Eligibility

A task wave is eligible only when every task is ready. Readiness requires the
task's `status: todo` and every listed `depends_on` task `done`. Each task
declares `modifies`, `creates`, `renames`, and `verification_resources`.
Overlapping `owns` patterns (glob intersection) create separate waves.
Asynchronous dispatch stays within the configured per-orchestrator builder
caps; a configured limit cannot exceed capacity.

## Wave lifecycle

1. Resolve one dependency-ready wave with `varde plan execution-wave`.
2. `scripts/worktree-wave.sh start` creates one worktree and branch per task.
3. Run workers concurrently on distinct branches; each edits only its task's
   paths.
4. `scripts/worktree-wave.sh integrate --check <cmd>` audits each commit with
   `check-task-ownership`, merges workers in task order, runs the combined
   check once, and fast-forwards the plan branch.
5. `scripts/worktree-wave.sh release` removes the task and integration
   worktrees.

The plan branch's owner alone writes plan state. Workers report commits,
checks, owned paths, and worktree locations. Dependents wait for verified
integration.

## Failure recovery

A failed worker, merge, or combined check leaves the plan branch unchanged.
`integrate` bisects a failure to the culprit task and exits 5 with
`culprit=<task>`, `verified_prefix=<commit>`, and
`untouched_remainder=<tasks>`; conflicts exit 3 naming the conflicting paths.
Diagnose the culprit before retrying, then re-start or re-integrate the
untouched remainder as a later wave.

## Compatibility

`inline`, `fresh`, and micro-change paths retain their behavior. Parallel mode
does not replace sequential task ordering or direct micro-change execution.

## Related

- [Change execution and testing](varde-change-execution-and-testing.md)
- [Change skill](../../../skills/varde-change/SKILL.md)
