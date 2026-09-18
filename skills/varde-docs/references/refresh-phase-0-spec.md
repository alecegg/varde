## Phase 0: Refresh specifications first

If the repository maintains generated specification documents (for example under
`memory-bank/knowledge/specs/`), check whether they are current before touching
any user-facing docs:

1. Read each spec's local source record. A current generated spec has a
   `source_hash` and `sources` list in its frontmatter; compare that provenance
   with the listed source files, resolving staleness per
   `references/refresh-marker-format.md`. Use `varde-code` when available
   (`references/varde-code.md`) to inspect the listed source files; otherwise
   read them directly.
2. For any spec that is stale or missing content, regenerate it directly —
   read the relevant source primarily via CLI symbol queries when
   available (or inspect subsystems directly, delegating only when fresh context
   is genuinely useful) and
   rewrite the spec Markdown by hand. Every regenerated spec must follow
   `references/spec-format.md`: record every source file read in
   `sources` with its `git hash-object` hash, then write the deterministic
   aggregate `source_hash`.

If the repository has no such spec documents, skip this phase and continue to
Phase 1.
