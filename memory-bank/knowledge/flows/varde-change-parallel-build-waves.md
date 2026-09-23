---
type: reference
title: varde change parallel build waves
description: Dependency-ready parallel execution with atomic integration.
---

# Varde parallel build waves

Parallel execution is opt-in. Sequential execution remains the default.

## Eligibility

A task wave is eligible only when every task is ready. Readiness requires all
listed dependencies to be complete. Each task declares `modifies`, `creates`,
`renames`, and `verification_resources`. Missing ownership keeps `auto`
sequential. Overlapping paths or resources create separate waves. Unknown
harness capacity uses two workers. A configured limit cannot exceed capacity.

## Wave lifecycle

1. Resolve one dependency-ready wave.
2. Create one isolated worktree per worker.
3. Run workers concurrently on distinct branches.
4. Merge worker commits into a temporary integration branch.
5. Run the wave verification command there.
6. Advance the target ref after verification passes.

The orchestrator alone writes plan state. Workers report commits, checks,
owned paths, and worktree locations. Dependents wait for verified integration.

## Failure recovery

Failed workers, merges, or verification leave the target ref unchanged.
Recovery refs retain worker and integration commits. Diagnose those refs before
retrying. Successful independent work may form a smaller later wave.

## Compatibility

`inline`, `fresh`, and micro-change paths retain their behavior. Parallel mode
does not replace sequential task ordering or direct micro-change execution.

## Related

- [Change execution and testing](varde-change-execution-and-testing.md)
- [Change skill](../../../skills/varde-change/SKILL.md)
