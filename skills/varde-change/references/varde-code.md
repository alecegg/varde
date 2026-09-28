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

Use it for unknown scope, dependencies, tests, and blast radius; `get_symbol`
for one symbol in a large file; `batch` related lookups.

## Commands

Call as `varde-code <cmd> --json '{"repoRoot": "'"$(pwd)"'", ...}'`, adding the
arguments listed. Run `varde-code <cmd> --help` for full input shapes.

Planning — a scoping signal, not a replacement for reading the touched code:

- `nav_map` (add `--format text`) — entrypoints, layers, subsystems, hotspots
  before scoping an unfamiliar area.
- `context_pack` `query` — keyword discovery while growing the plan.
- `dependents` / `dependencies` / `blast_radius` `filePath` — who depends on a
  file the plan changes (`references/plan-fundamentals.md`).
- `symbol_blast_radius` `name`, optional `filePath` / `kind` — downstream
  resolved call/inheritance impact of a unique declaration. Read `analysis`:
  partial coverage or an empty result cannot prove containment; inspect
  consumers directly or use file-level impact when references are unindexed.
- `clusters` — domain-boundary signal for splitting
  (`references/plan-splitting.md`); a starting point, not a verdict.
- `hotspots` — a change on a hotspot file gets a narrower slice.
- `type_hierarchy` `name` — type relationships an interface must honor.

Executing a task — in place of a raw `Read`:

- `symbols_in_file` `filePath` / `symbols_in_files` `filePaths`, with
  `includeBody: true` — survey a task's `modifies` scope.
- `get_symbol` `name`, `filePath`, `includeBody: true` — one symbol's exact
  body, usable directly as the edit's old text.
- `tests_for_file` `filePath` — existing tests before writing a new one.
- `detect_changes` `diffMode: "range"`, `range: "<plan-commit>..HEAD"` —
  symbol-level drift since the plan's authoring commit.
- `batch` `calls: [{"mode": "<cmd>", ...}]` — several lookups in one call.

## Fallback rule

If watcher setup is denied by the sandbox, the main agent retries once
with escalated access. On `index_missing` or `index_stale`, or if setup fails,
use Read/Grep for that call and report degraded index capability. Do not build
from a read-only Explore agent. Grep-check implausible results (e.g. zero
dependents).
