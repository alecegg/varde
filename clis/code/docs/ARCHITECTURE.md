# Architecture

`varde-code` is a library plus a single CLI binary (see [CLI.md](CLI.md)): no
MCP server, no long-running service beyond the supervised `watch` process. It
parses source with tree-sitter, extracts entities/symbols, resolves cross-file
relationships, and persists the result to a local SQLite index that the query
subcommands read back.

## Modules

| Module | Location | Role |
|---|---|---|
| `parse` | `src/parse.rs` | Language detection and full-tree parsing (via `ast-grep-language`); maps file extensions to the twenty-one indexed languages (JS/TS/TSX, Go, C, C++, C#, Java, Swift, Kotlin, Rust, Python, Ruby, PHP, Scala, Dart, Lua, Elixir, Solidity, Haskell, Bash) |
| `extract` | `src/extract/` | Entity/symbol extraction via a single merged tree walk; per-language visitors live under `extract/langs/`, plus `entity.rs`, `symbol.rs`, and `minhash.rs` (clone detection) |
| `model` | `src/model.rs` | In-memory AST types: `ExtractOutput` (entities/symbols/diagnostics per file), `Entity`/`Symbol`, and the handoff structs passed from extraction to resolution to persistence |
| `resolve` | `src/resolve.rs` | Cross-file resolution: import/dependency edges, call graph, type hierarchy; submodules `graph.rs` (edge indexing), `clones.rs` (clone bands), `community.rs` (community detection), `rust_modules.rs` (Rust `mod`/`use` module-path → file resolution) |
| `persist` | `src/persist.rs` | Writes entities, symbols, files, edges, and diagnostics to SQLite as one transaction |
| `db` | `src/db.rs` (+ `db/path.rs`) | SQLite schema DDL and open/rebuild scaffold; submodule `path.rs` resolves the on-disk index path (`~/.config/varde-code/repos/<name>-<hash>/index.db`) |
| `build` | `src/build.rs` | Wires `scan → extract → resolve → persist` for the `build` CLI command; full rebuild or incremental via file metadata (mtime/size/content-hash) |
| `slice` | `src/slice.rs` | Watcher-owned sliced reconciliation (`ensure_fresh`) plus a read-only query freshness preflight (`check_fresh`) |
| `repo_lock` | `src/repo_lock.rs` | Per-repo inter-process advisory lock (kernel `flock`) guarding explicit builds and reconciliation writes |
| `query` | `src/query/` | Read-side API: one function per query mode behind a uniform JSON envelope; submodules `simple.rs`, `graph.rs` (traversals), `mapping.rs` (clusters/context_pack), `find_pattern.rs` (live AST search, DB-free), `nav_map.rs` and its section builders (`entrypoints.rs`, `foundational_files.rs`, `module_layers.rs`, `subsystems.rs`, `symbols_section.rs`, `flows.rs`), and `noise_filter.rs` |
| `scan` (walker) | `src/scan.rs` | Directory walking with skip-and-report semantics; unparseable files become per-file diagnostics instead of hard failures |
| `scan_cli` | `src/scan_cli.rs` | Orchestrates the `scan` command: open DB → staleness check → load TOML rules → run pattern rules against the tree and SQL rules against the DB → merge findings |
| `rules` | `src/rules/` | Rule engine: `pattern.rs` (AST pattern rules), `sql.rs` (SQL rules), `rewrite.rs` (auto-fixes), `finding.rs` (content-addressed findings), `correlate.rs` (dedup), `suppress.rs` (suppression handling), `test_runner.rs` (rule self-test runners) |
| `churn` | `src/churn.rs` | Git touch-frequency analysis feeding hotspot ranking |
| `complexity` | `src/complexity.rs` | Cyclomatic/structural complexity metrics |
| `git` | `src/git.rs` | Git history/status/tree-state integration |
| `watch` | `src/watch.rs` | Background watcher: per-repo `notify::Watcher`, debounced incremental rebuilds, single-instance lock; a latency optimization only — see [CLI.md](CLI.md#background-watcher) |
| `test_cli` | `src/test_cli.rs` | Orchestrates the `test` command: discovers every rule carrying `[[test]]` entries and runs them through the pattern/SQL test runners, merged into the same `{ok, data}` envelope `scan_cli.rs` uses. Self-contained (no DB, no `build`) |
| `hooks` | `src/hooks.rs` | Session-start hook install targets for supported agent harnesses (claude, codex, opencode, pi); shared whole-file-write and merge-into-shared-config scaffold backing the `hooks` subcommands |

## Write path (`build`)

```
scan.rs        walk the tree, emit files (skip-and-report for unparseable ones)
  -> extract/   parse + extract entities/symbols per file (ExtractOutput)
  -> resolve.rs cross-file resolution: edges, call graph, clones, communities
  -> persist.rs write entities/symbols/files/edges/diagnostics to SQLite,
                 one transaction
  -> index.db   ~/.config/varde-code/repos/<name>-<hash>/index.db
```

`build.rs` runs the full pipeline for a missing index or `--force`.
Otherwise it updates changed files incrementally. File metadata drives
change detection, with content hashes used when metadata is unavailable.

### Concurrency & durability

Explicit builds and watcher reconciliation must not corrupt a shared index:

- **Full build** (`run_full`, and `--force`) writes to a sibling `*.db.tmp`
  and `rename`s it over `index.db` only on a clean commit — atomic, so a
  concurrent reader or a crash never sees a partial full build. It runs on a
  `journal_mode=OFF` connection (`db::open`): no rollback journal, chosen so a
  multi-million-row single transaction doesn't hold its journal in RAM.
- **Incremental build** (`run_incremental`) and watcher reconciliation
  (`slice::ensure_fresh`) mutate `index.db` **in place**. Both hold the
  per-repo advisory `flock` (`repo_lock`) for the whole write, so a CLI `build`
  and a concurrent watcher reconcile serialize instead of interleaving partial writes.
  They use `db::open_incremental` (`journal_mode=MEMORY`) so a mid-write error
  rolls back cleanly rather than splicing a half-applied delta into the live
  index; deletes + derived-ledger invalidation commit as one transaction.

The watcher also holds separate kernel `flock` locks for every canonical repo
it covers, acquired in sorted path order, plus one set-level lock for status and
shutdown. This keeps overlapping watcher sets exclusive without holding the
index write lock for the watcher's lifetime. Lock files stay in place; the
kernel releases ownership when each process exits, so a prior process cannot
unlink a replacement's lock marker.

The only residual gap is a *power-loss* crash mid-commit on the in-place path
(the RAM journal is lost); it is recovered by `build --force`, never a manual
repair. `synchronous=OFF` (no per-commit fsync) is retained for write
throughput, making that the deliberate durability trade.

## Read path (query subcommands)

```
query/<mode>.rs   resolve repoRoot plus an optional dbPath override
  -> slice::check_fresh    compare source inventory and required slice revisions
  -> SQLite SELECT         read persisted entities/edges/files/symbols
  -> JSON envelope         {"ok": true, "data": ...} to stdout
```

Indexed modes require `repoRoot`; `dbPath` is an optional override paired with
that root. Each mode declares the slices it reads. A fresh index returns data;
a missing or stale index returns a typed error without locking or changing the
database. `find_pattern` parses live source, while `detect_changes` and
`slice_state` remain diagnostic exceptions. Batch applies the same contract to
each child after inherited input is resolved.

## Watch loop

The main agent runs `watch --ensure --repo ROOT` before dispatching indexed
queries. This registers a user service through launchd or user systemd and
waits until the supervisor job is active, exclusive repo locks are held, and
the initial reconcile has succeeded. The watcher subscribes before
reconciliation, then drives `slice::ensure_fresh` after debounced filesystem
events and periodic repair intervals. `watch --list` verifies the kernel locks,
matching owner generation, per-repo readiness marker, and current index
freshness; a PID or saved service definition alone does not count as coverage.
A missing or stale result sends the agent to manual source search while the
watcher catches up. Stop waits for lock release, and stop-all reports each
instance failure while continuing through the remaining services.

## Scan/rules path

`scan_cli.rs` checks read-only freshness, loads TOML rule packs (built-in
+ user + repo scope), then runs two kinds of rules against two different
substrates: pattern rules (`rules/pattern.rs`) walk the live AST, SQL rules
(`rules/sql.rs`) query the persisted index directly. Findings from both are
merged and deduplicated (`rules/correlate.rs`) before being reported or
(`--apply`) used to drive `rules/rewrite.rs` auto-fixes.
