---
topic: varde-plan/finalize-review
version: 1
summary: Run the Finalize review (reviewer rounds, completeness check, confirmation, ready)
---

1. Give an independent reviewer the plan, tasks, lint warnings, and resolved
   `<working>`/`<knowledge>` paths. Include each task's origin (user request or
   friction id, named by the planner).
2. Tell the reviewer to remove or defer no scope. Tell it to record each
   recommended cut as a question with its reason and options (keep, change
   approach, cut).
3. Tell the reviewer to judge user-requested work on usefulness, cost, and
   alternatives including doing nothing, never on missing friction evidence.
   For friction-derived work, friction evidence is the main backing.
4. Ask for one report-only round, written to `<plan-dir>/notes/plan-review.md`.
   Apply the findings except cuts, ask the user about cuts, then request one
   fixes-only re-check.
5. Ask the final completeness check: group unseen assumptions and changes by
   impact, one line each, and ask "Anything left to resolve before we finalize?"
   Apply changes and run one fixes-only re-check.
6. After confirmation, record `reviewed_commit` and `reviewed_on` in the plan
   frontmatter.
7. Make no more content changes. Announce `Plan <plan-id> is ready; ask to build it.`
