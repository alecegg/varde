# Principles

The four principles every edit in this pass must satisfy, plus the process
for applying them once `SCOPE.md` has resolved the file/line-range list.

## Principles

- **Preserve functionality.** Never change what the code does. All existing
  tests must continue to pass. This is a clarity pass, not a logic change.
- **Apply project standards.** Follow conventions from this repo's
  `CLAUDE.md` / `AGENTS.md` if present, over any generic preference below.
- **Enhance clarity.** Reduce unnecessary complexity and nesting, eliminate
  redundant code and abstractions, improve variable and function names, and
  consolidate related logic. Keep comments that explain design rationale,
  business rules, non-obvious behavior, or intent; remove only truly
  redundant noise (e.g. `// increment i` above `i++`). Avoid nested ternary
  operators — prefer a `switch` or `if`/`else` chain for more than one
  condition.
- **Maintain balance.** Do not over-simplify. Avoid overly clever solutions
  that are hard to understand. Do not combine unrelated concerns into a
  single function just to shorten the diff. Do not remove a helpful
  abstraction because it looks small in isolation. Prioritize readability
  over fewer lines.
- **Protect trust-boundary and safety code.** Never simplify away
  authentication/authorization checks, input validation, security
  sanitization, data-loss protection (confirmations, backups, guards against
  destructive operations), or accessibility affordances — even when a check
  looks dead or redundant in the diff's local context; it may exist for a
  case outside the changed lines. If a check appears to block a legitimate
  test or usage, revert the code to its pre-change behavior and flag it in
  the closing summary — never weaken an assertion, loosen a type, or narrow
  a validation just to make something pass.

## Process

1. For each file in scope, read its changed-line ranges and enough
   surrounding code to understand the intent of that code.
2. Identify concrete improvements within those lines only: dead code,
   unclear names, redundant logic, inconsistent patterns relative to the
   rest of the file.
3. Apply changes one file at a time, keeping every edit inside that file's
   listed ranges.
4. After each file's edits, run the project's test command (per `SKILL.md`
   step 5) before moving to the next file.
5. If a worthwhile simplification would require editing lines outside the
   listed ranges, leave it alone and record it for the closing summary
   instead of applying it.

Do not add new features, change public APIs, or refactor code outside the
listed line ranges — even when the improvement is obviously good. That
belongs to a deliberate refactor pass (`build posture=refactor`) or a full
`/varde-review` finding, not this pass.
