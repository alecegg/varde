---
topic: varde-orchestrate/worker-launch
version: 1
summary: Launch workers, set explorer counts, and brief them
---

## Roles and state

- Use `varde-builder` with its configured role file for source/integration work; count merge agents as builders. You launch only this plan's workers, reviewers, and merge agent; spawn no other agent.
- Launch workers with `varde-runner agent launch` using an approved role and existing workspace. Use the Agent tool only for `varde-reviewer`, never `general-purpose`. If the native launcher is unavailable, send main `--kind blocked`.
- Set each brief's explorer count to its remaining cap (zero if exhausted, workers cannot spawn, or no tool exists). Explorers are bounded/read-only and spawn nothing. Workers may spawn only authorized `varde-explorer`s; otherwise the orchestrator explores and adds notes.
- Keep briefs pointer-only: task, plan, notes, exact worktree, explorer count, and the orchestrator slot; scope, checks, and posture belong in task/plan files. Require each brief to name the orchestrator slot and require the worker's final completion mail.
