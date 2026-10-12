---
name: varde-change
description: "Plan, build, verify, or orchestrate a code change, list plans in flight, diagnose why something fails, or fix a named bug evidence-first. Not for explaining or reviewing code."
requires: [varde-review]
recommends: [varde-agent-doc-authoring, varde-code, varde-explore, varde-knowledge, varde-learn, varde-prototype]
---

# Manage the change lifecycle

Never ask the user which mode to use.

Every change gets the one review in `references/review-gates.md`.

## Entry routing

Explicit intent wins, in order: review → load `varde-review`: use your skill
tool, or read `../varde-review/SKILL.md`; exploration → load `varde-explore`:
use your skill tool, or read `../varde-explore/SKILL.md`; an explicit build
request takes a build row below, even for a bug.

## What the request needs

| The request is | Read |
|---|---|
| "What's in flight?", or an empty invocation — show current work and what to do next | `references/status.md` |
| Plan a new feature before building | `references/plan.md` |
| Resume planning with no feature named | `references/plan.md` (Start or resume) |
| One task file assigned by an orchestrator (builder) | `references/build-execution.md` |
| A settled single-outcome refactor | `references/build-micro-change.md`, then `references/build-posture-refactor.md` |
| A settled single-outcome change that fits one task | `references/build-micro-change.md` |
| A named plan, multiple dependent outcomes, or unresolved design | `references/build.md`; use `references/build-orchestrate-tasks.md` for task execution |
| Diagnose why something fails, without fixing it | `references/build-posture-debug.md` (`diagnose`) |
| Fix a named bug or regression, no mode given | `references/build-posture-debug.md` (`fix`) |
| Report evidence for finished work without changing anything | `references/verify.md` |
| Run a plan set's ready plans in parallel | `references/orchestrate.md` |

## Gotchas

- Ask one topic per turn as an inline numbered menu with a recommendation;
  wait for an explicit answer.
- Resolve `<working>` and `<knowledge>` once with `varde setup paths --json`;
  retry once with escalated access, then ask; never guess. Outside a repo, use
  `mv`, not `git mv`.
- A `varde` call that is denied or errors: load
  `references/varde-workflow-cli.md` for its fallback rule and
  `references/workflow-state.md` for status values.
- Run Varde commands; read `varde <cmd> --help` if unsure.
