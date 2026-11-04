---
topic: varde-doc-authoring/review
version: 1
summary: Review intro, step 4 of 4 - read last; clean-context reviewer, no fixes if dispatched
---

# Review an agent document edit

Audit every item in scope adversarially.

For an agent document edit, have an agent other than the editor, with a
clean context, review every route it touches. Fix each whole-route finding or
report it to the user; never waive one as out of scope.

**Dispatched review:** when dispatched as a reviewer, write no fixes; write the
findings to `review.md`.

## 4. Deliver the list

Save a user-requested review as Markdown in the workspace (or supplied
location) and respond with a summary and link. Return an agent-requested
review to its caller. Delegating a user request keeps it user-requested.
