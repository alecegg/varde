# Simplification principles

Follow these for every edit, once `references/simplify-scope.md` has identified
the files and line ranges.

- **Preserve functionality.** This is a clarity pass: the code does the same
  thing afterwards and every existing test still passes.
- **Apply project standards.** This repo's `CLAUDE.md` / `AGENTS.md` conventions
  win over any generic preference below.
- **Enhance clarity.** Reduce complexity and nesting, drop redundant code and
  abstractions, improve names, consolidate related logic. Keep comments that
  carry design rationale, business rules, non-obvious behavior, or intent;
  remove only noise (`// increment i` above `i++`). Past one condition, prefer a
  `switch` or `if`/`else` chain to a nested ternary.
- **Prioritize readability over fewer lines.** Keep an abstraction that earns its
  place even when it looks small in isolation, and keep unrelated concerns in
  separate functions even when merging them would shorten the diff. A clever
  solution that is hard to follow is a worse outcome than the original.
- **Keep security and safety code.** Authentication and authorization checks,
  input validation, sanitization, data-loss protection (confirmations, backups,
  guards on destructive operations), and accessibility affordances all stay —
  including when a check looks dead in the diff's local context, since it may
  exist for a case outside the changed lines. If one appears to block legitimate
  usage, restore the pre-change behavior and flag it in the closing summary
  rather than weakening an assertion, loosening a type, or narrowing a
  validation to make something pass.

## Steps

1. For each file in scope, read its changed-line ranges plus enough surrounding
   code to understand the intent.
2. Identify concrete improvements within those lines only: dead code, unclear
   names, redundant logic, patterns inconsistent with the rest of the file.
3. Apply changes one file at a time, keeping every edit inside that file's
   listed ranges.
4. After each file's edits, run the project's test command
   (`references/simplify.md` step 5) before moving to the next.
5. A worthwhile simplification that would reach outside the listed ranges goes
   into the closing summary as a recommendation, unapplied.

Feature work, public API changes, and refactoring beyond the listed ranges
belong in a refactor-posture build or a full `varde-review report` finding.
