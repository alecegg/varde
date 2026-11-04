---
topic: varde-review/pipeline-mode
version: 1
summary: Reviewer-slot handoff and the findings follow-up queue in pipeline mode
---

## Pipeline mode

- For the reviewer slot on an approved multi-task plan, review the one plan-level item and follow `varde-reviewer`'s handoff. Use the standalone contract otherwise.
- `finish --outcome findings` queues the builder follow-up. The queue's follow-up depth cap refuses deeper enqueues, and `finish` reports `cap-reached` (decide whether the remaining work needs a separately scoped item).
