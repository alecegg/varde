## Phase 1: Discover all documents

List all target files: `README.md` plus every `docs/*.md` in the repository root.

Classify each file:

- **Marked**: has a leading `<!-- docs:v1 ... -->` marker.
- **Unmarked**: no marker, so every section is stale.

For each marked doc, resolve each marker value against the matching local
generated spec's `source_hash` to find which declared sections are stale or
missing. `references/refresh-marker-format.md` defines what resolves stale.

Use local spec provenance for this decision. A `source_hash` is a content hash,
not a git revision. Read the matching spec and its declared sources when a stale
section needs regeneration.
