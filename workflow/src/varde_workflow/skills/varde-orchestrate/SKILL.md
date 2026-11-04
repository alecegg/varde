---
name: varde-orchestrate
description: "Use this skill when the user wants an approved multi-task plan with settled scope, criteria, and tasks executed end to end: setting up its worktree branch, running its tasks through builders, integrating their commits, reviewing the result, and finishing the plan. Interactive runs pause for user choices; unattended runs continue without those pauses. It runs one plan at a time."
requires: [varde-build, varde-review]
recommends: [varde-knowledge, varde-learn, varde-skill-authoring, varde-doc-authoring]
---

# Coordinate one plan

Run an approved multi-task plan with settled scope, criteria, and tasks.

Outcomes and how to validate each:

- The plan runs on a `worktree/<plan id>` branch, with `branch:` and `base` in plan frontmatter. Plan and task frontmatter changes are committed only under authority already granted. Validate: `varde plan status` shows no staleness notice, or the notice is shown to the user.
- Open plan comments are handled before tasks start: resolved ones get `addressed` events, unresolvable ones stay open and main is told. Validate: `varde plan comments <plan> --open` lists only the unresolvable.
- Each task is built by a worker that follows the task's declared posture and edits only its assigned paths; task states change only through `varde plan task set`. Validate: `varde plan gate <task.md> --commit <sha>` passes and `varde plan check-task-ownership --task <task.md> --commit <sha> --json` is clean before integration.
- Tasks run in pipeline mode by default; the per-task flow is the fallback when slots are unavailable or main or the user selects it.
- Main hears one `varde msg send` kind per milestone; your final reply is one line.

| The step is | Read |
|---|---|
| Progress reply to main | `references/main-agent-replies.md` |
| Finish the plan | `references/build-finish.md` |
| Dispatch a reviewer | `references/review-gates.md` |
| A command was denied | `references/varde-workflow-cli.md` |
| Change a status | `references/workflow-state.md` |
