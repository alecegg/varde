---
topic: varde-orchestrate/pipeline-checkpoints
version: 1
summary: Run pipeline-slot-check at turn boundaries and act on its result
---

# Pipeline checkpoints

- At each Paseo turn boundary, save the `get_agent_status` snapshot as JSON and run `varde hook pipeline-slot-check --plan-dir <abs-plan-dir> --slot <slot> --role <role> --item <item> --status-file <abs-status.json>`.
- On `continue` from `pipeline-slot-check`, proceed.
- On `checkpoint_required`, prompt the agent to write the record it names to `notes/checkpoints/<plan-id>-<role>/latest.json`, then check again.
- On `handoff_required`, hand off per the `pipeline-handoff` topic before the next item.
- On `one_shot_required`, stop using a long-lived slot.
