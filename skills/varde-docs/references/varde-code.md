# Optional `varde-code` CLI

`varde-code` is an optional Rust CLI on PATH. If
`command -v varde-code` finds nothing, use Read/Grep/Glob. Its absence is not
an error. Never build or install it yourself. When it is installed, the main agent runs `varde-code watch --ensure --repo
<absolute-repo-root>` and checks `watch --list` for `registered`, `alive`,
and `ready` before dispatching indexed queries. The watcher writes the index;
queries only validate and read it. If supervision or readiness fails, search
source directly and report degraded index capability. An Explore agent in a
read-only sandbox uses indexed queries only after the parent confirms coverage.

Every command prints JSON: branch on `ok`; a failure carries `data.error`.
When a truncated result includes `meta.toz.handle`, query that handle with
`toz query --handle <H> "<term>"` or its `toz_read` line range instead of
requesting repeated offset pages. The inline list remains bounded.
For `find_pattern`, the handle stores locations and 160-character previews.
Use `matchesOffset` or `fullMatches` when you need full match text or captures.

## When to use it

Use it for unknown scope, dependencies, changed symbols, and tests;
`get_symbol` for one symbol in a large file; `batch` related lookups.

## Content and tests

```bash
# One exact symbol's source text in a large file
varde-code get_symbol     --json '{"repoRoot": "'"$(pwd)"'", "name": "createUser", "includeBody": true}'
# Several lookups in one call
varde-code batch          --json '{"repoRoot": "'"$(pwd)"'", "calls": [...]}'
# Covering tests for an Acceptance Criteria "Verified by" note
varde-code tests_for_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
```

## Fallback rule

If watcher setup is denied by the sandbox, the main agent retries once
with escalated access. On `index_missing` or `index_stale`, or if setup fails,
use Read/Grep for that call and report degraded index capability. Do not build
from a read-only Explore agent. Grep-check implausible results (e.g. zero
dependents).
