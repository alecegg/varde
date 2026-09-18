---
name: varde-change
description: "Run the change lifecycle: show what work is in flight, plan scope and acceptance criteria, build a plan or a bounded change, verify finished work, or run a group of plans in order. Not for exploration, review, or docs."
---

# Manage the change lifecycle

Read the request and pick one reference. Never ask the user which mode to use.

## What the request needs

| The request is | Read |
|---|---|
| "What's in flight?" — show current work and what to do next | `references/status.md` |
| Define scope, design, and acceptance criteria before building | `references/plan.md` |
| Execute one plan, or make a bounded change described directly | `references/build.md` |
| Report evidence for finished work without changing anything | `references/verify.md` |
| Run a group of related plans end to end, in dependency order | `references/orchestrate.md` |

Load only the reference the request needs.
Then load its explicitly required supporting files.

Derive status from existing artifacts.
Verification reports never mutate plan files.
Handoffs require a stopping boundary.

Load `references/worktree.md` before isolated edits.
