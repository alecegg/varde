---
topic: varde-diagnose/capture-steps
version: 1
summary: 1 of 2 - check one incident is eligible; ambiguous witness or grouping goes in the report
---

For each distinct eligible incident:

1. Confirm no matching friction item already represents it. Pick one canonical triggering event; if its witness boundary or item grouping is ambiguous, record the finding in the report instead.
2. For a failed-tool candidate, inspect the exact anchored native tool result; a normalized status label or excerpt alone does not prove failure.
3. Set `--kind` to `failed-tool`, `repeated-work`, or `workflow-deviation`. Choose `--item-id <ID>` for an existing item, or `--item-source` and `--item-title` (plus optional `--item-target`) for a new one. Take `--source-id` and `--record-index` from the frozen bundle's inspect record.
