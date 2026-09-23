---
type: spec
status: active
title: "nav_map: session-start repo orientation map"
related:
  - "definition/semantic-entrypoint"
  - "definition/role-tag"
  - "definition/flow"
  - "definition/collapse-with-backref"
  - "definition/foundational-file"
  - "definition/subsystem"
---

# nav_map: session-start repo orientation map

`nav_map` is a query mode (and matching CLI subcommand) that assembles a
structured orientation snapshot of an already-indexed repo entirely from
the persisted code-intelligence index — no live analysis, no doc/knowledge-
bundle access. It follows the same conventions as every other query mode:
auto-freshening via `freshen_for_mode`, and the uniform
`{"ok":true,"data":...}` / `{"ok":false,"error":{...}}` envelope.

## Invocation

```
varde-code nav_map --json '{"repoRoot":"<repo-root>"}'
varde-code nav_map --json '{"repoRoot":"<repo-root>"}' --format text
```

`--format` accepts `json` (default, the canonical output) or `text` (a
plain-text rendering derived from the same JSON — never a second
data-gathering path). The same mode is reachable via `code_query(mode:
"nav_map", ...)`.

## Output sections

`data` is one JSON object with exactly these 7 keys:

- **`entrypoints`** — semantic entrypoints: functions/classes role-tagged
  (`route_handler`, `page_component`, `cli_command`, `background_job`,
  `event_listener`, `middleware`) via decorator/base-class/path-glob
  matching. Bootstrap/process entrypoints (`main.rs`, `__main__.py`,
  `index.ts`, ...) are excluded.
- **`foundational_files`** — a fan-in leaderboard (file, count, one-line
  `why`), noise-filtered. No edges listed here — edges live in `flows`.
- **`module_layers`** — module-to-module edges (kept only when ≥3 files
  cross the boundary) plus cycle detection over the resulting graph. Cycle
  detection is the only violation signal — there is no declared/enforced
  layer order.
- **`subsystems`** — Louvain-clustered file groups, each named by directory-
  path overlap across members (supermajority prefix) or, when no directory
  dominates, by dominant role tag.
- **`symbols`** — a cross-file symbol fan-in leaderboard, noise-filtered,
  with symbols already listed under `entrypoints` excluded.
- **`flows`** — a full reachable-tree walk from each semantic entrypoint
  through the resolved call graph. A node reachable from more than one
  entrypoint is fully expanded once and rendered as a collapse-with-backref
  node (referenced by file path + symbol id) everywhere else — no depth/size
  cap, no separate "shared utilities" tier.
- **`hotspots`** — the existing churn×complexity `hotspots` output,
  noise-filtered.

Generated/vendored paths (`target/`, `node_modules/`, `dist/`, `build/`) are
excluded from every section via one shared filter
(`query::noise_filter::is_generated_or_vendored_path`).

## Non-goals

- Test-coverage-gap detection (no function-level test-coverage-linkage data
  exists).
- Doc-linked concepts / related docs (no knowledge-bundle access from
  varde-code's own query surface).
- Output-size capping or pagination — the JSON output is meant to be
  filtered/queried by the caller, not read whole at once.
