## Phase 1: Discover all documents

Enumerate all target files: `README.md` plus every `docs/*.md` in the repository
root.

Classify each file:

- **Marked**: has a leading `<!-- docs:v1 ... -->` marker.
- **Unmarked**: no marker present — treat as stale.

For each marked doc, determine which declared sections are stale or missing:

- If `varde-code` is available (`references/VARDE-CODE-CLI.md`), diff each
  section's `source_hash` against `HEAD` via `detect_changes`. A section
  with no changed symbols in range is up to date — don't open its doc or
  source. A section with hits is stale.
- Otherwise, compare declared sources against the current code (or specs)
  by reading both.

Unmarked docs are always treated as stale in full (no watermark exists for
them yet).
