---
name: varde-code
description: "Find where a symbol is declared, a file's imports and dependents, or an ordered set of source files to read for a topic, with varde-code. Not for explanations (`varde-explore`), code changes (`varde-change`), reviews (`varde-review`), or CLI installation (`varde-manage`)."
---

# Query code with varde-code

## Index readiness

- Query first; every index query reports `index_missing` or `index_stale` itself.
- On either error, the coordinator starts the watcher once, then retries the query:

```sh
varde-code watch --ensure --repo <absolute-root>
```

- Workers never start watchers or build indexes; on either error they use the Fallback.

## Choose a query

- Index search matches paths/names, not text/docs/semantics; use `rg` for comments, strings, and docs.
- Send JSON with absolute `repoRoot` and mode fields; verify optional fields with `<mode> --help`.

- Known symbol: `get_symbol` with `name`; add `filePath` to disambiguate and `includeBody:true` only when needed.
- Usages and other code shapes: `find_pattern` with `language` and a `pattern`; omitting `path` searches all of `repoRoot`, and it needs no index. Call patterns:
  - Functions: `<name>($$$ARGS)`
  - Methods: `$RECV.<name>($$$ARGS)`
  - Qualified calls (`a::b(...)`): the full path
- Topic set: `context_pack` `query` adds one graph hop; files stay ranked. Its `tests` are import-reachability hints, not measured coverage; `includeReadingOrder:false` omits the duplicate sequence.
- For declaration/body tracing, set `includeTests:false` when test hints aren't needed; keep it enabled for test work.
- By default, `context_pack` returns Function/Class/Interface/Variable/Export/Route declarations with persisted 1-based spans. Set `includeOccurrences:true` to add matching occurrence/control rows.
- Relationships: `dependencies` returns files reachable through imports; `dependents` returns files that reach `filePath`. Omit `maxDepth` for transitive results; set `maxDepth:1` for direct edges.
- Broad orientation: use `nav_map`; skip it for known lookups.

## Read results

- Check `ok` and `data.error`; treat `readingOrder` as a candidate sequence.
- Keep output narrow with a specific query and `resultsLimit`.
- For `context_pack`, `meta.toz.handle` captures file rows only. Recover
  missing files there before paging; query again with `includeOccurrences:true`
  only when matching occurrence rows are needed:

```sh
varde-toz query --handle <H>
```

- If no capture is available or it lacks needed sections, page with `resultsOffset` or use `fullResults:true`; it bypasses token and result caps and honors the offset, but does not change symbol-kind filtering.
- `context_pack` defaults to `maxTokensEstimate:4000`, estimated as serialized bytes/4 (not a tokenizer or global context cap). The estimate also bounds symbols per file; pagination metadata reports omitted symbols.

## Fallback

- On a sandbox denial, retry that exact command once with escalation.
- On `index_missing`/`index_stale` or a failed `watch --ensure`, `find_pattern` still works; use `Read`/`Grep`/`Glob`/`rg` for other lookups and report degraded index access.
- If the CLI is unavailable, use `Read`/`Grep`/`Glob`/`rg` and report degraded access. Never build or install the CLI.

## Gotchas

- The dependency graph can be partial; verify important edges in source. Empty results do not prove absence.
