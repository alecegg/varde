# Scope

Use this reference to find the lines this pass may edit. Do this before step 4
of `references/simplify.md`.

## Resolving the diff source

- Default with no arguments: compare the working tree, including staged
  changes, against `HEAD`. Use `git diff --name-status HEAD` for the file list.
- Staged changes only: compare the index against `HEAD`. Add `--cached` to both
  commands below.
- Named ref: compare against that ref instead of `HEAD` in both commands.
- Named paths: skip name-status discovery and treat each path as
  `status: modified`. Still compute line ranges with the hunk diff below.
- If the primary diff source reports no files, use `git diff --name-status
  HEAD~1` against the previous commit. Do this before concluding that nothing
  needs simplification. A fresh commit with a clean working tree remains
  reviewable.

## File list and status

`git diff --name-status <source>` returns one line for each file:
`<status-code>\t<path>` or `<status-code>\t<old-path>\t<new-path>` for
renames and copies. Map status codes as follows: `M` means modified, `A` means
added, `R*` means renamed, and `C*` means copied. For renames and copies, use
the new path. Deleted files (`D`) have nothing to simplify, so drop them from
scope.

## Line ranges per file

For every non-added file, run:

```
git diff --unified=0 --no-ext-diff <source> -- <path>
```

Parse each hunk header in this form: `@@ -<old-start>,<old-count>
+<new-start>,<new-count> @@`. Counts are omitted when they equal 1. The
scope range is `[new-start, new-start + new-count - 1]`. These line numbers
refer to the *current* file, not the old file. A hunk with `new-count = 0` is a
pure deletion. It has no current lines to simplify, so skip it.

Merge adjacent or overlapping ranges into one range in hunk order. Merge when
the next range starts within 1 line of the previous range's end. This keeps the
scope compact and removes one-line gaps.

For added files (`status: added`), skip hunk parsing entirely. The whole file
is in scope.

## What "in scope" means for editing

- A line range includes both endpoints. It refers to the current file before
  this pass edits it.
- Read outside the range when context requires it. Do not edit outside the
  range, regardless of how minor the edit seems.
- If changed lines produce zero ranges after merging, treat the file as having
  nothing to simplify and skip it. For example, this can happen when
  whitespace-only hunks produce an empty diff under `--unified=0`. Do not
  guess.
