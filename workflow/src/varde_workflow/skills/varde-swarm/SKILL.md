---
name: varde-swarm
requires: [varde-orchestrate]
recommends: [varde-knowledge]
description: "Use this skill when the user explicitly asks for swarm or a parallel plan set: running several selected related plans with one orchestrator per plan, relaying user decisions and approvals between them, or reporting what is in flight."
---

# Coordinate a plan set

Runs only on explicit user request, never by default. An empty invocation or a question about current work gets a status report, no launches.

Outcomes and how to validate each:

- Status is reported from files on disk and changes nothing. Validate: no plan, task or session note file differs afterwards.
- Only ready, non-overlapping plans from the chosen set are launched, one orchestrator per plan within the orchestrator cap. Validate: `varde plan readiness <plan.md> --json` shows each launched plan ready.
- Each plan has an assigned slot and an address marker in its orchestrator's first prompt. Validate: `varde plan assign <PLAN> <SLOT>` and `varde msg address new <SLOT> --plan <PLAN>` ran; commands run from the repo root.
- Multi-task plans run in pipeline mode by default.
- A merge is confirmed only by `varde plan merged <PLAN>`.

| The step is | Read |
|---|---|
| Report current work or an empty invocation | `references/status.md` |
| Select, order and launch plans | `references/orchestrate.md` |
| Relay, watch and keep notes | `references/main-agent.md` |
| Progress reply to the user | `references/main-agent-replies.md` |
| A command was denied | `references/varde-workflow-cli.md` |
| Change a status | `references/workflow-state.md` |
