---
type: reference
status: active
title: "varde-code query surface CLI"
related: ["2026-08-12-varde-code-rust-port/query-surface"]
---

# varde-code query surface CLI reference

Contract reference for varde-code's read-side query surface — all 17 query
modes plus the CLI envelope contract. Every mode reads the SQLite store that
the `sqlite-persistence` phase writes; nothing re-derives in-memory
structures. Source of truth: `crates/varde-code/src/query/` (+
`crates/varde-code/src/cli.rs`, `crates/varde-code/src/main.rs`).

## Invocation

```text
varde-code <mode> --json '<input object>'
```

One subcommand per mode, one-shot process per call (not a persistent
stdin/stdout protocol). The `--json` object carries `repoRoot` (or `dbPath`)
plus mode-specific fields:

- `repoRoot` — a repository path; the DB is located at
  `~/.config/varde-code/repos/<name>-<hash>/index.db` (see the
  sqlite-persistence reference for the path scheme).
- `dbPath` — an explicit database path (overrides `repoRoot`; used by tests
  and by callers that manage their own DB location).

## Envelope contract

Every mode prints exactly one JSON document to stdout. Logging goes to
stderr.

Success:

```json
{"ok": true, "data": <mode payload>}
```

Failure:

```json
{"ok": false, "error": {"code": "<stable code>", "message": "<human text>"}}
```

Error codes:

| code | meaning |
|---|---|
| `invalid_input` | malformed JSON, or a required input field missing/typed wrong |
| `not_found` | unknown symbol/file/type (distinct from an empty result) |
| `db_error` | the SQLite store could not be opened or queried |
| `unknown_mode` | dispatch error (not reachable via the CLI's fixed subcommands) |
| `invalid_pattern` | `find_pattern` pattern does not parse in the target language |
| `parse_error` | `find_pattern` source file contains syntax errors |
| `file_error` | `find_pattern` source file cannot be read |

Empty-vs-error contract: a known file/symbol with no matches returns
`{"ok": true, "data": []}`; an *unknown* file/symbol returns `not_found`.

## Modes

### Simple lookups

| mode | input fields | data payload |
|---|---|---|
| `symbols_in_file` | `filePath`, `includeBody?` (no-op — symbol bodies are not persisted) | array of symbols `{kind, name, file, span}` |
| `get_symbol` | `name`, `filePath?`, `kind?` | one symbol object |
| `tests_for_file` | `filePath` | array of test-file paths reaching the target via resolved import edges |
| `find_imports` | `filePath` | array of `{to, resolved, to_file_id}` import edges |
| `filter_symbols` | `kind?`, `file?`, `language?`, `minCyclomaticComplexity?`, `maxSymbols?` | array of symbols |

`filePath` matching: exact path, or trailing path components (`a.rs` matches
`/x/a.rs` but not `/x/ab.rs`). Test files are path-marked (`_test`,
`test_`, `.spec`, `.test`, `tests/`, `tests_`).

### Graph traversal

| mode | input fields | data payload |
|---|---|---|
| `dependencies` | `filePath`, `direction?` (`outgoing` default \| `incoming`), `maxDepth?` | array of reachable file paths |
| `dependents` | `filePath`, `maxDepth?` | array of dependent file paths |
| `blast_radius` | `filePath` | array of file paths reachable either direction (impact set, excluding self) |
| `symbol_blast_radius` | `name` | `{declaring_file, blast_radius:[...]}` |
| `type_hierarchy` | `name`, `filePath?` | `{symbol, hierarchy:[...]}` — the persisted containment chain (entity → enclosing function → file) |
| `explore` | `query: {kind:"dependency", params:{input, maxItems?}}` | `{input, reachable:[...]}` |

Performance: the full resolved-edge adjacency is loaded in two SQL
statements and traversed in memory (visited-set BFS), so statement count is
O(1) in the number of nodes and cyclic input always terminates.

### Mapping and diff

| mode | input fields | data payload |
|---|---|---|
| `map_file` | `filePath` | `{path, complexity, churn, fan_in, fan_out, community_id, community_label}` |
| `map_symbol` | `name`, `sourceFile?` | persisted entity fields (`kind`, `file`, `span`, optionals) |
| `map_path` | `sourceFile`, `targetFile`, `maxDepth?` | shortest dependency path (array of paths), or `[]` when unreachable |
| `detect_changes` | `diffMode` (`staged`\|`working_tree`\|`range`), `range?`, `repoRoot` | array per changed file: `{file, status, symbols:[{name, kind, change}]}` with `change` ∈ `added`\|`removed`\|`modified` |
| `hotspots` | — | array of `{file, complexity, churn, score}` ordered by `score` (complexity + churn) descending |

`detect_changes` mirrors the existing `code_query` contract: changed files
come from `git diff` (cached / worktree / range), and symbols are classified
by diffing the persisted store against the current source.

### find_pattern

| mode | input fields | data payload |
|---|---|---|
| `find_pattern` | `pattern`, `filePath`, `language?` | array of matches `{kind, text, span, captures}` |

Pattern syntax — a hand-rolled structural matcher over the parsed tree (no
ast-grep-core matching):

- `$VAR` — single-node capture: matches exactly one node of any kind.
- `$$$VAR` — variadic capture: matches zero or more sibling nodes.

Captures map each variable name to the matched node(s): a node object for
`$VAR`, an array for `$$$VAR`. Kind constraints and structural relational
rules are out of scope. The pattern is parsed in the target language after
rewriting `$VAR`/`$$$VAR` to marker identifiers; statement/expression
fragments that are not valid file-scope syntax are parsed inside a wrapper
function and the pattern node is extracted from it.

## Packaging

Release binaries are built for `aarch64-apple-darwin`, `x86_64-apple-darwin`,
`x86_64-unknown-linux-gnu`, and `aarch64-unknown-linux-gnu` (no Windows) by
`.github/workflows/release.yml` (per-target runner matrix, `--help`
subcommand verification, artifact upload). Release profile: `lto`,
`codegen-units = 1`, `strip`.
