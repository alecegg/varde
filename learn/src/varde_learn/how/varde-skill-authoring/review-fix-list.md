---
topic: varde-skill-authoring/review-fix-list
version: 1
summary: Skill review steps 2-3 of 4 - fix list, apply; clean-context, never apply cost options
---

# Create and apply the review fix list

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
   `varde learn check --write <skill-dir>`.
2. Verify it and mark it **Fixed** in the list, naming the applied option.
