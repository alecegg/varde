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

Use it for unknown scope, dependencies, tests, hotspots, and blast radius;
`get_symbol` for one symbol in a large file; `batch` related lookups.

## Review scoping

Set `ROOT=$(git rev-parse --show-toplevel)` once.

```bash
# Every review: tests and dependents of each changed file, in one call
varde-code batch --json '{"repoRoot":"'"$ROOT"'","calls":[
  {"mode":"tests_for_file","filePath":"src/foo.ts"},
  {"mode":"dependents","filePath":"src/foo.ts"}]}'
```

Also useful, same `--json '{"repoRoot":"'"$ROOT"'", ...}'` shape: `nav_map` for
an unfamiliar area or multi-module diff; `hotspots` and `scan` for a
whole-repo review only.

## Diff-scoped lookups

For a simplify pass, scope to what actually changed rather than the whole tree.

```bash
# Symbols changed vs HEAD, staged included (diffMode: working_tree | staged | range)
varde-code detect_changes   --json '{"repoRoot": "'"$ROOT"'", "diffMode": "range", "range": "HEAD"}'
# detect_changes omits untracked files
git ls-files --others --exclude-standard
# Who uses a changed file: its symbols keep their signatures when this is nonempty
varde-code dependents       --json '{"repoRoot": "'"$ROOT"'", "filePath": "src/foo.ts"}'
# Existing helpers matching a new symbol's key terms, with their neighbors
varde-code context_pack     --json '{"repoRoot": "'"$ROOT"'", "query": "retry backoff"}'
varde-code symbols_in_files --json '{"repoRoot": "'"$ROOT"'", "filePaths": ["src/foo.ts"], "includeBody": true}'
```

## Fallback rule

If watcher setup is denied by the sandbox, the main agent retries once
with escalated access. On `index_missing` or `index_stale`, or if setup fails,
use Read/Grep for that call and report degraded index capability. Do not build
from a read-only Explore agent. Grep-check implausible results (e.g. zero
dependents).
