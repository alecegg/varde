# Acceptance criteria

Criteria are plan-level: true after ship, however build slices it. Grow them
in the growth loop (`references/plan-grow-doc.md`) and review the full set
before the final completeness check.

## Review

- **`assert:`** — a command, grep, or test whose pass/fail needs no LLM
  judgment. **`retrieve:`** — the specific file(s) or grep an LLM must read and
  judge, and what the judge looks for.
- **Prefer `assert:`.** A `retrieve:` criterion asks the agent to grade text it
  just produced, which biases the result. Before accepting one, try to restate
  it as `assert:` via a command, exit code, file existence, or non-empty output.
  Keep `retrieve:` only for semantic judgment no command can give, such as
  whether an error message explains the cause.
- **Testable as written.** Name the command that checks each criterion, or the
  file a reader judges it from. A criterion with neither is not an acceptance
  criterion: rewrite it, and when no faithful rewrite exists, stop with a
  blocker rather than weakening it.
