# Find domains needing updates

Classify each domain as **missing** (no document), **stale** (provenance or
coverage mismatch), or **up to date** (skip, unless the user asked to
force-regenerate). Recompute hashes and the file inventory per
`references/spec-format.md`; legacy specs without `source_roots` or
`covered_paths` are stale.

## Incremental, with a `source_commit`

Recompute every document's provenance and covered paths; a mismatch is stale.
For missing domains, collect the union of `git diff --name-only <source_commit>..HEAD`,
`git diff --cached --name-only`, `git diff --name-only`, and untracked files.
Deduplicate paths before classifying them. Compare changed files with
`source_roots`, not `sources`: a file outside every domain boundary is a
candidate missing domain. Diff from `source_commit`, never
`source_hash`; an unresolvable watermark means a Full scan.

## Full scan

Without `source_commit`, diff the directory and module structure against the
domains in `index.md` and recompute every document's provenance and covered
paths. With no
`index.md` (first run): one domain per workspace member/package, else one per
top-level source directory with its own entry point; state the list.

## Architecture

Identify architecture sources (see `references/spec.md` step 3), including
new declaration files outside old roots, and recompute provenance and covered
paths the same way. Refresh architecture only when it is missing, stale, its
declaration set changed, or a domain was added or removed. A full scan alone
does not require rewriting an up-to-date architecture document.

List current source candidates (from workspace members, source directories,
entrypoints, and deployment declarations) outside all domain `source_roots`,
and candidates covered by more than one domain root. Report both sets for
domain classification,
including on scoped runs. Architecture may intentionally overlap domains;
report that overlap without automatically changing a domain boundary.

## Plan

Return, as reasoning rather than a file:

- `dirty` — missing or stale domains, each with a note on what changed.
- `upToDate` — count.
- `toDelete` — confirmed orphans whose code no longer exists.
- `architectureDirty` — whether the architecture document is missing, stale,
  or needs refreshing because a domain was added or removed.
- `overlapping` and `unmatched` — source paths needing classification.
- `ambiguous` — possible orphans you cannot confirm (the code may have moved);
  leave them in place.

An empty `dirty` list skips domain regeneration; it does not stop the run.
Continue through architecture refresh when `architectureDirty`, confirmed
orphan deletion when `toDelete` is nonempty, and index writing on every run.
