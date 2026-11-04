---
topic: varde-orchestrate/pipeline-mode
version: 1
summary: Per-role pull queues, eligibility, and block rules
---

# Pipeline mode

Use per-role pull queues for approved multi-task plans. Orchestrators enqueue work and launch workers; workers share each role's pool and claim their next eligible item. Use the per-task worker flow (`dispatch` topic) only when pipeline slots are unsupported or unavailable, or when main or the user selects that fallback.

## Queue protocol

- Include ownership details when enqueuing, and create task worktrees with `scripts/worktree-create.sh`. Use `--parent <item-id>` for follow-ups; unknown dependency IDs show as `waiting-on-unwritten` until written. The queue's follow-up depth cap refuses deeper enqueues, and `finish` reports `cap-reached` (decide whether the remaining work needs a separately scoped item).
- Each worker is a slot. Pull with `varde plan queue pull --role <ROLE> --slot <SLOT> --epoch <EPOCH>`, then finish with `varde plan queue finish --item <ITEM> --slot <SLOT> --epoch <EPOCH> --outcome done`; a finished builder item enqueues no reviewer, and the epoch fences stale workers.
- After finishing, pull again while status shows ready work and budget remains.

Workers follow the `worker-loop` topic (item loop, mail kinds, worker handoff file).
