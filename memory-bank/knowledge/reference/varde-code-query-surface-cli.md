---
type: reference
status: active
title: "varde-code query surface CLI"
related: ["2026-08-12-varde-code-rust-port/query-surface"]
---

# varde-code query surface CLI reference

Reference for selected varde-code query modes and the shared CLI envelope.
Indexed modes read the SQLite store and verify the required slices without
writing or refreshing it. `find_pattern` parses live source; `includeBody`
can read source text for persisted symbols.

Source of truth: `clis/code/crates/varde-code/src/query/mod.rs` (dispatch,
input preflight and envelope),
`clis/code/crates/varde-code/src/query/output.rs` (output policy), and
`clis/code/crates/varde-code/src/cli.rs` /
`clis/code/crates/varde-code/src/main.rs` (CLI routing).
The mode tables below are an overview. Use `varde-code --help` and
`varde-code <mode> --help` for the complete current command and field list.

## Invocation

```text
varde-code <mode> --json '<input object>'
```

One subcommand per mode, one-shot process per call. For indexed queries,
the `--json` object requires `repoRoot`, plus mode-specific fields:

- `repoRoot` identifies the source repository. Its index normally lives at
  `~/.config/varde-code/repos/<name>-<hash>/index.db`.
- `dbPath` optionally overrides the database location. It does **not** replace
  `repoRoot`. Freshness-gated queries also verify that the overridden index
  belongs to that source root; an old or mismatched index returns `index_stale`.

Example input for an indexed query:

```json
{"repoRoot": "/path/to/repo", "filePath": "src/main.rs"}
```

Missing indexes return `index_missing`. Stale required slices return
`index_stale`; wait for a ready watcher or search source directly. Queries
never repair the index themselves. `detect_changes` deliberately skips the
freshness gate so it can compare the stored snapshot with current source.

Exceptions: `find_pattern` needs a live file/directory target, not an index;
`slice_state` is a read-only diagnostic and can inspect an explicit `dbPath`
without `repoRoot`. In `batch`, indexed children need their own or inherited
`repoRoot`; inspect each child's result as well as the outer envelope.

## Envelope contract

By default, query commands print one JSON document to stdout; logging goes
to stderr. `nav_map --format text` is an explicit text-output exception.

A successful empty result:

```json
{"schema_version": 1, "ok": true, "outcome": "success", "data": [], "meta": {"compact": true, "truncated": false}}
```

Failure (for an indexed query missing `repoRoot`):

```json
{"schema_version": 1, "ok": false, "outcome": "tool-error", "data": {"error": {"code": "invalid_input", "message": "missing string field \"repoRoot\""}}, "meta": {"compact": false, "truncated": false}}
```

Read errors from `data.error`, never a top-level `error`. Check `ok` rather
than relying on the query process exit code. `outcome` normally reports
`success`, or promotes a payload's own outcome; errors report `tool-error`.
`schema_version` versions this envelope.

Paths in known repository-path fields are normally repository-relative, and
spans normally contain line bounds only. Set `absolutePaths: true` or
`includeSpanDetail: true` to retain the corresponding detail. `meta.compact`
reports that policy; `meta.truncated` reports omitted results. When present,
`meta.pagination` gives recovery information. Many indexed collections default
to 100 results and accept `resultsLimit`, `resultsOffset`, and `fullResults`;
check the selected mode's help. Optional `meta.toz` carries capture guidance.

Common error codes (not an exhaustive list):

| code | meaning |
|---|---|
| `invalid_input` | malformed JSON, or a required input field missing/typed wrong |
| `not_found` | unknown symbol/file/type (distinct from an empty result) |
| `index_missing` | no index at the selected database location |
| `index_stale` | source identity or required-slice freshness check failed |
| `ambiguous_symbol` | more than one declaration matches the requested symbol |
| `db_error` | the SQLite store could not be opened or queried |
| `unknown_mode` | unknown batch mode or internal dispatch error |
| `invalid_pattern` | `find_pattern` pattern does not parse in the target language |
| `parse_error` | `find_pattern` source file contains syntax errors |
| `file_error` | `find_pattern` source file cannot be read |

For lookups such as `symbols_in_file`, a known file with no symbols returns
an empty successful array; an unknown file returns `not_found`. Modes can
report per-item errors inside their payload (for example `symbols_in_files`
and `batch`), so inspect those items too.

## Modes

### Simple lookups

| mode | input fields | data payload |
|---|---|---|
| `symbols_in_file` | `filePath`, `includeBody?`, `includeReferences?` | array of symbols `{kind, name, file, span}` |
| `get_symbol` | `name`, `filePath?`, `kind?`, `includeBody?` | one symbol object |
| `tests_for_file` | `filePath` | array of test-file paths reaching the target via resolved import edges |
| `find_imports` | `filePath` | array of `{to, resolved, to_file_id}` import edges |
| `filter_symbols` | `kind?`, `file?`, `language?`, `minCyclomaticComplexity?`, `maxSymbols?` | array of symbols |

`filePath` matching: exact path, or trailing path components (`a.rs` matches
`/x/a.rs` but not `/x/ab.rs`). Test files are path-marked (`_test`,
`test_`, `.spec`, `.test`, `tests/`, `tests_`).

`includeBody: true` reads each symbol span from the current source file on a
best-effort basis; unreadable or invalid spans omit `body`.

### Graph traversal

| mode | input fields | data payload |
|---|---|---|
| `dependencies` | `filePath`, `direction?` (`outgoing` default \| `incoming`), `maxDepth?` | array of reachable file paths |
| `dependents` | `filePath`, `maxDepth?` | array of dependent file paths |
| `blast_radius` | `filePath` | array of transitive dependent file paths (potential downstream impact, excluding self) |
| `symbol_blast_radius` | `name`, `filePath?`, `kind?` | `{declaring_file, blast_radius:[...], analysis:{...}}`: reverse resolved call/inheritance impact of a unique declaration |
| `type_hierarchy` | `name`, `filePath?` | `{symbol, hierarchy:[...]}` — the persisted containment chain (entity → enclosing function → file) |
| `explore` | `query: {params:{input, direction?, maxItems?}}` | `{input, reachable:[...]}` |

Symbol impact is partial: arbitrary data references and dynamic dispatch are
not fully indexed. Ambiguous declarations return `ambiguous_symbol` instead of
selecting the first match. Calls with no unique named owner report their file
but stop propagation. An empty result does not prove isolation.

Performance: file-level resolved-edge adjacency is loaded in two SQL
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
| `find_pattern` | `pattern`, `filePath` or `path`, `language?`, `inside?`, `has?`, `precedes?`, `follows?` | `{matches:[{file,kind,text,span,captures}]}` |

Pattern syntax — a hand-rolled structural matcher over the parsed tree (no
ast-grep-core matching):

- `$VAR` — single-node capture: matches exactly one node of any kind.
- `$$$VAR` — variadic capture: matches zero or more sibling nodes.

Captures map each variable name to the matched node(s): a node object for
`$VAR`, an array for `$$$VAR`. `$VAR:kind` and `$$$VAR:kind` constrain captured node kinds.
Relational fields accept `{"kind": "..."}`: `inside` checks ancestors,
`has` checks descendants, and `precedes`/`follows` check later/earlier
siblings. Nested relational sub-patterns are not supported. The pattern is parsed in the target language after
rewriting `$VAR`/`$$$VAR` to marker identifiers; statement/expression
fragments that are not valid file-scope syntax are parsed inside a wrapper
function and the pattern node is extracted from it.

## Packaging

The Code module is a separate Cargo workspace at `clis/code/`. Its release
profile uses `lto`, `codegen-units = 1`, and `strip`. This checkout has no
`.github/workflows/release.yml`; it does not establish a release target matrix.
