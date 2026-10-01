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
[`machine-output-contract.md`](../../../memory-bank/knowledge/reference/machine-output-contract.md)
for the full contract.

On a truncated query, scan, or test result, an available `toz` stores a
JSONL result list and adds `meta.toz` with `handle`, total `items`, `format: "jsonl"`, and
a file-grouped `toc`. The default inline page becomes 20 items; explicit
`resultsLimit`, `matchesLimit`, and `findingsLimit` keep their requested sizes.
For `find_pattern`, each stored row contains the file, kind, span, and first
160 characters of match text (`meta.toz.projection: "match_preview_160"`).
Use `matchesOffset` or `fullMatches` for full text and captures beyond the inline page.
Use `toz query --handle <H> --lines 101:200` to read a one-based inclusive
range or search the handle by term. The next-page command is also in
`data.guide.truncated.<list>.toz_read` or, for array payloads,
`meta.pagination.<list>.toz_read`. Set `VARDE_CODE_TOZ=0` to disable capture.

Indexed query modes and `scan` require `repoRoot`. `dbPath` may override the
index location only when paired with `repoRoot`; the source files and derived
slices are checked against that database. `find_pattern` parses live source.
`detect_changes` and `slice_state` are diagnostic exceptions that may accept
`dbPath` alone. `batch` applies these rules to each child after inheriting its
parent input. Missing and stale indexes return `index_missing` and
`index_stale` error codes in the normal JSON envelope. Queries never update
the index; search source directly while watcher coverage is unavailable.

Two output-shaping fields are accepted by every query mode and by `scan`:

- **`absolutePaths?`** (default `false`) — file paths in the output are emitted
  repo-relative (the absolute `repoRoot` prefix is stripped) so the prefix
  isn't re-stated on every path. Set `true` to keep absolute paths. Relative
  paths round-trip: a relative `filePath` fed back into another mode still
  resolves (paths are matched by suffix). No effect on paths outside the repo.
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
For successful map data, `nav_map --format text` renders a compact Varde-owned
repository orientation with up to five entrypoints, four shallow flows, and
`varde-code` commands for retrieving an expanded map or focused context,
dependency graph, and hotspot data. It also captures a rendering without the
token budget to `toz` when available
(per-section hard caps still apply). A successful capture appends the handle
and `varde-toz query` commands for searching or reading the expanded map. If
Toz is disabled, unavailable, or capture fails, the orientation is unchanged.
Query errors retain their raw envelope. Set `VARDE_CODE_TOZ=0` to disable
capture. Add `--with-project-knowledge` to
prepend a short pointer to the project's durable knowledge bundle, when
present, without loading its contents. Session-start hooks use this option.

## Build / index

- **`extract PATH`** — Extract entities and symbols from a file or directory
  tree; prints JSON to stdout. Does not touch the database.
- **`build --repo-root ROOT [--force] [--changed-files]`** — Extract, resolve,
  and persist a repo's index. Later runs update changed files incrementally;
  `--force` rebuilds the full index. Writes to
  `~/.config/varde-code/repos/<name>-<hash>/index.db`. Query subcommands read
  from here without modifying it. The JSON result reports
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
| `tests_for_file` | `filePath` | Test-path files that transitively import the target through resolved import edges |
| `hotspots` | `resultsLimit?`, `resultsOffset?`, `fullResults?` | Risk hotspots ranked by complexity × churn (falls back to complexity alone when no file has churn) |
| `clusters` | `minSize?`, `maxClusters?`, `seedPath?` | Community-detection (Louvain) partition of the resolution graph into densely-interconnected file clusters; each `{id, files, label, cohesion}` (`label` always `null`, `cohesion` is the fraction of touching edges kept inside). `seedPath` returns only the cluster containing that file |
| `context_pack` | `query`, `resultsLimit?`, `resultsOffset?`, `fullResults?`, `maxTokensEstimate?`, `includeReadingOrder?` | Keyword-driven context bundle. Files match paths or symbol names; one-hop dependency neighbors follow. Symbols prioritize declarations. `files`, `symbols`, `tests`, and `readingOrder` remain available. Structural only; no doc corpus or semantic search |
| `nav_map` | `maxTokensEstimate?` (plus `--format json\|text`) | Session-start repo orientation map: entrypoints, foundational files, module layers, subsystems, symbols, flows, and hotspots assembled from the persisted index. Trimmed to a total token budget (default 12000, override with `maxTokensEstimate`) spent section-by-section in priority order; per-section hard caps also apply. A `guide.truncated` block reports `{shown, total, more}` per trimmed section (after section caps) and names the follow-up query for more data. The fallback's counts describe items present in its capped map, not repository totals. Raise `maxTokensEstimate` for an expanded map, while keeping in mind section caps still apply. The `symbols` leaderboard ranks by **caller breadth** (distinct calling files, reported as `callers`) rather than raw call count, and drops low-orientation accessor/stdlib names (`getName`, `push`, `ConfigureAwait`, …). The `flows` section lists only genuine multi-node call trees — single-node trees that merely restate an entrypoint are omitted; each flow summary carries a deduplicated `files` path table and its tree nodes reference paths by `f` index into that table (so a tree of many nodes in a few files pays each path once, not per node). Orientation sections (`foundational_files`, `symbols`, `entrypoints`) exclude front-end asset code (JS/TS/CSS under `assets/`), and `foundational_files` ranks pure data classes (all-accessor/boilerplate methods) below real modules. `entrypoints` covers annotation-based handlers and call-based routes, Node `main()` functions inside recognized direct-run guards, named `handleRequest` functions called by Node `createServer` callbacks, and SvelteKit page/layout files plus named exported HTTP methods in `+server` modules. Node guard detection reads source through `repoRoot`; dbPath-only queries omit Node roots. Svelte page/layout entries are path-only and do not produce symbol or flow roots. JSON is canonical; `--format text` renders the same data as plain text |
| `map_file` | `filePath` | Map a file to its persisted node info |
| `map_symbol` | `name`, `sourceFile?` | Map a symbol to its persisted entity |
| `map_path` | `sourceFile`, `targetFile`, `maxDepth?` | Dependency path between two files |
| `explore` | `query: {params: {input, direction?, maxItems?}}` | Explore the dependency graph from a seed; `input` resolves as a file path, falling back to a symbol-name match (exact, then substring) if no file matches; `direction` is `outgoing` (default), `incoming`, or `both` |
| `blast_radius` | `filePath`, `resultsLimit?`, `resultsOffset?`, `fullResults?` | Potential downstream impact: transitive dependents through resolved edges, excluding the changed file |
| `symbol_blast_radius` | `name`, `filePath?`, `kind?`, `resultsLimit?`, `resultsOffset?`, `fullResults?` | Downstream files reached through calls and inheritance referencing a unique declaration; includes explicit partial-coverage metadata |
| `detect_changes` | `diffMode`, `range?` | Symbols changed between git states |
| `find_imports` | `filePath` | Resolved import edges of a file |
| `type_hierarchy` | `name?`, `filePath?` | Type hierarchy (extends/implements) |
| `filter_symbols` | `kind?`, `tags?`, `language?`, `file?`, `maxSymbols?`, `resultsLimit?`, `resultsOffset?`, `fullResults?`, ... | Filter symbols by kind/tags/language/etc. |
| `find_pattern` | `pattern`, `filePath?` (`file?` alias), `path?`, `language?`, `matchesLimit?`, `matchesOffset?`, `fullMatches?`, `inside?`, `has?`, `precedes?`, `follows?` | Find AST nodes matching a `$VAR`/`$$$VAR` pattern, optionally `$VAR:kind`-constrained and filtered by `{kind}` ancestor/descendant/sibling relations (live parse, no DB). Works on **every** `ast-grep`-linked grammar (not just the twenty-one indexed languages); `language` accepts `ast-grep` aliases (`c++`, `py`, `rb`, …) and is inferred from the extension for a single `filePath`. A directory `path` requires an explicit `language`. |

`symbol_blast_radius` selects declarations only. `kind` accepts `function`,
`class`, `interface`, `variable`, or `parameter`; `filePath` narrows by full
path or path-component suffix. Multiple matches return `ambiguous_symbol`,
including overloads that remain ambiguous within the same file.

The result retains `declaring_file` and `blast_radius`, and adds `analysis`.
Traversal follows resolved call and inheritance edges between declarations,
not file imports. Calls map to their nearest named callable span; top-level
calls and anonymous callbacks report their file but stop propagation when a
unique named owner cannot be established. The seed declaration is excluded;
its file is included when another affected symbol or unowned call is there.
Export wrappers resolve only to a uniquely matching declaration contained in
the wrapper. Aliases and re-exports without that match remain unresolved.

`analysis.status` is `partial`: arbitrary data references and dynamic dispatch
are not fully indexed. `unresolved_edges` counts unresolved or missing-target
call/inheritance edges across the indexed repository; `unmapped_owners` counts
reached references whose named caller could not be established. An empty
result does not prove isolation. Use file-level impact and source inspection
when those limitations matter to the decision.

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
  current index and emit findings. Checks freshness without writing. Exits nonzero for incomplete
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

These commands describe the current checkout. Check `varde-code watch --help`
for `--ensure` before starting supervised coverage. If the option is missing
or rejected, the installed binary predates this interface; follow the
[README upgrade instructions](../README.md#usage). Use source search until a
compatible binary is available. Removing `--ensure` starts a foreground
watcher; it does not register a persistent user service.

- **`watch --ensure --repo ROOT`** — Register a persistent user service for one
  Git repository through launchd (macOS) or user systemd (Linux), start it
  idempotently, and wait up to 30 seconds for an active supervisor job, exclusive
  repo ownership, and successful initial reconciliation. An unavailable
  supervisor or readiness failure returns `watch_error`; use manual source
  search until coverage is restored.
- **`watch [--repo REPO...] [--config PATH] [--debounce-ms N]`** — Run the
  watcher in the foreground. It subscribes to filesystem events before its
  initial reconciliation, debounces updates (default 750ms), and periodically
  reconciles to repair missed events. A `watch.toml` can list `repos` and
  `parent_dirs`.
- **`watch --list`** — Report registered, alive, and ready states. Readiness
  requires held kernel locks, a matching process generation, completed initial
  reconciliation, and a fresh index; a PID or service file alone is not enough.
- **`watch --stop --repo ROOT`** — Stop and unregister that repo's supervised
  watcher, or stop a matching foreground watcher. It waits for kernel ownership
  to release before returning.
- **`watch --stop-all`** — Try every running watcher. Per-instance failures are
  included in the result array and do not prevent later stops.
