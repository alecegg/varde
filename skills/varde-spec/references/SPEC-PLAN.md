# Plan the dirty domains

Compare existing spec documents in `memory-bank/knowledge/specs/` against the
current code structure. For each domain, determine whether:

- The domain has no existing spec document (**missing** — needs a fresh
  document).
- The code backing an existing domain document has changed since the
  document was last written (**stale** — needs regeneration).
- The domain document still matches the current code (**up to date** — skip
  it, unless a force-regenerate was requested, in which case treat all
  domains as needing work).

## When `varde-code` is available (see `VARDE-CODE-CLI.md`)

Read `source_commit` from `memory-bank/knowledge/specs/index.md`
frontmatter. If present, scope the whole plan to the diff since that commit
instead of scanning the repo:

1. `detect_changes` with `diffMode: "range"`, `range: "<source_commit>..HEAD"`
   — the changed-symbols list is the entire input to dirty-domain detection.
2. For each changed symbol's file, resolve its domain with `map_file` (or
   `clusters` for unmapped/new files) instead of reading directory structure
   by hand.
3. A domain is `dirty` only if a changed symbol's file maps into it. Every
   domain with zero hits is `upToDate` — do not open its files.
4. A file in the diff that maps to no existing domain and doesn't fit an
   existing domain's convention is a candidate **missing** domain; add it as
   `dirty` with a note.

No `source_commit` (first run, or index.md predates this scheme) → fall
through to the full scan below.

## Full scan (no watermark, or `varde-code` unavailable)

Build this by reading directory/module structure, diffing it against the
domains already documented in `memory-bank/knowledge/specs/index.md`, and
skimming source files for the sections that source-cite regenerable content
(scope boundary, key operations, invariants, acceptance criteria, flows).

Produce, as reasoning output (not a generated artifact), a plan consisting
of:

- `dirty`: the list of domains requiring work (missing or stale), with a
  short note on what changed or why the document is missing.
- `upToDate`: count of unchanged domains.
- `toDelete`: domain documents whose corresponding code no longer exists in
  the repository — confirmed orphans.
- `ambiguous`: domain documents you cannot confidently classify as orphaned
  (e.g. the code may have moved rather than been deleted) — leave these in
  place.

Architecture-relevant paths (UI, middleware, domain, and model layers) get
classified by directory convention and import structure. Unmatched paths use
the majority convention already present in the repo when available.

If `dirty` is empty, report unchanged domains and stop — there is nothing to
generate.
