# Scope

How to compute the exact set of changed lines this pass is allowed to touch.
Get this right before step 4 of `SKILL.md` — every later step depends on it.

## Resolving the diff source

- Default (no args): compare the working tree (including staged changes)
  against `HEAD` — `git diff --name-status HEAD` for the file list.
- `--staged`: compare only the index against `HEAD` — add `--cached` to both
  commands below.
- `--ref=<ref>`: compare against `<ref>` instead of `HEAD` in both commands.
- Explicit paths given as arguments: skip the name-status discovery step and
  treat each path as `status: modified` directly, but still compute its line
  ranges via the hunk diff below.
- If the primary diff source reports zero files, fall back to `git diff
  --name-status HEAD~1` (comparing against the previous commit) before
  concluding there is nothing to simplify — a fresh commit with a clean
  working tree should still be reviewable.

## File list and status

`git diff --name-status <source>` returns one line per file:
`<status-code>\t<path>` (or `<status-code>\t<old-path>\t<new-path>` for
renames/copies). Map status codes: `M` → modified, `A` → added, `R*` →
renamed (use the new path), `C*` → copied (use the new path). Deleted files
(`D`) have nothing to simplify — drop them from scope.

## Line ranges per file

For every non-added file, run:

```
git diff --unified=0 --no-ext-diff <source> -- <path>
```

Parse each hunk header of the form `@@ -<old-start>,<old-count>
+<new-start>,<new-count> @@` (counts are omitted when they equal 1). The
range in scope is `[new-start, new-start + new-count - 1]` — these are line
numbers in the *current* file contents, not the old ones. A hunk with
`new-count = 0` is a pure deletion in the current file; it has no current
lines to simplify, so skip it.

Merge adjacent or overlapping ranges (where the next range's start is within
1 of the previous range's end) into a single range, in hunk order. This
keeps the scope description compact and avoids ambiguous gaps of a single
unchanged line.

For added files (`status: added`), skip hunk parsing entirely — the whole
file is in scope.

## What "in scope" means for editing

- A line range is inclusive on both ends and refers to current file content
  — the file as it exists right now, before this pass's edits.
- Reading outside the range is fine and often necessary for context;
  editing outside the range is not, regardless of how minor.
- If a file has changed lines but merging degenerates it to zero ranges
  (e.g. only whitespace-only hunks that produce an empty diff under
  `--unified=0`), treat it as nothing-to-simplify and skip it rather than
  guessing.
