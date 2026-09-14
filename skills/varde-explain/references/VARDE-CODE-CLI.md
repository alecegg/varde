# Optional varde-code CLI

`varde-code` is a standalone, pre-alpha Rust CLI installed on PATH as
`varde-code` (CLI-only — no MCP server surface). It's optional: use it when
available and fall back to plain Read/Grep/Glob when it isn't. Check once
per session whether it's installed:

```bash
command -v varde-code >/dev/null 2>&1
```
If `varde-code` is not installed, ignore this file entirely and use the plain
Read/Grep workflow described elsewhere in this skill. Do not build or
install it, and don't treat its absence as an error — it's pre-alpha and
may not exist in a given checkout.

## Build before query

Every query subcommand reads from a persisted index. Run `build` once per
session (not before every query — it does a full rebuild each time):

```bash
varde-code build --repo-root "$(pwd)"
```

## Operations

```bash
# Keyword/feature-area discovery — replaces a manual Grep/Glob sweep when the
# explanation target is a keyword rather than a known path. Matches files,
# directory names, and symbol names, plus their one-hop neighborhood and
# covering tests. Structural only (no doc corpus, no semantic search).
varde-code context_pack --json '{"repoRoot": "'"$(pwd)"'", "query": "authentication"}'

# Call graph from a seed file or symbol — direction is outgoing (default), incoming, or both
varde-code explore --json '{"repoRoot": "'"$(pwd)"'", "query": {"params": {"input": "src/foo.ts", "direction": "both"}}}'

# Symbol body for the explanation being written
varde-code get_symbol --json '{"repoRoot": "'"$(pwd)"'", "name": "myFunction", "includeBody": true}'

# Type/interface relationships (extends/implements)
varde-code type_hierarchy --json '{"repoRoot": "'"$(pwd)"'", "name": "MyClass"}'
```

All commands print a uniform envelope: `{"ok": true, "data": ...}` or
`{"ok": false, "error": {...}}`.

## Fallback rule

If any `varde-code` call fails for any reason (binary missing, build
stale, unexpected error), fall back immediately to reading the relevant
files directly. Don't block on it or try to build/install it yourself.
