---
topic: varde-orchestrate/merge-approval
version: 1
summary: Request merge approval from main, merge on APPROVED, and report denials
---

# Merge approval

- Send merge requests as `merge-ready` from your slot to main; each becomes a dashboard approval card. On `HOLD` or `ASK-MORE`, do not merge; answer and repost.
- On the relayed `re merge-ready <msg_id>:` answer `APPROVED` for that card, run `varde plan merge <PLAN>` from a checkout on `main`. It refuses without the user's recorded approval; never write one.
- If a merge or action is denied, send main `--kind blocked` and name the exact user command that was denied.
