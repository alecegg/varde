---
type: reference
title: Knowledge discovery maps
description: Concept metadata and deterministic maps expose searchable knowledge without renaming legacy files.
generated: { by: codex, at: 2026-09-19T18:30:00Z }
---

# Knowledge discovery maps

New Concepts need a non-empty `description`. They may include `aliases` as a
sequence of non-empty strings. Aliases remain searchable with full-text search:

```sh
varde-workflow concept search --bundle memory-bank/knowledge \
  --text "an alias" --json
```

Generate navigation maps from the current Knowledge Bundle:

```sh
varde-workflow concept map --bundle memory-bank/knowledge --json
```

Generation writes the reserved root `index.md` and one `index.md` inside each
type directory. Existing root frontmatter remains intact. Legacy Concepts
without descriptions remain readable and appear with a placeholder description.

Map entries include the title, bundle-relative link, description, aliases, and
status. Active entries appear before deprecated entries. Entries are grouped
by type, then sorted by title and slug. Repeating generation produces identical
bytes when Concept content is unchanged.

Maps are discovery surfaces only. They do not replace Concept files, search,
lint, vault layering, or OKF metadata. Existing filenames need no migration.
