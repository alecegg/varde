# Simplify mode

## Principles

- Preserve behavior and rationale comments; favor readability over brevity;
  keep abstractions that earn their place; no nested ternaries.
- Keep security and safety code (auth, validation, data-loss guards,
  accessibility) even when it looks dead.
- Never weaken an assertion, loosen a type, or narrow validation to pass a
  test.

## Workflow

Simplify edits get the one independent review per change (load `varde-change`: use your skill tool, or read `../../varde-change/SKILL.md`).

1. Simplify edits committed work; undo with git. With uncommitted changes in scope, stop and ask the user to commit or allow a WIP commit.
2. **Compute scope** with `scripts/change-ranges.sh [--staged | --ref <ref>] [-- <file>...]`
   using `--ref <commit before the change>`; edit
   only inside the printed ranges; read outside them for context. Empty
   output: report that and stop.
3. **Map the connections:** callers, tests for the changed files, and existing
   helpers that a new one duplicates (`varde map` per
   `references/varde-code-cli.md`). A changed symbol used outside scope
   keeps its name and signature; replacing new code with a call to an existing
   helper is in scope. Scope lookups to the diff.
4. **Edit one file at a time, then verify once.** After all edits, run the
   project's tests (only `tests_for_file` when the runner can target files);
   say if they do not exercise the edited lines.
5. **Report** files touched, what changed, why, and any obstacle you hit. List
   worthwhile improvements outside scope as unapplied recommendations.
