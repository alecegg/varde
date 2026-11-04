---
topic: varde-orchestrate/dispatch
version: 1
summary: Select waves, set task states, and gate and integrate task commits
---

## Dispatch

- `varde plan execution-wave <plan-dir>` selects a wave and `bash scripts/worktree-wave.sh <action> ...`. Prefix wave ids with the plan id (`<plan>-w1`).
- Give parallel writers task worktrees; a serial writer may use the plan worktree. Set task states through `varde plan task set <task.md> <state>`: `building` on dispatch, `integrating` before integration, and `done` after success.
- Before integrating each task commit, run `varde plan check-task-ownership --task <task.md> --commit <sha> --json` and `varde plan gate <task.md> --commit <sha>`; return a failure to that builder. Task level has static checks only; no agent review runs per task or wave.
- Wrap long builds and tests per `varde-build` references/build-execution.md; report the `writes:` line.
- If a task blocks or fails, stop dispatch, let running workers report, then report failed/completed tasks, blocker, and next action.
- Save full explorer reports under `<working>/plans/<id>/notes/`; report outcome, commit, checks, report path, and friction ids to the parent.
