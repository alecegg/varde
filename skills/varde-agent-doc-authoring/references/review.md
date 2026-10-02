# Review an agent document

Audit every item in scope adversarially.

**Gate review:** when dispatched as a review-gate reviewer, write no fixes and
record evidence per `references/review-gate-record.md`, not a saved Markdown
list.

## 1. Check the scope

1. Read `references/criteria.md`. For a skill, also read
   `references/specification.md` and run
   `uv run scripts/validate-frontmatter.py <skill-dir>` (in a sandbox, prefix
   `UV_PYTHON_PREFERENCE=only-system`).
2. Inventory the scope; run `scripts/check-length.py` and, for a whole skill,
   `scripts/skill-flow.py` on it (criteria: Scripts and length checks;
   Loading and references).
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

Skip this step when:

- the request is report-only
- the caller restricts writes
- you were dispatched only to review (another agent owns the edits)

Never apply an execution-cost optimization. Otherwise, for each finding whose
fix clearly preserves intended functionality and accuracy:

1. Apply the fix, then refresh FLOW.md with
   `scripts/skill-flow.py --write <skill-dir>`.
2. Verify it and mark it **Fixed** in the list, naming the applied option.

## 4. Deliver the list

- User-initiated review: save the list as Markdown in the current workspace
  (or a supplied location) and respond with a summary and link.
- Agent-initiated review: return the list to that agent.

Delegating a user request does not change its origin.
