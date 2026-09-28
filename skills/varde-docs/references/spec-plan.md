# Find domains needing updates

Classify each domain as **missing** (no document), **stale** (provenance or
coverage mismatch), or **up to date** (skip, unless the user asked to
force-regenerate). Legacy specs without `source_roots` or `covered_paths` are
stale.

Run `varde-workflow spec inventory --repository <repo-root> --knowledge
<knowledge> --working <working> --json` when available. Use its verified
per-domain statuses and `unclassified_paths`/overlapping inventory; the command
invalidates changed staged, unstaged, untracked, and committed inputs and
periodically performs a full validation. Reuse up-to-date domains only on a
successful result. If the command is unavailable or fails, recompute every
document through the manual procedure below and report that the cache was
unavailable. Regenerated
documents still require direct source reading and verification in
`references/spec.md`.
`unclassified_paths` lists changed outside-root paths on warm runs and all
outside-root paths on full runs; inspect those reported paths before classifying
them.

## Manual fallback: incremental, with a `source_commit`

Recompute every document's provenance and covered paths; a mismatch is stale.
For missing domains, collect the union of `git diff --name-only <source_commit>..HEAD`,
`git diff --cached --name-only`, `git diff --name-only`, and untracked files.
Deduplicate paths before classifying them. Compare changed files with
`source_roots`, not `sources`: a file outside every domain boundary is a
candidate missing domain. Diff from `source_commit`, never
`source_hash`; an unresolvable watermark means a Full scan.

## Manual fallback: full scan

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
Inspect `architecture_candidates` before treating `architecture_status: none`
as no architecture source. A candidate can be a deployment or workspace
declaration even if the inventory cannot identify it by filename.
For `architecture_status: inspect`, read `architecture_inspect_paths` directly.
If a path affects deployed units or wiring, refresh architecture. Otherwise,
acknowledge each inspected unrelated path with `varde-workflow spec inventory
--repository <repo-root> --knowledge <knowledge> --working <working>
--acknowledge-architecture-path <path> --json` (repeat the flag for multiple paths).
An acknowledgment binds the current content hash and expires when it changes.
Do not acknowledge a path without reading and classifying it.

List current source candidates (from workspace members, source directories,
entrypoints, and deployment declarations) outside all domain `source_roots`,
and candidates covered by more than one domain root. Report both sets for
domain classification,
including on scoped runs. Architecture may intentionally overlap domains;
report that overlap without automatically changing a domain boundary.
Inspect each reported `unclassified_paths` entry before deciding whether it is a new
domain source, an architecture declaration, or unrelated. Do not infer that an
unrecognized extension means the path is unrelated.

## Plan

Return, as reasoning rather than a file:

- `dirty` — missing or stale domains, each with a note on what changed.
- `upToDate` — count.
- `toDelete` — confirmed orphans whose code no longer exists.
- `architectureDirty` — whether the architecture document is missing, stale,
  or needs refreshing because a domain was added or removed. Resolve `inspect`
  paths before deciding.
- `overlapping`, `unmatched`, and `unclassified_paths` — paths needing
  classification.
- `ambiguous` — possible orphans you cannot confirm (the code may have moved);
  leave them in place.

An empty `dirty` list skips domain regeneration; it does not stop the run.
Continue through architecture refresh when `architectureDirty`, confirmed
orphan deletion when `toDelete` is nonempty, and deterministic index rendering.
Write the index only when its rendered bytes differ from the existing file.
