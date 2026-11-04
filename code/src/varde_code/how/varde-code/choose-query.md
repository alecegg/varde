---
topic: varde-code/choose-query
version: 1
summary: Pick the query mode for an intent, write call patterns, and set maxDepth
---

- Known symbol: `get_symbol`. Code shapes: `find_pattern`. Topic-based source set: `context_pack`. Imports or impact: relationship queries (`dependencies`, `dependents`). Broad orientation: `nav_map`.
- Calls: `<name>($$$ARGS)`; methods `$RECV.<name>($$$ARGS)`; qualified calls need the full path.
- `find_pattern` needs no index.
- Omit `maxDepth` for transitive relationships; use `maxDepth:1` for direct edges.
- Consult the mode's `--help` for JSON inputs.
