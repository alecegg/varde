---
name: varde-code
description: "Use this skill when you need to find where a symbol is declared, see a file's imports and dependents, get an ordered set of source files to read for a topic, or preview and apply an AST rewrite, using the repository's code index (`varde map`, `varde edit`)."
---

# Query code with varde map

## Index readiness

- Worktrees have no index and no watcher. Orient from the committed packs (`docs/repo-map/README.md`, then a module pack); `varde map packs status --check` reports missing or stale packs.
- Workers use packs, `find_pattern` and `Read`/`rg`; they never build indexes. Hooks never build one.
- On `index_missing` or `index_stale`, only the coordinator may build on demand, from the main checkout and only for packs, repo summaries, or scans: `varde map build --repo-root <main-checkout>`.
- In linked worktrees the gate scan is skipped with a warning; scan on main.
- Coordinator packs are built on main and committed; they never run in setup. Orphaned index folders are removed with `varde map prune`, which dry-runs by default; read the dry run before applying, and deleting is a separate explicit apply.

## Choose a query

- Index search matches paths and names, not text, docs, or semantics; use `rg` for comments, strings, and docs.
- Choose a query by intent and pass an absolute `repoRoot`; `--help` of the mode lists its JSON inputs.
- Known symbol: `get_symbol`; code shapes: `find_pattern` (needs no index); topic-based source set: `context_pack`; imports or impact: relationship queries; broad orientation: `nav_map`.
- `context_pack` test results are import-reachability hints, not measured coverage.
- Omit `maxDepth` for transitive relationships; `maxDepth:1` gives direct edges only.
- AST rewrites: preview with `varde edit preview`, review the diff (a parseable rewrite can still be wrong), then `varde edit apply --proposal <data.proposal_path>`.

## Read results

- Check `ok` and `data.error`; treat `readingOrder` as a candidate sequence.
- Keep output narrow with a specific query and `resultsLimit`.
- `context_pack` caps the whole envelope at `maxTokensEstimate` (default 4000) and each list at `resultsLimit`; cuts drop the lowest-ranked items and set `meta.truncated`.
- For `context_pack`, `meta.toz.handle` captures file rows only; recover missing files from it with `varde run query --handle <H>` before paging. With no capture, page with `resultsOffset` or use `fullResults:true`.

## Fallback

- On a sandbox denial, retry that exact command once with escalation.
- On `index_missing`/`index_stale`, report degraded index access and continue with `find_pattern`, the packs, and source tools.
- Missing `varde`: stop and report it. Do not build or install the CLI.

## Gotchas

- The dependency graph can be partial; verify important edges in source. Empty results do not prove absence.
