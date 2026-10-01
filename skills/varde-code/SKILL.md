---
name: varde-code
description: "Find declarations, code relationships, or source reading sets with varde-code. Not for explanations (`varde-explore`), code changes (`varde-change`), reviews (`varde-review`), or CLI installation (`varde-manage`)."
---

# Query code with varde-code

## Index readiness

- The coordinator reuses this checkout's watcher only when the varde-code CLI's `watch --list` shows it registered, alive, and ready; otherwise start it once and confirm:

```sh
varde-code watch --ensure --repo <absolute-root>
```

- Workers query only after the parent confirms checkout coverage; they never start watchers or build indexes.

## Choose a query

- Index search matches paths/names, not text/docs/semantics; use `rg` for source text and docs.
- Send JSON with absolute `repoRoot` and mode fields; verify optional fields with `<mode> --help`.

- Known symbol: `get_symbol` with `name`; add `filePath` to disambiguate and `includeBody:true` only when needed.
- Topic set: `context_pack` `query` matches paths/names and adds one graph hop. Its `tests` are import-reachability hints, not measured coverage; set `includeReadingOrder:false` to omit the duplicate sequence.
- Relationships: `dependencies` returns files reachable through imports; `dependents` returns files that reach `filePath`. Omit `maxDepth` for transitive results; set `maxDepth:1` for direct edges.
- Broad orientation: use `nav_map`; skip it for known lookups.

## Read results

- Check `ok` and `data.error`; treat `readingOrder` as a candidate sequence.
- Keep output narrow with a specific query and `resultsLimit`.
- If truncated output has `meta.toz.handle`, inspect its capture first:

```sh
varde-toz query --handle <H>
```

- If no capture is available or it lacks needed sections, page with `resultsOffset` or use `fullResults:true`; it bypasses result caps but honors the offset.
- `context_pack` defaults to `maxTokensEstimate:4000`, estimated as serialized bytes/4. This is not an actual tokenizer or global context cap; `fullResults` skips the estimate trim.

## Fallback

- On watcher setup sandbox denial, retry that exact command once with escalation.
- If the CLI/index cannot serve a query (including failed readiness or `index_missing`/`index_stale`), use `Read`/`Grep`/`Glob`/`rg` and report degraded access. Never build or install the CLI.

## Gotchas

- The dependency graph can be partial; verify important edges in source. Empty results do not prove absence.
