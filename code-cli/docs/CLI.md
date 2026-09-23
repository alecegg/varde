# CLI

The `varde-code` binary is a library plus a single CLI: one subcommand per query
mode, plus `extract`, `build`, `scan`, `test`, the `rules_*` and `hooks`
management commands, `slice_state`, and `watch`.
Global flag: `-v`/`--verbose` (only applies when `RUST_LOG` is unset).

## Conventions

Every machine-readable command prints one JSON envelope to stdout. Query modes
take a single `--json '<object>'` argument; commands with flat flags still use
the same output envelope:

```json
{"schema_version": 1, "ok": true, "outcome": "success", "data": {"...": "payload"}, "meta": {"compact": true, "truncated": false}}
{"schema_version": 1, "ok": false, "outcome": "tool-error", "data": {"error": {"code": "not_found", "message": "not found: ..."}}, "meta": {"compact": false, "truncated": false}}
```

`schema_version` is currently `1`. `ok` reports execution only.
`outcome` reports `success`, `passed`, `code-quality-error`,
`analysis-incomplete`, or `tool-error`. Payloads always use `data`.
Failures use `data.error.code` and `data.error.message`.
`meta.compact` reports the active compacting policy.
`meta.truncated` reports declared omissions. Query errors remain
process-successful, so callers inspect `ok`. CI gates can return nonzero after
printing their envelope. See
[`machine-output-contract.md`](../memory-bank/knowledge/reference/machine-output-contract.md)
for the full contract.

The JSON object always accepts `repoRoot` or `dbPath` to locate the index,
plus mode-specific fields (documented per command below).

Two output-shaping fields are accepted by every query mode and by `scan`:

- **`absolutePaths?`** (default `false`) — file paths in the output are emitted
  repo-relative (the absolute `repoRoot` prefix is stripped) so the prefix
  isn't re-stated on every path. Set `true` to keep absolute paths. Relative
  paths round-trip: a relative `filePath` fed back into another mode still
  resolves (paths are matched by suffix). No effect on `dbPath`-only calls
  (no `repoRoot` to strip) or on paths outside the repo.
- **`includeSpanDetail?`** (default `false`) — a `span` carries only
  `start_line`/`end_line` by default; set `true` to also include the
  `start_byte`/`end_byte`/`start_col`/`end_col` fields.

`scan` also accepts **`fullFindings?`**, **`findingsLimit?`**, and
**`findingsOffset?`**. The default returns at most 100 findings with summary
counts. Set `fullFindings: true` to return every finding. Bounded results set
`meta.truncated: true` and include `data.guide.truncated.findings` with
`shown`, `total`, `offset`, `limit`, `next_offset`, and `request` recovery
fields.

`nav_map` JSON uses the same envelope and compacting rules.
`nav_map --format text` is the deliberate text renderer. Tools should use JSON.

## Build / index

- **`extract PATH`** — Extract entities and symbols from a file or directory
  tree; prints JSON to stdout. Does not touch the database.
- **`build --repo-root ROOT [--force] [--changed-files]`** — Extract, resolve,
  and persist a repo's index. Later runs update changed files incrementally;
  `--force` rebuilds the full index. Writes to
  `~/.config/varde-code/repos/<name>-<hash>/index.db`. Query subcommands read
  from here (or freshen it incrementally on demand). The JSON result reports
  `changedFilesCount` plus a small `changedFilesSample`; pass `--changed-files`
  to include the full `changedFiles` array instead (on a full build that is
  every reparsed path in the repo).

## Query modes

Each takes `--json '<object>'`; fields shown are in addition to
`repoRoot`/`dbPath`.

Large result collections default to 100 records. Continue with
`resultsOffset`, change the window using `resultsLimit`, or request every
record using `fullResults: true`. Pagination details appear in envelope
metadata. Pattern search uses the equivalent `matches*` fields.

| Command | Extra JSON fields | Description |
|---|---|---|
| `batch` | `calls: [{mode, ...}]` | Run several query modes in one call, sharing `repoRoot`/`dbPath` |
| `symbols_in_file` | `filePath`, `includeBody?`, `includeReferences?`, `resultsLimit?`, `resultsOffset?`, `fullResults?` | List symbols declared in a file. Returns declarations + bindings by default; `reference`-kind symbols (call sites/usages, 80–95% of rows) are excluded unless `includeReferences: true` |
| `symbols_in_files` | `filePaths`, `includeBody?`, `includeReferences?`, `resultsLimit?`, `resultsOffset?`, `fullResults?` | Batch form of `symbols_in_file` over many files; maps each path to its symbols or `{error}` |
| `get_symbol` | `name`, `filePath?`, `kind?`, `includeBody?` | Get one symbol by name |
| `dependencies` | `filePath`, `direction?`, `maxDepth?`, `resultsLimit?`, `resultsOffset?`, `fullResults?` | Files a file depends on |
| `dependents` | `filePath`, `maxDepth?`, `resultsLimit?`, `resultsOffset?`, `fullResults?` | Files depending on a file |
| `tests_for_file` | `filePath` | Test files covering a file |
| `hotspots` | `resultsLimit?`, `resultsOffset?`, `fullResults?` | Risk hotspots ranked by complexity × churn (falls back to complexity alone when no file has churn) |
| `clusters` | `minSize?`, `maxClusters?`, `seedPath?` | Community-detection (Louvain) partition of the resolution graph into densely-interconnected file clusters; each `{id, files, label, cohesion}` (`label` always `null`, `cohesion` is the fraction of touching edges kept inside). `seedPath` returns only the cluster containing that file |
| `context_pack` | `query`, `resultsLimit?`, `resultsOffset?`, `fullResults?`, `maxTokensEstimate?`, `includeReadingOrder?` | Keyword-driven context bundle. Files match paths or symbol names; one-hop dependency neighbors follow. Symbols prioritize declarations. `files`, `symbols`, `tests`, and `readingOrder` remain available. Structural only; no doc corpus or semantic search |
| `nav_map` | `maxTokensEstimate?` (plus `--format json\|text`) | Session-start repo orientation map: entrypoints, foundational files, module layers, subsystems, symbols, flows, and hotspots assembled from the persisted index. Trimmed to a total token budget (default 12000, override with `maxTokensEstimate`) spent section-by-section in priority order so it stays fixed-cost regardless of repo size; a `guide.truncated` block reports `{shown, total, more}` per trimmed section and names the follow-up that returns the full data. The `symbols` leaderboard ranks by **caller breadth** (distinct calling files, reported as `callers`) rather than raw call count, and drops low-orientation accessor/stdlib names (`getName`, `push`, `ConfigureAwait`, …). The `flows` section lists only genuine multi-node call trees — single-node trees that merely restate an entrypoint are omitted; each flow summary carries a deduplicated `files` path table and its tree nodes reference paths by `f` index into that table (so a tree of many nodes in a few files pays each path once, not per node). Orientation sections (`foundational_files`, `symbols`, `entrypoints`) exclude front-end asset code (JS/TS/CSS under `assets/`), and `foundational_files` ranks pure data classes (all-accessor/boilerplate methods) below real modules. `entrypoints` covers both annotation-based handlers and call-based routes (Express, Slim, Phoenix, Laravel, Ktor, net/http, …). JSON is canonical; `--format text` renders the same data as plain text |
| `map_file` | `filePath` | Map a file to its persisted node info |
| `map_symbol` | `name`, `sourceFile?` | Map a symbol to its persisted entity |
| `map_path` | `sourceFile`, `targetFile`, `maxDepth?` | Dependency path between two files |
| `explore` | `query: {params: {input, direction?, maxItems?}}` | Explore the dependency graph from a seed; `input` resolves as a file path, falling back to a symbol-name match (exact, then substring) if no file matches; `direction` is `outgoing` (default), `incoming`, or `both` |
| `blast_radius` | `filePath`, `resultsLimit?`, `resultsOffset?`, `fullResults?` | All files transitively reachable from a file |
| `symbol_blast_radius` | `name`, `kind?`, `resultsLimit?`, `resultsOffset?`, `fullResults?` | All files reachable from a symbol |
| `detect_changes` | `diffMode`, `range?` | Symbols changed between git states |
| `find_imports` | `filePath` | Resolved import edges of a file |
| `type_hierarchy` | `name?`, `filePath?` | Type hierarchy (extends/implements) |
| `filter_symbols` | `kind?`, `tags?`, `language?`, `file?`, `maxSymbols?`, `resultsLimit?`, `resultsOffset?`, `fullResults?`, ... | Filter symbols by kind/tags/language/etc. |
| `find_pattern` | `pattern`, `filePath?` (`file?` alias), `path?`, `language?`, `matchesLimit?`, `matchesOffset?`, `fullMatches?`, `inside?`, `has?`, `precedes?`, `follows?` | Find AST nodes matching a `$VAR`/`$$$VAR` pattern, optionally `$VAR:kind`-constrained and filtered by `{kind}` ancestor/descendant/sibling relations (live parse, no DB). Works on **every** `ast-grep`-linked grammar (not just the twenty-one indexed languages); `language` accepts `ast-grep` aliases (`c++`, `py`, `rb`, …) and is inferred from the extension for a single `filePath`. A directory `path` requires an explicit `language`. |

`context_pack` pages files as one unit. Its symbols and tests match those files.
The default estimate allows 4,000 tokens. Increase `maxTokensEstimate` for
larger windows. `fullResults: true` bypasses that estimate. The estimate uses
serialized characters divided by four, not a model tokenizer.
The token estimate also bounds symbols per file. Pagination metadata reports
the omitted symbol count. Increase the estimate for more symbols.
`readingOrder` mirrors the returned files for compatibility. Set
`includeReadingOrder: false` to return an empty array and save tokens.

## Scan / rules

- **`scan --json '{repoRoot, output?, severityThreshold?, gateRules?, fullFindings?, findingsLimit?, findingsOffset?}' [--apply] [--force]`**
  — Run the repo's rule packs (built-in + user + repo scope) against the
  automatically refreshed index and emit findings. Exits nonzero for incomplete
  analysis or unresolved findings meeting `severityThreshold`, default `error`.
  `data.analysis.status` is `complete` or `incomplete`.
  `data.gate.status` is `pass`, `fail`, or `unknown`. Only `pass` exits zero.
  A blocking finding sets top-level `outcome` to `code-quality-error`.
  An incomplete scan sets `outcome` to `analysis-incomplete` unless a blocking
  finding takes precedence. `data.outcome` mirrors the top-level value, and
  `data.outcome_reasons` preserves both reasons.
  `gateRules` selects unique active rule IDs and is mutually exclusive with
  `severityThreshold`; selected IDs are validated before index work. The
  `dependency-boundary` rule requires nonempty source and target prefixes.
  Explicit gate output includes `rule_ids` and a null `severity_threshold`.
  `ok: true` reports execution only. It does not establish gate success.
  `--apply` writes `rewrite` templates to matched files (default is
  read-only); `--force` allows writing to files with uncommitted git changes
  (otherwise skipped as `skipped-dirty`). Incomplete scans skip rewrites.
  Output includes `{findings, findings_summary, diagnostics, analysis, gate,
  policy, rules}`. The default findings list contains at most 100 entries.
  `fullFindings: true` returns all findings. `findingsLimit` and
  `findingsOffset` support bounded pages. Truncated output exposes recovery
  details under `data.guide.truncated.findings`. Each finding is `{id, rule_id, severity, location, evidence,
  message?, certainty?, agent_instructions?}`, and the `rules` legend maps each
  fired `rule_id` to its `{message, remediation}` once rather than repeating that
  static text on every finding (a finding carries an inline `message` only when
  rule interpolation changed it from the template). `duplicate-code-clone`
  findings are collapsed by verified exact-group identity. The collapsed
  evidence retains the exact-group IDs, members, token count, and configured
  minimums instead of emitting one finding per member.
- **`test --json '{rulesDir?}'`** — Run every rule's `[[test]]` entries through
  the pattern/SQL test runners and report pass/fail. Self-contained: no DB and
  no prior `build` required. `rulesDir` scopes discovery to a single directory
  of rule-pack TOML files (no user/repo merge, no built-ins); absent it,
  discovery mirrors `scan`'s rule loading from the current directory. Exits
  non-zero when any test fails, so it can gate CI.

Gate details are `status`, `severity_threshold`, `blocking_findings`,
`diagnostic_count`, and `blocking_diagnostic_count`. The first counts every
normalized diagnostic. The second counts diagnostics that block certification.
Diagnostics add stable `kind`, `source`, `message`, `location`, `severity`, and
`blocking` fields while retaining legacy fields. Explicit `gateRules` also
returns `rule_ids` and nulls the threshold. Expected unsupported or generated
file skips are omitted. Other rule and source diagnostics make the analysis
incomplete. `policy` reports the selected mode, active and gating rule counts,
source counts, and a stable `fnv1a64` fingerprint. Malformed options fail
before source rewrites. Stale suppressions are informational and checked only
in files containing findings.
Successfully applied findings stop blocking; skipped rewrites remain unresolved.
All 21 extraction languages have tested complexity profiles.
The syntax pack covers 35 declared rule-language pairs.
The six informational rules are `vertical-slice-sprawl`,
`churn-complexity-hotspot`, `function-complexity-advisory`, `solid-lsp`,
`solid-isp`, and `console-log-strict`; selecting `info` includes them.
Certified dependency facts cover relative JS/TS/TSX/Dart/Solidity paths and Go
module package units. Cycle detection reports direct reciprocal pairs only.
See [built-in coverage](../BUILT_IN_RULES.md) for thresholds and exceptions.

## Rules management

Materialize or undo the built-in rule packs as editable TOML so they can be
customized directly (instead of only overridden by id). All three take
`--json '{repoRoot}'` and never require a DB.

- **`rules_list --json '{repoRoot}'`** — List the rules that would run for a
  repo, with active definitions and override provenance. Includes patterns, SQL,
  thresholds, constraints, language scopes, exclusions, and remediation. Never scans.
- **`rules_seed --json '{repoRoot}' [--user] [--force]`** — Copy the built-in
  rule packs into the repo's `.varde-code/rules/` (default) or, with `--user`,
  `~/.config/varde-code/rules/`. Existing files are left untouched unless
  `--force`.
- **`rules_remove --json '{repoRoot}' [--user] [--force]`** — Undo a
  `rules_seed`: delete previously seeded built-in files from the repo (default)
  or user (`--user`) rules dir. Only files matching a shipped built-in are
  removed; custom rule files are left alone. A seeded file edited since seeding
  is skipped unless `--force` (which discards those local edits).

## Hooks

Install or remove session-start hooks for supported agent harnesses (`claude`,
`codex`, `opencode`, `pi`) that shell out to `nav_map` at session start. Same
These commands use flat flags instead of `--json`.

- **`hooks list`** — List the 4 supported agent hook targets and the
  directory/file each installs to. No filesystem writes.
- **`hooks install [--agent A...] [--force] [--dir DIR]`** — Install
  session-start hooks for the given agents (default: all 4). `--agent` is
  repeatable (`--agent claude --agent codex`) or comma-separated
  (`--agent claude,codex`). Existing entries are left untouched unless
  `--force`. `--dir` overrides the install target (primarily for testing);
  without it each agent resolves its real per-OS default (`~/.claude/`,
  `~/.codex/`, `~/.config/opencode/`, `~/.pi/agent/extensions/`).
- **`hooks remove [--agent A...] [--force] [--dir DIR]`** — Undo
  `hooks install`. Whole-file targets (opencode, pi) are deleted; merge targets
  (claude, codex) have only this tool's injected entry removed, never the rest
  of the shared config. A target edited since install is skipped unless
  `--force`.

## Diagnostics

- **`slice_state --json '{repoRoot}'`** — Dump the slice freshness ledger for a
  repo: what each derived slice was last built through and whether it's stale.
  Read-only, never builds or freshens.

## Background watcher

- **`watch [--repo REPO...] [--config PATH] [--debounce-ms N]`** — Long-lived
  foreground process that proactively keeps one or more repos' indexes warm by
  reacting to filesystem events (debounced, default 750ms) and running the
  same incremental `ensure_fresh` path queries use on demand. Purely a latency
  optimization: every query still self-verifies freshness independently, so a
  dead or lagging watcher never produces a stale answer, only a slower one.
  Backgrounding the process itself (launchd/systemd/nohup) is the caller's
  job. `--config` points at a `watch.toml` (defaults to
  `~/.config/varde-code/watch.toml` if present and no `--repo` given) that can
  list `repos`/`parent_dirs`; explicit `--repo` flags combine with it.
- **`watch --list`** — List every running (or stale-locked) watcher instance
  as JSON and exit.
- **`watch --stop [--repo REPO...] [--config PATH]`** — Stop the watcher for
  the repo set given via `--repo`/`--config` (SIGTERM if live; always clears
  its lock) and exit.
- **`watch --stop-all`** — Stop every running watcher instance and exit.
