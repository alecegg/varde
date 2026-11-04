---
topic: varde-swarm/orchestrator-handoff
version: 1
summary: Orchestrator handoff relaunch and main address supersede, migrate, refresh and bind commands
---

## Orchestrator handoff and address binding

- On an orchestrator `info` "handoff", archive the old orchestrator, then launch its replacement with `varde-runner agent launch --role <ROLE> --workspace <ID> --prompt <BOOTSTRAP> --slot <SLOT> --plan <PLAN>`. The bootstrap tells it to run `varde plan slot resume <SLOT> --agent-ref <agent>` and follow the printed prompt. That prompt lists the claimed items, child slots and next actions; the supersede alert is expected.
- Run `varde msg address new main --supersede`; the user supplies the printed marker at the next session start (or starts it with `VARDE_ADDRESS=main`), then run `varde msg migrate` once.
- Use `varde msg address refresh` only for an existing binding. For an unbound session, issue a marker with `varde msg address new <SLOT>` and bind it with `varde msg address bind <MARKER> --session <ID> --harness <HARNESS>`.
