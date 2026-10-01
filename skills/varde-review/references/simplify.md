# Simplify mode

## Principles

- Preserve behavior and rationale comments; favor readability over brevity;
  keep abstractions that earn their place; no nested ternaries.
- Keep security and safety code (auth, validation, data-loss guards,
  accessibility) even when it looks dead.
- Never weaken an assertion, loosen a type, or narrow validation to pass a
  test.

## Workflow

1. **Edit in the current checkout, no worktree;** if concurrent edits make it
   unsafe, stop and ask.
2. **Compute scope** with `scripts/change-ranges.sh [--staged | --ref <ref>] [-- <file>...]`
   (default: working tree and staged vs `HEAD`, plus untracked files). Edit
   only inside the printed ranges; read outside them for context. Empty
   output: report that and stop.
3. **Map the connections:** callers, tests for the changed files, and existing
   helpers that a new one duplicates (`varde-code` per
   `references/varde-code-cli.md`, else grep). A changed symbol used outside scope
   keeps its name and signature; replacing new code with a call to an existing
   helper is in scope. Scope lookups to the diff and include untracked files
   separately with `git ls-files --others --exclude-standard`.
4. **Edit one file at a time, then verify once.** Before editing or creating a
   file, run `scripts/snapshot.sh save <backup-dir> <file>...` with a per-run
   `mktemp -d` directory; after all edits, run the project's tests (only
   `tests_for_file` when the runner can target files). On failure, restore one
   file at a time with `scripts/snapshot.sh restore <backup-dir> <file>` until
   tests pass, never `git checkout`, which discards the diff under review; say
   so if the tests do not exercise the edited lines.
5. **Report** files touched, what changed, why, and any obstacle you hit. List
   worthwhile improvements outside scope as unapplied recommendations.
