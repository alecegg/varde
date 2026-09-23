# varde-code

A native Rust code-intelligence engine: tree-sitter parsing, entity/symbol extraction, and a
SQLite-backed query/scan engine, exposed as a library plus a single `varde-code` CLI binary.

## Scope

- Multi-language parsing (tree-sitter) for JS/TS/TSX, Go, C, C++, C#, Java, Swift, Kotlin, Rust,
  Python, Ruby, PHP, Scala, Dart, Lua, Elixir, Solidity, Haskell, and Bash (Tier B / shell) (`crates/varde-code/src/extract/langs/`). These
  twenty-one are the *extraction/indexing* languages; structural `find_pattern` search additionally covers every
  grammar `ast-grep-language` links (HCL/Terraform, …)
- Entity/symbol extraction, resolution (imports/dependencies/type hierarchy), and complexity/churn
  metrics, persisted to a local SQLite index (`crates/varde-code/src/db`, `persist.rs`)
- A query engine (`query/`) exposed via the `varde-code` CLI (`cli.rs`) for lookups like
  `symbols_in_file`, `get_symbol`, `dependencies`/`dependents`, `hotspots`, `type_hierarchy`,
  `blast_radius`, and dependency-graph maps (`map_file`/`map_symbol`/`map_path`, `explore`)
- A pattern-matching scan/rules engine (`rules/`, `scan.rs`) for structural pattern search
  (`find_pattern`) and rule-based scanning (`scan`, `rules_list`)
- An optional background watcher (`watch`) that keeps a repo's index incrementally fresh
- Explicitly out of scope: no MCP server or long-running daemon beyond the optional watcher —
  this module is a library plus a CLI binary

The scan engine's product direction is a language-agnostic counterpart to
[Fallow](https://github.com/fallow-rs/fallow)'s static analysis workflow.
Varde keeps detectors shared across languages while adapters contribute
normalized imports, exports, references, entrypoints, and framework facts.
Unsupported facts must remain explicit instead of weakening finding precision.
All twenty-one extraction languages have tested complexity profiles.
Unknown constructs and syntax errors lower affected metric confidence.
Only high-confidence metrics block unreadable functions.

Scan refreshes its index automatically before evaluating rules:

```sh
varde-code scan --json '{"repoRoot":".","severityThreshold":"error"}'
varde-code rules_list --json '{"repoRoot":"."}'
```

The built-in pack has 34 rules: 28 errors and six informational advisories.
The default gate includes certified function, file, structural, clone, and
dependency budgets. Choose `warning` or `info` to widen the severity gate.
Use `gateRules` for explicit active rule IDs; it cannot accompany
`severityThreshold`. Syntax rules cover 35 declared rule-language pairs.
The dependency boundary stays inactive until configured.
`rules_list` exposes active definitions, thresholds, and override provenance.
Scan exits nonzero for blocking findings or incomplete analysis.
The envelope uses `schema_version: 1` and a top-level `outcome`.
`ok` reports execution only. Use `outcome` for caller messaging.
For scan results, inspect `data.analysis.status` and `data.gate.status`.
The default finding list is bounded. Pass `fullFindings: true` for all findings.
See [BUILT_IN_RULES.md](BUILT_IN_RULES.md) for coverage and customization.

## Install

Prebuilt binaries (macOS arm64/x86_64, Linux x86_64/arm64) are attached to each
[tagged release](https://github.com/alecegg/varde/releases). Download the tarball for your
platform, extract it, and put `varde-code` on your `PATH`. Each tarball also contains
`THIRD-PARTY-LICENSES.md` — the attribution notices for the statically-linked dependencies.

Or build from source with Cargo (requires Rust 1.88+):

```sh
cargo install --path crates/varde-code
```

## Usage

Query a repo directly. Queries refresh the index automatically:

```sh
varde-code hotspots --json '{"repoRoot": "."}'
varde-code symbols_in_file --json '{"repoRoot": ".", "filePath": "src/main.rs"}'
varde-code context_pack --json '{"repoRoot": ".", "query": "authentication"}'
varde-code build --repo-root . # optional precomputation
```

Every query subcommand takes a single `--json '<object>'` argument and prints
the versioned envelope documented in
[machine-output-contract.md](memory-bank/knowledge/reference/machine-output-contract.md).
The top-level `ok` field reports execution. The top-level `outcome` reports
success, quality failure, incomplete analysis, or tool failure. The index is
stored at `~/.config/varde-code/repos/<name>-<hash>/index.db`.

## Docs

- [docs/CLI.md](docs/CLI.md) — every subcommand, its JSON input, and what it does
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — module map, write/read data flow, watch and scan loops
- [BUILT_IN_RULES.md](BUILT_IN_RULES.md) — scope and schema for the built-in scan rule pack
- [BENCHMARK.md](BENCHMARK.md) — speed/quality tracking against `ast-grep` for overlapping modes
- [CHANGELOG.md](CHANGELOG.md) — notable changes per release

Agent workflows treat this CLI as internal tooling.
Canonical agent guidance lives under `guidance/varde-code/`.
The skills module vendors focused copies for each consumer.

## Status

Beta. Core parsing/extraction/query/scan surfaces are covered by an extensive test suite and
gated by CI.
