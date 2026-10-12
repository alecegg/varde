<!-- kind: reference -->
# Orchestrate plan tasks

Advance the approved task graph from current readiness and wave state. The orchestrator owns plan/task status, dispatch, integration, review, merge queue, sync, memory commits, conclusion, and `varde plan now <plan> "<status>"` (`--clear` when done). Main relays user decisions and approvals with `varde msg send --to <plan id> --kind info`; before acting, confirm each approval by `info` naming the action, or send `needs-user`. Workers edit assigned paths only.

## Roles and state

- Use `varde-builder` with its configured role file for source/integration work; count merge agents as builders.
- Launch one background orchestrator per plan on a cheaper model, within role caps. It launches that plan's workers, reviewers, and merge agent; it spawns no other agent.
- Set each brief's explorer count to the remaining cap (zero if exhausted, workers cannot spawn, or no tool exists). Explorers are bounded/read-only and spawn nothing. Workers may spawn only brief-authorized `varde-explorer`s; otherwise the orchestrator explores and adds notes to the brief.
- Keep briefs pointer-only: task, plan, notes, exact worktree, explorer count. Scope, checks, and posture belong in task/plan files.
- At start, run `varde plan owner <plan.md> <harness>:<id>` when a harness id exists.
- Plan owners get unread messages by hook; otherwise run `varde msg read --as <plan id>` before merge, sync, or conclusion.

## Dispatch and integrate

- Use `varde plan execution-wave`, `varde plan check-task-ownership`, and `bash scripts/worktree-wave.sh start|integrate|release`; on failure, read its `--help`.
- Give each parallel writer a task worktree; one serial writer may use the plan worktree.
- Check assigned paths before dispatch; before integration run `varde plan check-task-ownership --task <task.md> --commit <sha> --json`.
- Dispatch ready tasks within caps; integrate as they return.
- Check task evidence before integration; independent review is still required.
- Workers do not merge.
- Request the merge slot from main by `info`; merge only after `info: slot granted`, and notify main when done.
- The integration queue's full gate runs once per batch and bisects failures to the culprit task; do not poll running commands or agents. Build branch `varde` before `--check` (missing only warns); it runs each modified crate's unfiltered tests.
- At wrap-up, the orchestrator or merge agent runs full workspace/integration checks under the repository lock; workers never do.
- Wrap long builds and tests in `scripts/measure-writes.sh run`; report its `writes:` line.
- Use `release --keep` for clean workers; report dirty or unmerged workers in place.
- Commits to the plan branch/task worktrees are authorized; other targets and pushes need explicit user approval.
- On conflict or failed integration checks, preserve the verified prefix/remainder and report evidence.
- If a task blocks or fails, stop dispatch, let running workers report, then report failed/completed tasks, blocker, and next action.
- Save full explorer reports under `<working>/plans/<id>/notes/`; report outcome, commit, checks, report path, and friction ids to the parent.
- Record worker `friction:` lines. Search open items first; append to a match or add one with `varde learn friction list --status open --text "<phrase>"` then `varde learn friction add --item <ID> | --source <S> --title <T> --text "<evidence>"`.

## Progress replies

For the main agent's replies, use this compact progress layout:

- The `**Progress** HH:MM` block from `varde plan status`. If unchanged from the prior block ignoring time, use `**Progress** HH:MM: no change since last check.` with a fresh `date +%H:%M`.
- One `Agents:` line.
- Bold `**My work**` and `**Needed from you**` sections.

When orchestrators run and no `varde plan watch` is running, start it.
Orchestrator and worker final replies are one line.

Refresh the session notes only when the session-notes token nudge fires, before compaction, or on request (load `varde-knowledge`: use your skill tool, or read `../../varde-knowledge/SKILL.md`; follow its session-notes-write route).

Report blocked, needs-user, and done milestones with `varde msg send`. Do not use `plan watch` for reports; it only reports plan state.
