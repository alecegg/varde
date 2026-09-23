# Simplification principles

Apply these principles after `references/simplify-scope.md` identifies the
files and line ranges.

- **Preserve functionality.** Keep the code's behavior unchanged. Every
  existing test must still pass.
- **Apply project standards.** Follow this repo's `CLAUDE.md` and `AGENTS.md`
  conventions before the generic preferences below.
- **Enhance clarity.** Reduce complexity and nesting. Remove redundant code
  and abstractions. Improve names and consolidate related logic. Keep comments
  that explain design rationale, business rules, non-obvious behavior, or
  intent. Remove only noise, such as `// increment i` above `i++`. For more
  than one condition, prefer a `switch` or `if`/`else` chain to a nested
  ternary.
- **Prioritize readability over fewer lines.** Keep an abstraction that earns
  its place, even when it looks small alone. Keep unrelated concerns in
  separate functions, even when merging them shortens the diff. A clever
  solution that is hard to follow is worse than the original.
- **Keep security and safety code.** Keep authentication and authorization
  checks, input validation, sanitization, data-loss protection such as
  confirmations and backups, guards on destructive operations, and
  accessibility affordances. Keep them even when a check looks dead in the
  changed lines. It may handle a case elsewhere. If a check seems to block
  legitimate use, restore the pre-change behavior and flag it in the closing
  summary. Do not weaken an assertion, loosen a type, or narrow validation to
  make a test pass.

## Steps

1. For each file in scope, read its changed-line ranges and enough surrounding
   code to understand the intent.
2. Identify concrete improvements within those lines only. Look for dead code,
   unclear names, redundant logic, and patterns inconsistent with the file.
3. Apply changes one file at a time. Keep every edit inside its listed ranges.
4. After each file's edits, run the project's test command
   (`references/simplify.md` step 6) before moving to the next.
5. Put worthwhile simplifications outside the listed ranges in the closing
   summary as unapplied recommendations.

Use a refactor-posture build for feature work, public API changes, and
refactoring beyond the listed ranges. A full `varde-review report` can also
record those changes as findings.
