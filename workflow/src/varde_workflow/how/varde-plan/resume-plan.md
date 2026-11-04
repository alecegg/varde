---
topic: varde-plan/resume-plan
version: 1
summary: Pick up an existing plan; open comments and which backlog plan to resume
---

- At pickup, read `plans/<id>/comments.jsonl` and resolve open comments first.
  Update the plan or task work, and append an `addressed` event for each
  resolved comment.
- To resume without a named plan, search `<working>/plans/` for a `plan.md`
  with `status: backlog` and a live Open Questions bullet. One: resume it.
  Several: list them as `title - path` and ask which. None: wait for the idea.
