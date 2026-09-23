---
name: varde-change
description: "Run the change lifecycle: show work in flight, plan scope, build bounded changes, verify plans, or orchestrate groups. Route named bugs through evidence-led debugging. Not for exploration, review, or docs."
---

# Manage the change lifecycle

Read the request, then open the matching reference. Never ask the user which mode to use.

## Entry routing

Resolve explicit intent before automatic routing. Use this precedence:

1. A review request belongs to `varde-review report`.
2. An exploration request belongs to `varde-explore`.
3. An explicit diagnosis-only request opens `references/debugging-entry.md`
   with `debug_mode: diagnose`.
4. An explicit build request keeps the normal build path, even when it names a
   bug or regression.
5. A named bug or regression without an explicit mode opens
   `references/debugging-entry.md` with `debug_mode: fix`.

The debugging entry records `route_source` as `explicit` or `automatic`.
Diagnosis does not edit production source. Fixes begin only after reproduction
and tested hypothesis evidence exists.

## What the request needs

| The request is | Read |
|---|---|
| "What's in flight?" — show current work and what to do next | `references/status.md` |
| Define scope, design, and acceptance criteria before building | `references/plan.md` |
| Execute one plan, or make a bounded change described directly | `references/build.md` |
| Report evidence for finished work without changing anything | `references/verify.md` |
| Run a group of related plans end to end, in dependency order | `references/orchestrate.md` |

Open only the matching reference.
Then open every supporting file it explicitly requires.

## Gotchas

- Paths written `<working>/…` and `<knowledge>/…` resolve per
  `references/memory-locations.md`. Read it before the first memory read or write.
- Derive status from existing artifacts. Read each inspected artifact and leave it unchanged.
- Verification reports never mutate plan files.
- Handoffs require a stopping boundary.
- Review-only requests belong to `varde-review`. Name it and stop.
- Load `references/worktree.md` before isolated edits.
- Parallel builds require a complete task manifest and atomic verification.
