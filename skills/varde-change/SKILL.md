---
name: varde-change
description: "Plan, build, verify, or orchestrate a code change, list plans in flight, diagnose why something fails, or fix a named bug evidence-first. Not for explaining or reviewing code."
---

# Manage the change lifecycle

Never ask the user which mode to use.

Before implementation edits, apply `references/review-gates.md` and carry its
verdict through completion, including changes made by this skill. An executor
with a caller-supplied subject runs only the checks in
`references/build-execution.md` instead.

## Entry routing

Explicit intent wins, in order: review → `varde-review report`; exploration →
`varde-explore`; an explicit build request takes a build row below, even for a
bug.

## What the request needs

| The request is | Read |
|---|---|
| "What's in flight?", or an empty invocation — show current work and what to do next | `references/status.md` |
| Plan a new feature before building | `references/plan.md` |
| Resume planning with no feature named | `references/plan.md` (Resume a draft) |
| One task file assigned by an orchestrator (executor) | `references/build-execution.md` |
| A settled single-outcome refactor | `references/build-micro-change.md`, then `references/build-posture-refactor.md` |
| A settled single-outcome change that fits one task | `references/build-micro-change.md` |
| A named plan, multiple dependent outcomes, unresolved design, or spike | `references/build.md` |
| Diagnose why something fails, without fixing it | `references/build-posture-debug.md` (`diagnose`) |
| Fix a named bug or regression, no mode given | `references/build-posture-debug.md` (`fix`) |
| Report evidence for finished work without changing anything | `references/verify.md` |
| Run a group of related plans end to end, in dependency order | `references/orchestrate.md` |

## Asking questions

- **One topic per turn.** Ask one question, or up to three that are facets of
  the same decision or share candidate solutions, such as naming sibling
  commands or edge cases of one input. Never mix unrelated problems in one
  turn. End your turn and wait before the next.
- **Recommend one option** and say why in one sentence, using severity,
  confidence, blast radius, or a context clue.
- **Wait for an explicit answer.** Silence and surrounding context leave the
  decision open.

Write the question inline in your message, using a numbered menu:

```
<Question>

  1. <Option A>
  2. <Option B>
  3. Other - describe what you want

Recommendation: <n> (<label>) - <one-sentence reason>.
```

## Gotchas

- A draft is a `plan.md` with `status: backlog` and an id ending in
  `-draft` or a live Open Questions bullet.
- Resolve `<working>` and `<knowledge>` once with `varde-workflow paths --json`; retry once with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.
- A `varde-workflow` call that is denied, errors, or returns
  `workflow_blocked`: load `references/varde-workflow-cli.md` for its fallback
  rule and `references/workflow-state.md` for legal state moves.
