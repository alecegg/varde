# Orchestrate mode

Choose one branch. Load only its named reference.

| The request is | Action |
|---|---|
| Names a group plan | Load `references/orchestration-run.md`. |
| Requests a whole feature without naming a group | Load `references/orchestration-discovery.md`. |
| Names one non-group plan | Invoke `varde-change build plan=<id>`. Stop. |

Orchestration applies only to group plans with multiple children.
A group has `shape: group` in its `plan.md`.
Its child plans live in nested child directories.

Discovery never executes a group before user selection.
Named execution runs children sequentially through `varde-change build`.
The orchestrator never edits production source or dispatches tasks.
