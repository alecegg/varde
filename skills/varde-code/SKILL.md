---
name: varde-code
description: "Find where a symbol is declared, a file's imports and dependents, or an ordered set of source files to read for a topic, with varde-code. Not for explanations (`varde-explore`), code changes (`varde-change`), reviews (`varde-review`), or CLI installation (`varde-manage`)."
---

# Query code with varde map

## Index readiness

- Query first; every index query reports `index_missing` or `index_stale` itself.
- On either error, the coordinator starts the watcher once, then retries the query:

```sh
varde setup watch --ensure --repo <absolute-root>
```

- Workers never start watchers or build indexes; on either error they use the Fallback.
- In a linked worktree with no index, an indexed query reads the main checkout's index read-only and reports `meta.base_index`; answers may not reflect files this worktree changed.
- Coordinator cleanup: `varde map prune --json '{}'` dry-runs; `"apply": true` deletes orphaned index folders, and `unknownOlderThanDays` also removes unrecorded folders past that age.

## Choose a query

Index search matches paths/names, not text/docs/semantics; use `rg` for comments, strings, and docs.
Choose a query by intent; pass an absolute `repoRoot`; consult its mode's `--help` for JSON inputs:

- Known symbol: `get_symbol`; code shapes: `find_pattern`; topic-based source set: `context_pack`.
- Imports or impact: relationship queries; broad orientation: `nav_map`.
- Calls: `<name>($$$ARGS)`; methods `$RECV.<name>($$$ARGS)`; qualified calls need the full path.
- `find_pattern` needs no index. `context_pack` test results are import-reachability hints, not measured coverage. Omit `maxDepth` for transitive relationships; use `maxDepth:1` for direct edges.

### AST rewrites

Preview from one rules file or one inline rule, then apply its proposal:

```sh
varde edit preview --rules rules.json --path src/ --json
varde edit preview --language typescript --pattern 'oldCall($ARG)' --replacement 'newCall($ARG)' --path src/ --json
varde edit apply --proposal <data.proposal_path> --json
```

Use `varde edit preview --help` and `varde edit apply --help` for proposal fields and command inputs. Preview before applying, then review the diff because a parseable rewrite can still be wrong.

## Read results

- Check `ok` and `data.error`; treat `readingOrder` as a candidate sequence.
- Keep output narrow with a specific query and `resultsLimit`.
- For `context_pack`, `meta.toz.handle` captures file rows only. Recover
  missing files there before paging; query again with `includeOccurrences:true`
  only when matching occurrence rows are needed:

```sh
varde run query --handle <H>
```

- If no capture is available or it lacks needed sections, page with `resultsOffset` or use `fullResults:true`; see `context_pack --help` for paging options and the token estimate's meaning.

## Fallback

- On a sandbox denial, retry that exact command once with escalation.
- On `index_missing`/`index_stale` or a failed `watch --ensure`, `find_pattern` still works; use `Read`/`Grep`/`Glob`/`rg` for other lookups and report degraded index access.
- Missing `varde`: stop and report it. Do not build or install the CLI.

## Gotchas

- The dependency graph can be partial; verify important edges in source. Empty results do not prove absence.
