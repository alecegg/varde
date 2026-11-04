---
topic: varde-explorer/queries
version: 1
summary: Pick the right query and handle a missing index
---

1. Set the repository root and pass `repoRoot` in indexed queries.
2. Run `varde map nav_map` for unfamiliar repositories; use `varde map context_pack` for feature-oriented exploration.
3. Choose `get_symbol` for a known declaration, `context_pack` for a topic, `dependencies`/`dependents` for relationships; `tests_for_file` and `blast_radius` for tests and impact, `find_pattern` for call sites (needs no index), and `nav_map` for broad orientation.
4. Read the smallest relevant source set after locating symbols.
5. On `index_missing` or `index_stale`, use `docs/repo-map/` packs, `find_pattern`, and manual source search; report degraded index capability.
6. Check mode `--help` for JSON inputs when needed.
