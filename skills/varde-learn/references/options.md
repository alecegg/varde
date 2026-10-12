<!-- kind: reference -->
# Propose and audit options

When proposing solutions, include an option that simplifies by removing one of these:

- A rule.
- A step.
- A gate.
- A check.
- A feature.

State its upside and cost or downside. Get user approval before removing a feature or guarantee.

When auditing a gate, rule or forced tool step, answer:

1. What failure does it prevent, and has that failure occurred?
2. What are its instruction-token cost and the work it adds through tool cycles, blocks or rework?
3. Could an outcome check replace the prescribed path?
4. Does it carry state other agents need? If so, prefer a small fixed-format artifact over a procedure.

Give each proposal one tag:

- `keep-invariant`.
- `convert-to-outcome-check`.
- `replace-with-state-artifact`.
- `remove`.

Keep these invariants unless the user approves changing them:

- Exact-content binding.
- Reviewer independence.
- No self-approval.
- Task ownership.
