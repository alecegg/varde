---
name: varde-build
description: "Use this skill when the user wants one bounded code task implemented or diagnosed: an assigned task file, a settled small change, a bug fix, a diagnosis without changes, or a refactor that preserves behavior. It covers the task's checks, the commit of verified paths, and the independent review before merge."
requires: [varde-review]
recommends: [varde-skill-authoring, varde-doc-authoring]
---

# Build one bounded task

## What the request needs

An explicit build request, including a bug fix, takes this route. Work one task; its scope is settled before editing.

| The request is | Read |
|---|---|
| One assigned task | — |
| Settled standalone change | `references/build-micro-change.md`, `references/TASK-TEMPLATE.md` |
| Diagnose without fixing | `references/build-posture-debug.md` |
| Refactor with preserved behavior | `references/build-posture-refactor.md` |
| Fix a named bug | `references/build-posture-debug.md` |

Read `references/build-execution.md` and `references/review-gates.md`. Start from the assigned task file, or a compact task written for a settled micro-change.

- Never run `uv tool install|upgrade|uninstall` from a linked worktree; a PreToolUse guard denies it where hooks are installed.
- When status commands are denied or unavailable, follow `references/varde-workflow-cli.md`; consult `references/workflow-state.md` for legal status values.
