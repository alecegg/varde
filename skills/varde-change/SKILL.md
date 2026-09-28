---
name: varde-change
description: "Plan, build, verify, or orchestrate a code change, list plans in flight, diagnose why something fails, or fix a named bug evidence-first. Not for explaining or reviewing code."
---

# Manage the change lifecycle

Read the request, then open the matching reference. Never ask the user which mode to use.

Before implementation edits, apply `references/review-gates.md`. Carry its
verdict through execution and completion, including changes made by this skill.

## Entry routing

Explicit intent wins, in order: review → `varde-review report`; exploration →
`varde-explore`; an explicit build request takes a build row below, even for a
bug.

## What the request needs

| The request is | Read |
|---|---|
| "What's in flight?", or an empty invocation — show current work and what to do next | `references/status.md` |
| Plan a new feature before building | `references/plan-start.md` |
| Resume planning with no feature named | `references/plan-resume.md` |
| One task file assigned by an orchestrator (executor) | `references/build-execution.md` |
| A settled single-outcome refactor | `references/build-micro-change.md`, then `references/build-posture-refactor.md` |
| A settled single-outcome change with known verification, regardless of file count | `references/build-micro-change.md` |
| A named plan, multiple dependent outcomes, unresolved design, or spike | `references/build-plan.md` |
| Diagnose why something fails, without fixing it | `references/build-posture-debug.md` (`diagnose`) |
| Fix a named bug or regression, no mode given | `references/build-posture-debug.md` (`fix`) |
| Report evidence for finished work without changing anything | `references/verify.md` |
| Run a group of related plans end to end, in dependency order | `references/orchestrate.md` |

## Gotchas

- `<working>` (local, uncommitted) and `<knowledge>` (committed): resolve once
  before first use with `varde-workflow paths --json`; use its absolute
  `data.working`/`data.knowledge` paths for this session and pass them to
  subagents. If the command fails, retry it once with escalated access; if it
  still fails, ask the user for the paths. Do not guess storage paths. A
  location outside the repo skips git ops (`check-ignore`, `mv`, `status`);
  use plain file ops.
