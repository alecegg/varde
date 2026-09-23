## Phase 0: Refresh specifications first

When the repository has generated specification documents, such as those under
`<knowledge>/specs/`, verify them before touching user-facing docs:

1. Read each spec's local source record. A current generated spec has a
   `source_hash` and `sources` list in its frontmatter. Compare that provenance
   with the listed source files. Resolve staleness with
   `references/refresh-marker-format.md`. Read short, listed files directly.
   Use `varde-code` for several files, changed symbols, or relationships.
   Use `get_symbol` only for exact symbols inside large files.
2. For each stale or incomplete spec, regenerate it —
   batch related CLI queries when needed (or inspect the subsystem directly;
   delegate only when another
   agent provides needed context) and
   rewrite the spec Markdown by hand. Every regenerated spec must follow
   `references/spec-format.md`: record every source file read in
   `sources` with its `git hash-object` hash, then write the deterministic
   aggregate `source_hash`.

If the repository has no specification documents, skip this phase and continue
to Phase 1.
