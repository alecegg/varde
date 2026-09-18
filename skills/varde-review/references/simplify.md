# Simplify mode

## Resolve the diff scope

Default to uncommitted changes — working tree plus staged — against `HEAD`.
Narrow when the request says so: to staged changes only, to a named ref instead
of `HEAD`, or to named files, which are still line-ranged against `HEAD` or the
named ref.

## Workflow

1. **Load the instructions.** Read `references/simplify-scope.md` for how changed-line
   ranges are computed and merged from `git diff`. Load
   `references/simplify-principles.md` for the simplification principles that govern
   every edit this skill makes. Load `references/varde-code.md` if that CLI is on
   PATH, for diff-scoped symbol lookups that replace some of step 5's context
   reads.
2. **Keep the source location.** Run in the checkout that owns the selected
   diff. A new worktree starts clean and cannot simplify the invocation's
   uncommitted changes. If concurrent editing makes that checkout unsafe, stop
   and ask the user to pause the competing work or invoke this pass against a
   committed ref range instead.
3. **Compute scope.** Derive the changed-file list and line ranges (or
   whole-file for newly added files) per `references/simplify-scope.md`. With no
   changes found, report that and stop.
4. **State the plan.** Report the resolved diff source (working tree /
   staged / named ref) and the file list with their line ranges before editing
   anything.
5. **Apply edits.** One file at a time, per `references/simplify-principles.md`.
   Surrounding code is context to read; the listed ranges are what you edit.
   Newly added files may be edited in full.
6. **Verify.** Run the project's existing test command after each file's
   edits — when `varde-code` is available, use `tests_for_file` to scope this
   to the tests actually covering the edited file instead of the whole
   suite where the project's test runner supports targeting individual
   files; fall back to the full command otherwise. A failing run reverts
   that file's edits (`git checkout -- <path>` for a tracked file, or
   discard the edit for a new file) before moving to the next file, so the tree
   is never left worse than it started. A green run only proves
   behavior-preservation if the tests actually exercise the edited lines — if
   the edited lines have no covering test, say so in the report rather than
   treating the green run as proof.
7. **Report.** A short summary: files touched, what changed and why, and any
   worthwhile improvement that fell outside scope (name it, don't apply it).
8. **Record lessons.** Invoke `varde-knowledge reflect`, scoped to this run. It
   records friction and durable lessons only — a handoff belongs at a
   session boundary, which this is not.

## Gotchas

- Newly added files are in scope in full; files with deletions-only hunks have
  nothing to simplify — skip them.
- This pass has no findings store and no review folder — it edits inline and
  reports a summary directly to its caller. Use report mode when persisted,
  triaged findings are needed; use fix mode to apply an existing review's
  findings.
- This pass edits the checkout containing its input diff, creating no worktree
  of its own. A caller's worktree stays valid because it holds that diff, and
  the caller owns its merge.
