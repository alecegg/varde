# Workflow state

| Artifact | Legal values | Initial |
|---|---|---|
| `plan` | `backlog`, `active`, `blocked`, `completed`, `cancelled` | `backlog` |
| `task` | `todo`, `in_progress`, `blocked`, `done` | `todo` |

- `varde plan validate` flags a value outside this table; `varde plan readiness` reports ready tasks.
