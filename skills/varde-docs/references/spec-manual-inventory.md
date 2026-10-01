<!-- kind: reference -->
# Manual spec inventory

Report that the cache was unavailable. Recompute every document's
provenance and covered paths, then find missing domains:

- **With `source_commit` in `index.md`:** a changed file outside every domain's
  `source_roots` (not `sources`) is a candidate missing domain. Changed files
  are the deduplicated union of `git diff --name-only <source_commit>..HEAD`,
  `git diff --cached --name-only`, `git diff --name-only`, and untracked files.
  Never diff from `source_hash`.
- **Full scan** (no or unresolvable `source_commit`): diff the directory and
  module structure against the domains in `index.md`.
- **First run** (no `index.md`): one domain per workspace member/package, else
  one per top-level source directory with its own entry point; state the list.
