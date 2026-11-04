---
topic: varde-orchestrate/plan-setup
version: 1
summary: Create the plan worktree, handle open comments, and run task gates and ownership checks
---

## Plan setup

- Create the plan worktree and branch with `scripts/worktree-create.sh`; worktree scripts live in `scripts/`. Then check `varde plan status` and show its staleness notice.
- Open comments (`varde plan comments <plan> --open`) are input before tasks start. Append resolved ones as `addressed` events with notes to `plans/<id>/comments.jsonl` and commit the file by path with plan changes. Leave unresolvable ones open and tell main.
- Each worker follows `varde-build` (or `varde-builder`) and the task's declared posture.
- Pipeline mode uses per-role pull queues; fall back to the per-task flow when slots are unavailable or main or the user selects it.
- Main hears one `varde msg send` kind per milestone; load `references/main-agent-replies.md` for the progress reply format.
- Read `references/build-finish.md` to finish the plan, `references/review-gates.md` before reviewer dispatch, `references/varde-workflow-cli.md` after command denial, and `references/workflow-state.md` before status changes.
