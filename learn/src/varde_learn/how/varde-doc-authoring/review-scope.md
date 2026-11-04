---
topic: varde-doc-authoring/review-scope
version: 1
summary: Doc review step 1 of 4 - check scope; clean-context reviewer, dispatched writes no fixes
---

## 1. Check the scope

1. Read `references/criteria.md` (Cut or keep).
2. Inventory the scope and run `varde learn check <file>`. Report the word-count or tokenizer delta against the base ref, and flag text that can be shorter.
3. Check every item (including references, scripts, templates, and evals)
   against the criteria, answering Optimize each item's questions in order.
4. Fail the review on any violation of `references/conditions.md`: an instruction kept without cited evidence, or a rule stated twice.
5. Separate correctness
   defects (contradictions, broken behavior) from value judgments, and mark
   untested effects as uncertain.
