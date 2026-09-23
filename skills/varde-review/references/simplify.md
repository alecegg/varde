# Simplify mode

## Resolve the diff scope

Use uncommitted changes by default. Compare the working tree and staged changes
against `HEAD`. Narrow the scope when requested: staged changes only, a named
ref instead of `HEAD`, or named files. Named files still use line ranges
against `HEAD` or the named ref.

## Workflow

1. **Load the instructions.** Read `references/simplify-scope.md` to learn how
   to compute and merge changed-line ranges from `git diff`. Read
   `references/simplify-principles.md` for the principles governing every edit.
   Load `references/varde-code.md` only for several files, covering tests, or
   structural relationships. Read known changed lines directly. Use
   `get_symbol` only for exact symbols inside large files.
2. **Keep the source location.** Run in the checkout that owns the selected
   diff. A new worktree starts clean and cannot simplify the invocation's
   uncommitted changes. If concurrent editing makes that checkout unsafe, stop.
   Ask the user to pause the competing work or run this pass against a
   committed ref range instead.
3. **Compute scope.** Use `references/simplify-scope.md` to derive the changed
   file list and line ranges. Use the whole file for newly added files. If no
   changes exist, report that and stop.
4. **State the plan.** Before editing, report the resolved diff source, which
   can be the working tree, staged changes, or a named ref. Also report each
   file and its line ranges.
5. **Apply edits.** Edit one file at a time using
   `references/simplify-principles.md`. Read surrounding code for context. Edit
   only the listed ranges. Newly added files may be edited in full.
6. **Verify.** Run the project's existing test command after each file's edits.
   When `varde-code` is available, use `tests_for_file` to run tests covering
   that file instead of the whole suite, if the test runner supports targeting
   files. Otherwise, run the full command. If a run fails, revert that file's
   edits before moving on. Use `git checkout -- <path>` for a tracked file, or
   discard the edit for a new file. The tree must not be worse than it was.
   A passing run proves behavior preservation only when tests exercise the
   edited lines. If they do not, say so in the report.
7. **Report.** Give a short summary of files touched, what changed, and why.
   Name worthwhile improvements outside the scope, but do not apply them.
8. **Record lessons.** Invoke `varde-knowledge reflect` for this run. Record
   friction and durable lessons only. Record a handoff at a session boundary,
   not during this run.

## Gotchas

- Newly added files are in scope in full. Files with deletions-only hunks have
  no current lines to simplify, so skip them.
- This pass has no findings store or review folder. It edits inline and reports
  a summary directly to its caller. Use report mode when you need persisted,
  triaged findings. Use fix mode to apply an existing review's findings.
- This pass edits the checkout containing its input diff. It creates no
  worktree. A caller's worktree remains valid because it holds that diff, and
  the caller owns the merge.
