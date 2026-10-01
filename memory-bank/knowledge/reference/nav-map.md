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
data-gathering path). `--with-project-knowledge` prepends a pointer to the
project's `memory-bank/knowledge/` bundle when present; it reads no document
contents. The same mode is reachable via `code_query(mode:
"nav_map", ...)`.

## Output sections

`data` is one JSON object with exactly these 7 keys:

- **`entrypoints`** — semantic entrypoints: functions/classes role-tagged
  (`route_handler`, `page_component`, `cli_command`, `background_job`,
  `event_listener`, `middleware`) via decorator/base-class/path-glob
  matching. Process mains in compiled languages are included; Node `main()`
  is included when its source contains a recognized direct-run guard and the
  query has `repoRoot`. Node `handleRequest` functions called by a
  `createServer` callback are also included. SvelteKit `+page.svelte` and
  `+layout.svelte` files are path-only entries; named, exported HTTP methods
  in `+server` modules are entity-backed route roots. Path-only entries have
  no `entity_id` and do not contribute symbols or flows.
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

## Text rendering and toz capture

For successful map data, `--format text` emits the compact repository
orientation: up to five entrypoints, up to four shallow flow summaries, and
commands for retrieving an expanded map or focused context, dependency graph,
and hotspot data. Text mode also hands a rendering without the
`maxTokensEstimate` token budget (still under each section's hard cap, e.g.
`HOTSPOTS_SECTION_LIMIT`) to `toz capture`
(source `varde-code nav_map <repoRoot>`, label `nav_map`) if a `toz` binary is
on `PATH`. A successful capture appends the Toz handle and commands to search
or read the expanded map; Toz's TOC preview does not replace the orientation.
If capture is unavailable, fails, or `VARDE_CODE_TOZ=0`, the orientation is
unchanged. Its counts describe items present in the capped map, with
token-budget omissions called out separately; per-section hard caps still
apply. Query errors retain their raw envelope, and JSON mode is unchanged.

## Non-goals

- Test-coverage-gap detection (no function-level test-coverage-linkage data
  exists).
- Doc-linked concepts / related docs (no knowledge-bundle access from
  varde-code's own query surface).
- Output-size capping or pagination — the JSON output is meant to be
  filtered/queried by the caller, not read whole at once.
