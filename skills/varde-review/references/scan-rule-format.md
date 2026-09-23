# varde-code rule pack format

The source of truth is `crates/varde-code/src/rules/mod.rs`
(`Rule`/`TestCase` structs), `pattern.rs`, and `sql.rs`. This document
summarizes them for rule authoring. If it disagrees with code, follow the code.

A rule pack is a TOML file with one or more `[[rule]]` entries. Each rule has
`kind = "pattern" | "sql"`. The parser ignores unknown fields. If a required
field is missing, it skips that rule and reports a diagnostic instead of
rejecting the whole file.

## Choosing pattern vs sql

| | `pattern` | `sql` |
|---|---|---|
| Scope | one file / one AST match at a time | whole persisted index, joins across files |
| Good for | a specific call/declaration/literal shape | thresholds, aggregates, graph relationships (imports, complexity, churn, clones) |
| Data source | live parsed source | index refreshed automatically by `scan` |
| Cross-file checks? | no | yes |

## Rule fields

Required. The rule is skipped and diagnosed if any field is missing:

- `id` (string) — stable identifier. A repo or user rule with the same `id` as
  a built-in silently replaces it. `rules_list` also uses `id` for deduplication.
- `kind` (`"pattern"` | `"sql"`)
- `severity` (`"error"` | `"warning"` | `"info"`, case-insensitive) —
  `error` > `warning` > `info` for threshold comparisons, such as scan's
  `severityThreshold` gate.
- `message` (string) — the finding's headline text.

Recommended. These are optional and unvalidated. Every built-in sets them:

- `name` (string) — short human title.
- `description` (string) — one/two sentences on what's being checked and why.
- `remediation` (string) — how to fix a finding.

Kind-specific payload (exactly one required, matching `kind`):

- `pattern` (string) — ast-grep-style pattern, required when `kind = "pattern"`.
- `query` (string) — SQL SELECT, required when `kind = "sql"`.

Kind-agnostic optional fields:

- `verification` (`"exact-clone"` | `"dependency-facts"` | `"dependency-boundary"`) — SQL only; optional source-aware verification.

- `thresholds` (table of string → float) — SQL only. Each key becomes a
  `:key` parameter in `query`.
- `strings` (table of string → string) — SQL only. It binds string parameters
  like `thresholds`.
- `constraints` maps captures to regex strings or string arrays.
  Pattern rules require every listed constraint to pass.
  Missing captures drop the match.
  Prefix individual regexes with `!` to negate their match.
  Empty arrays and invalid regexes produce execution diagnostics.
  Rust `regex` supports neither lookaheads nor lookbehinds.
- `fix` (string) — free-text fix guidance. It is informational and never
  applied automatically. Valid for either kind.
- `rewrite` (string) — pattern only. This meta-variable template
  (`$VAR`/`$$$VAR`) applies to matched spans when `scan --apply` runs. Every
  variable in `rewrite` must appear in `pattern`; the loader rejects unknown
  captures.
- `languages` (array of strings) — pattern only. Names must resolve through
  `SupportLang`, such as `"javascript"`, `"typescript"`, `"tsx"`, `"python"`,
  `"rust"`, and `"go"`. Omitted or empty runs against every parseable file.
- `test` — see "Test entries" below. `scan` ignores it; `varde-code test` uses
  it.

Verification requires a repository root during scans. `exact-clone` reparses
candidate spans and compares canonical syntax trees. Defaults are
`min_tokens = 20`, `min_members = 3`, and `min_span_lines = 8`.
`dependency-facts` uses certified dependency facts. `dependency-boundary` also
requires both `strings.source_prefix` and `strings.target_prefix`, each a
normalized relative directory or `.`. Both blank leaves the policy inactive;
one blank is invalid. Matching uses only explicitly configured source and
target prefixes. It does not infer a blanket unresolved dependency prohibition.

Constraint forms can coexist:

```toml
[rule.constraints]
NAME = ["^get", "!^getDeprecated$"]
VALUE = "^[0-9]+$"
```

Invalid rule loading or execution makes scan gates incomplete.
Explicit language scopes must parse the pattern in every language.

## Pattern syntax

The pattern engine reuses `find_pattern`'s ast-grep-style matcher. This is the
same engine as `find_pattern` scan-benchmark mode.

- `$VAR` captures a single AST node.
- `$$$VAR` captures a variadic list of nodes (e.g. call arguments, statement lists).
- Everything else in the pattern string matches AST structure literally, not
  text. The matcher strips declaration keywords such as `const` and `let` as
  trivia. Therefore `const $KEY = $VAL` also matches `let` declarators.
- Constraints apply per capture through `regex::is_match`, which is unanchored.
  Anchor with `^...$` unless substring matching is intentional.

Worked example:
`crates/varde-code/src/rules/builtin/hardcoded_credential_literal.toml` has
two `[[rule]]` entries. One pattern cannot express both `$KEY = $VAL` and
`const $KEY = $VAL`. Both entries reuse the same `constraints`.

## SQL surface

`kind = "sql"` queries read the persisted index from `varde-code build`. The
SELECT must alias `file` as the source path and `line` as a one-based line
number. Use `1 AS line` when the check has no natural line.

### Tables

**`files`** — one row per indexed file.
| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `path` | TEXT | repo-relative source path |
| `mtime`, `size` | INTEGER | |
| `content_hash` | TEXT | |
| `complexity` | INTEGER | `1 + count(ControlFlow entities)` in the file |
| `churn` | INTEGER | commit-touch count (see `git`-derived churn signal) |
| `fan_in`, `fan_out` | INTEGER | denormalized edge counts |
| `community_id` | INTEGER | clustering group, FK-ish to `communities.id` |

**`entities`** — one row per extracted language construct (functions, classes, calls, literals, control-flow nodes, etc.)
| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `kind` | INTEGER | see `EntityKind` codes below |
| `name` | TEXT | |
| `file_id` | INTEGER | FK to `files.id` |
| `start_byte`/`end_byte`, `start_line`/`start_col`, `end_line`/`end_col` | INTEGER | |
| `enclosing_function` | TEXT, nullable | bare name of the narrowest enclosing named function — **not** an entity id, so same-named functions in one file collide (see `file-complexity-hotspot`'s known-limitation comment) |
| `method`, `path`, `status`, `body_shape` | TEXT, nullable | kind-specific payload (e.g. `Route`/`Response` entities) |
| `body_minhash` | BLOB, nullable | clone-detection signature |
| `is_async` | BOOLEAN, nullable | |

**`entities.kind` codes** (`EntityKind::as_i64`, append-only — never reorder):
`0` function, `1` class, `2` interface, `3` variable, `4` parameter, `5` export, `6` call, `7` literal, `8` member_access, `9` import, `10` catch, `11` throw, `12` control_flow, `13` route, `14` response, `15` extends, `16` implements, `17` decorator.

**`symbols`** — lighter-weight symbol table (id, kind, name, file_id, span). Same `start_*`/`end_*` shape as `entities`, no `enclosing_function`/kind-specific payload columns.

**`resolved_edges`** — one row per resolved relationship between files/entities.
| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `from_file_id`, `to_file_id` | INTEGER (`to_file_id` nullable) | |
| `kind` | INTEGER | see `EdgeKind` codes below |
| `resolved` | INTEGER (bool) | `1` if the edge target was actually resolved to a file, `0` for unresolved (external/unresolvable import etc.) — filter on `resolved = 1` for real graph traversal |
| `from_entity_id`, `to_entity_id` | INTEGER, nullable | entity-level endpoints when known |

**`resolved_edges.kind` codes** (`EdgeKind::as_i64`): `0` call, `1` import, `2` extends, `3` implements.

**`diagnostics`** — id, file_id, path, message, severity (parse/extraction diagnostics, not scan findings).

**`communities`** / **`community_members`** — clustering groups and file membership.

**`clone_bands`** / **`clone_band_members`** — approximate near-duplicate groups for navigation. `duplicate-code-clone` verifies source trees with `exact-clone`; it does not treat these tables as proof.

**`temp.dependency_facts`** — scan-local certified dependency facts. It is
prepared only when an active rule uses dependency verification, then recreated
in SQLite TEMP storage. It never changes the index schema. Columns
are `from_file_id`, `from_unit`, `to_file_id`, `to_unit`, `kind`, `certainty`,
`source_entity_id`, and `specifier`. `certainty = "certified"` means source
and indexed targets agree; `certainty = "missing"` means a recognized local
target is absent. Relative JS, TS, TSX, Dart, and Solidity
imports require one matching physical and indexed target. Go uses resolved
module-aware edges plus a physical target check. Test, tooling, type-only, and
ambiguous loader imports are excluded. Use this table for blocking dependency
policy; persisted graph tables remain approximate signals.

For `exact-clone`, the SQL query must return valid indexed function spans:
`file`, `line`, `start_byte`, `end_byte`, `end_line`, and optional
`start_col`/`end_col`. Columns populate the finding span, not evidence. The
verifier reparses candidates and returns only final verified rows.

Indexes cover `resolved_edges(from_file_id/to_file_id/from_entity_id/to_entity_id)`
and `entities`/`symbols`(`file_id`, `name`). Filtering or joining on those
columns is cheap. Other columns require a full scan.

### Query conventions

- Bind thresholds and strings as `:key`. Every declared key must appear in
  `query`, or it is inert. Every `:key` in `query` needs a matching declaration,
  or binding fails at scan time.
- Exact-clone candidates need `token_count >= 20`, at least 3 verified members,
  and `end_line - start_line >= 8`, which spans at least 9 inclusive lines.
- Use `JOIN files f ON f.id = <table>.file_id` to expose `path` as `file`.
- For graph checks, self-join `resolved_edges`. See `circular_import.toml`.
  Join swapped `from` and `to` values. Dedupe symmetric pairs with
  `e1.from_file_id < e1.to_file_id`.
- Use `GROUP BY ... HAVING` for per-entity aggregates. See
  `file-complexity-hotspot` in `complexity.toml`. Use `MIN(start_line)` for
  a representative line when grouping collapses rows.

## Test entries

`[[rule.test]]` blocks are self-tests validated by `varde-code test`. `scan` ignores
them. Every entry needs `name`; the remaining fields depend on the rule kind.

**Pattern rules:**
```toml
[[rule.test]]
name = "flags a plain assignment"
invalid = ["api_key = \"sk_live_1234567890abcdef\""]   # snippets that MUST match
valid = ["api_key = os.environ[\"API_KEY\"]"]           # snippets that must NOT match
```
If the rule sets `rewrite`, add `expect_rewrite`: a map from input snippet to
the expected output after applying the rewrite template.
```toml
[rule.test.expect_rewrite]
"old_call(x)" = "new_call(x)"
```

**SQL rules:** The test writes an inline fixture tree to a fresh temporary
directory, indexes it through the real build pipeline, prepares source-aware
verification when declared, and runs the query. `expect_rows` compares the
verifier's final rows as an order-insensitive
multiset.
```toml
[[rule.test]]
name = "flags a file over the complexity threshold"
[rule.test.fixture]
"big.py" = "if a:\n if b:\n  if c:\n   pass\n"
[[rule.test.expect_rows]]
file = "big.py"
line = 1
```

## Scopes and precedence

- **Built-in** — embedded in the `varde-code` binary (`crates/varde-code/src/rules/builtin/*.toml`), lowest priority.
- **User** — `$VARDE_USER_RULES_DIR` or `~/.config/varde-code/rules/`, applies across every repo.
- **Repo** — `<repo_root>/.varde-code/rules/`, applies to this repo only, highest priority.

Merge rules by `id`: repo wins over user, and user wins over built-in. The merge
is silent, with no diagnostic. This is how a default is disabled or replaced.
`varde-code rules_seed` materializes built-ins as editable files in either
scope, so you can edit them in place instead of re-authoring them.
