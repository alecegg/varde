---
topic: varde-orchestrate/pipeline-handoff
version: 1
summary: Register slots, hand off at thresholds, reclaim after a crash
---

# Pipeline handoff

- Register the slot at launch with `varde plan slot register <SLOT> --plan <PLAN> --role <ROLE> --agent-ref <AGENT>`; the slot owns its claims and records progress, context tokens and turns. `notes/slot-turns/<slot>.json` is its exported cursor.
- `pipeline-slot-check` heartbeats the slot each counted turn; off Paseo, run `varde plan slot heartbeat <SLOT> --epoch <EPOCH> --progress <ITEM> --context-tokens <N> --turn-count <N>`.
- Worker/reviewer thresholds: 250k context tokens or 60 turns, whichever comes first; the 350k hard stop waits for a completed checkpointed turn. Orchestrators hand off at 400k at a completed turn, with main archiving the old slot.
- At a threshold, run `varde plan slot handoff <SLOT> --epoch <EPOCH>`, then launch the replacement and have it run `varde plan slot resume <SLOT> --agent-ref <AGENT>` for its resume prompt.
