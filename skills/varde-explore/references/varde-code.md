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

## Operations

```bash
# Orient in an unfamiliar repository — start here
varde-code nav_map --json '{"repoRoot": "'"$(pwd)"'"}' --format text

# Gather the files, symbols, and covering tests around a concept or keyword
varde-code context_pack --json '{"repoRoot": "'"$(pwd)"'", "query": "authentication"}'

# Call graph from a seed file or symbol — direction outgoing, incoming, or both
varde-code explore --json '{"repoRoot": "'"$(pwd)"'", "query": {"params": {"input": "src/foo.ts", "direction": "both"}}}'

# Transitive dependents of a file — scope a change's potential downstream impact
varde-code blast_radius --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Files that depend on a given file
varde-code dependents --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Test files covering a given file
varde-code tests_for_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# One symbol's body, for writing an explanation
varde-code get_symbol --json '{"repoRoot": "'"$(pwd)"'", "name": "myFunction", "includeBody": true}'

# Batch related lookups sharing one repository root
varde-code batch --json '{"repoRoot": "'"$(pwd)"'", "calls": [{"mode": "nav_map"}, {"mode": "dependents", "filePath": "src/foo.ts"}]}'
```

Pass `includeBody` only when bodies are needed.

## Fallback rule

If watcher setup is denied by the sandbox, the main agent retries once
with escalated access. On `index_missing` or `index_stale`, or if setup fails,
use Read/Grep for that call and report degraded index capability. Do not build
from a read-only Explore agent. Grep-check implausible results (e.g. zero
dependents).
