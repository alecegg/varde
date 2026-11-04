---
topic: varde-plan/answer-sources
version: 1
summary: Record an answer by its source (chat, orchestrator, dashboard card, HOLD or ASK-MORE)
---

- Chat or direct plan edits: update Design (or Non-goals/Constraints), add
  `<question> → <answer>` to `## Decisions so far`, and remove the resolved line.
- Launched by an orchestrator: hand each open question and its options to the
  orchestrator slot to post with `--kind needs-user`. Put `plan_id`
  and the exact `question` in the notes.
- `varde plan answer` records dashboard card answers in Decisions so far.
  When the orchestrator relays one, fold it into Design. If the question
  remains under Open Questions, apply the chat rule.
- `HOLD` leaves the question open. Answer an `ASK-MORE` and hand it back to the
  orchestrator to repost.
