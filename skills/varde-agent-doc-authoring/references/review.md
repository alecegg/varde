# Review an agent document

Audit every item in scope adversarially.

For a skill or agent document edit, have an agent other than the editor, with a
clean context, review every route it touches. Fix each whole-route finding or
report it to the user; never waive one as out of scope.

Docs edits routed by `references/review-gates.md` get the writing review only.

**Dispatched review:** when dispatched as a reviewer, write no fixes; write the
findings to `review.md` under the report header in `references/review-gates.md`.

## 1. Check the scope

1. Read `references/criteria.md`. For a skill, also read
   `references/specification.md` and run
   `varde doc frontmatter <skill-dir>`.
2. Inventory the scope; run `varde doc lint <skill-dir-or-file>` and, for a whole skill, `varde doc flow <skill-dir>` (criteria: Scripts and length checks; Loading and references).
3. Check every item (including references, scripts, templates, and evals)
   against the criteria, answering Optimize each item's questions in order.
4. Separate correctness
   defects (contradictions, broken behavior) from value judgments, and mark
   untested effects as uncertain.

## 2. Create the fix list

Number findings from most in need of a fix to least. For each finding, give:

- location
- evidence
- value/cost judgment
- one fix when it is obvious; otherwise at least three distinct options with
  enough detail to judge tradeoffs, and one recommended

List retained items briefly so the report covers the full inventory; they
need no invented fixes.

List execution-cost optimizations (criteria: Optimize each item) in their own
group, as options for the user to decide.

## 3. Apply clear fixes

Skip when you may not edit (report-only, restricted writes, or dispatched as a
reviewer).

Never apply an execution-cost optimization. Otherwise, for each finding whose
fix clearly preserves intended functionality and accuracy:

1. Apply the fix, then refresh FLOW.md with
   `varde doc flow --write <skill-dir>`.
2. Verify it and mark it **Fixed** in the list, naming the applied option.

## 4. Deliver the list

Save a user-requested review as Markdown in the workspace (or supplied
location) and respond with a summary and link; return an agent-requested
review to its caller. Delegating a user request keeps it user-requested.
