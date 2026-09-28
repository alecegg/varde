# Simplify mode

Simplify edits inline and reports to its caller; it keeps no findings store.

**Principles.** Preserve behavior; follow the repo's CLAUDE.md/AGENTS.md first.
Readability beats fewer lines: keep abstractions that earn their place,
rationale comments, and separate concerns; no nested ternaries. Keep security
and safety code (auth, validation, sanitization, data-loss and destructive-op
guards, accessibility) even when it looks dead; never weaken an assertion,
loosen a type, or narrow validation to make a test pass.

Apply `references/review-gates.md` before edits and at completion; a
caller-approved plan can cover this pass when its scope and assumptions hold.

## Workflow

1. **Edit in the current checkout, no worktree;** if concurrent edits make it
   unsafe, stop and ask.
2. **Compute scope.** The source defaults to working tree plus staged changes
   against `HEAD` plus untracked files (`git ls-files --others --exclude-standard`
   — each one is whole-file in scope); narrow to staged
   only, a named ref, or named files on request. For everything else, scope is
   the lines added or changed in `git diff -U0 <source>`: a whole added file,
   nothing for a pure deletion. Read outside the ranges for context; edit only
   inside them. With no diff and no untracked files, report that and stop.
3. **Map the connections.** With `varde-code`, per `references/varde-code.md`:
   changed symbols, dependents per changed file, tests to verify with, and
   whether a new public helper duplicates an existing one. Without it, grep
   for callers and similar helpers. A changed symbol used outside scope keeps
   its name and signature; simplify only its body. Replacing new code with a
   call to an existing helper is in scope.
4. **Edit one file at a time, per the principles above, then verify once.**
   Snapshot each existing file under a per-run backup directory using its
   repository-relative path; record any newly created files. After all edits,
   run the project's
   tests — only the `tests_for_file` set when the runner can target files. On
   failure, restore snapshots to their original paths one file at a time and
   delete newly created files until the tests pass again
   (`git checkout` would also discard the diff under review). A pass proves
   behavior preserved only when tests exercise the edited lines; if they do
   not, say so.
5. **Report** files touched, what changed, why, and any obstacle you hit. List
   worthwhile improvements outside scope as unapplied recommendations.
6. **Record lessons.** Record real obstacles through `varde-learn` and durable
   decisions through `varde-knowledge`; otherwise skip.
