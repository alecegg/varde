---
topic: varde-build/escalation-routes
version: 1
summary: Route requests that are not one bounded build task to the skill that owns them
---

- Honor explicit review requests with `varde-review`; send exploration-only
  requests to `varde-explore` and verify-only requests to `varde-verify`.
- Do not decompose or coordinate multiple tasks: escalate them to
  `varde-orchestrate`, or to `varde-plan` first when scope is unsettled.
- A builder slot on an approved multi-task plan follows `varde-builder`'s
  pipeline item loop and handoff by default. Use the one-task contract for
  standalone tasks or the orchestrator's per-task fallback.
- Escalate a micro change to `varde-plan` when scope is unsettled, or
  `varde-orchestrate` when several tasks are settled.
- For one standalone review finding, load `varde-review` and follow its fix
  guidance. Record the finding with its concrete solution and decision
  evidence, apply it, and update only that finding's status.
