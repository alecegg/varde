# Workflow state

An unknown status (`draft`, or a task in `backlog`) makes later CLI calls fail
with `unknown status`.

| Artifact | States | Initial | Legal moves |
|---|---|---|---|
| `plan` | `backlog`, `active`, `blocked`, `completed` | `backlog` | `backlog` to `active` or `blocked`; `active` to `blocked` or `completed`; `blocked` to `active`; `completed` is terminal |
| `task` | `todo`, `in_progress`, `blocked`, `done` | `todo` | `todo` to `in_progress` or `blocked`; `in_progress` to `blocked` or `done`; `blocked` to `in_progress`; `done` is terminal |

Change status through `transition`, never by editing `status` directly:

```bash
varde-workflow readiness <plan.md> --json
varde-workflow graph <any-sibling>/plan.md --json
varde-workflow transition <artifact.md> <state> --json
varde-workflow validate <artifact.md> --json
```

- Run `graph` on a sibling, not the parent. A group `plan.md` returns one node
  and no edges.
- A rejected transition (`workflow_blocked`) lists legal states and changes no
  bytes.
- `recover --root <project-root>` finishes an interrupted accepted transition.
