---
topic: varde-skill-authoring/review-scope
version: 1
summary: Skill review step 1 of 4 - check scope; clean-context reviewer, dispatched writes no fixes
---

# Check the review scope

## 1. Check the scope

1. Read `references/criteria.md` and run
   `varde learn check <skill-dir>`.
2. Inventory the scope and run `varde learn check <skill-dir-or-file>` (criteria: Scripts and length checks; Loading and references). For each touched skill, run `varde learn measure <skill> flow --json` on the base ref and working tree. Report each touched route's before/after `main_min_tokens`–`main_max_tokens` from `data[].routes[]`, and flag text that can be shorter. If it errors, read `data.error.details`.
3. Fail the review on any violation of `references/conditions.md`:
   - a `skill-refs`, `eval-content`, or unexplained `how-steps` warning.
   - another skill named.
   - HOW kept without cited evidence.
   - a partial trim.
4. Check every item (including references, scripts, templates, and evals)
   against the criteria. Apply the How versus what test and the
   residual-HOW end-state condition, then answer Optimize each item's
   questions in order.
5. Separate correctness
   defects (contradictions, broken behavior) from value judgments, and mark
   untested effects as uncertain.
