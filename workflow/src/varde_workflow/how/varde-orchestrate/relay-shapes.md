---
topic: varde-orchestrate/relay-shapes
version: 1
summary: Planner question files, plan answers, and the stalled watch event
---

# Relay shapes

Use main's slot marker; run `varde msg` at the repo root. The `stalled` watch event is a 10-minute heuristic based on slot-binding activity.

- Post a planner's open question as `varde msg send --from <slot> --to main --kind needs-user --notes <decision.json>`. The file holds `"type":"question"`, `asked`, `why`, `options` (id, label), `recommendation`, `plan_id`, and the exact `question`. Relay the dashboard answer to the planner.
- Record an answer to an open plan question with `varde plan answer <PLAN> --question <text-or-index> --answer <text>`.
