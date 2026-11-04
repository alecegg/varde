# Workflow state

| Artifact | Legal values | Initial |
|---|---|---|
| `plan` | `backlog`, `active`, `blocked`, `completed`, `cancelled` | `backlog` |
| `task` | `todo`, `in_progress`, `building`, `in_review`, `fixing`, `integrating`, `blocked`, `done` | `todo` |

- `in_review` and `fixing` are valid but unused by orchestration.
- `varde plan validate` flags a value outside this table.
