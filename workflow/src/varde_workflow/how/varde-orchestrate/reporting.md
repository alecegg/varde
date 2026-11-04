---
topic: varde-orchestrate/reporting
version: 1
summary: Report milestones to main, decision-file shapes, and merge approval
---

## Reporting to main

- Send requests with `varde msg send --from <me> --to main --kind needs-user --notes <abs decision.json> <title>`. Use the decision-file shapes below and include each request in the final reply.
- Use request kinds `needs-user`, `blocked`, `merge-ready`, `done`, `info`, or `stale`; send each milestone with one kind. Keep the final reply to one line.
- Confirm only the merge slot and merge approval; fold other confirmations into the next milestone message.
- Approval decision file:

  ```json
  {"type":"approval","approval":"merge","title":"Merge","asked":"May I merge?","why":"Checks passed","options":[{"id":"approve","label":"Approve"}],"recommendation":"approve","evidence":[{"kind":"diff","caption":"Diff","text":"2 files"}]}
  ```

- Evidence paths must be absolute under `working/plans/` and end in jpg, jpeg, png, webp, md, or txt; diff evidence uses inline `text`.
