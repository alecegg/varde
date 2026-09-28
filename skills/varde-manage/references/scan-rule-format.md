# varde-code rule pack format

Where this disagrees with the tool, the tool wins: `varde-code rules_list`
shows what loads, and `varde-code <cmd> --help` documents inputs.

A rule pack is a TOML file of `[[rule]]` entries. Unknown fields are ignored;
a rule missing a required field is skipped with a diagnostic. Invalid rule
loading or execution makes scan gates incomplete.

## Choosing pattern vs sql

| | `pattern` | `sql` |
|---|---|---|
| Sees | one file, one AST match at a time | the whole persisted index |
| Good for | a specific call, declaration, or literal shape | thresholds, aggregates, graph relationships (imports, complexity, churn, clones) |

A check needing both a structural shape and a cross-file relationship needs
`sql`, joining `entities` and `resolved_edges`.

## Rule fields

Required (else skipped and diagnosed):

- `id` — stable identifier; a repo or user rule with a built-in's `id`
  replaces it.
- `kind` — `"pattern"` or `"sql"`.
- `severity` — `"error"`, `"warning"`, or `"info"` (case-insensitive), ordered
  for `severityThreshold`.
- `message` — the finding's headline.
- `pattern` (for `kind = "pattern"`) or `query`, a SQL SELECT (for
  `kind = "sql"`).

Recommended, unvalidated, set by every built-in: `name`, `description`,
`remediation`.

Optional:

- `thresholds` (string → float) and `strings` (string → string) — SQL only;
  each key binds as a `:key` parameter.
- `verification` — SQL only: `"exact-clone"`, `"dependency-facts"`, or
  `"dependency-boundary"`; see below.
- `constraints` — capture name → regex string or array of regexes. Every
  listed constraint must pass; a missing capture drops the match; prefix a
  regex with `!` to negate it. Empty arrays and invalid regexes are execution
  diagnostics.
- `fix` — free-text guidance, never applied automatically.
- `rewrite` — pattern only: a `$VAR`/`$$$VAR` template applied by
  `scan --apply`. Every variable in it must appear in `pattern`, or the loader
  rejects the rule.
- `languages` — pattern only, e.g. `"javascript"`, `"typescript"`, `"tsx"`,
  `"python"`, `"rust"`, `"go"`. Omitted or empty runs on every parseable file;
  an explicit list must parse the pattern in every language.
- `test` — self-tests for `varde-code test`; `scan` ignores them.

```toml
[rule.constraints]
NAME = ["^get", "!^getDeprecated$"]
VALUE = "^[0-9]+$"
```

### Verification

Verification needs a repository root during scans.

- `exact-clone` reparses candidate spans and compares canonical syntax trees
  (thresholds: `duplicate-code-clone` in `rules_list`). The query returns
  indexed function spans — `file`, `line`, `start_byte`, `end_byte`,
  `end_line`, optional `start_col`/`end_col` — and only verified rows survive.
- `dependency-facts` uses certified dependency facts (below).
- `dependency-boundary` also needs `strings.source_prefix` and
  `strings.target_prefix`, each a normalized relative directory or `.`. Both
  blank leaves the policy inactive; one blank is invalid. Only the configured
  prefixes are matched; no blanket prohibition on unresolved dependencies is
  inferred.

## Pattern syntax

Patterns use the same ast-grep-style matcher as `find_pattern`.

- `$VAR` captures one AST node; `$$$VAR` captures a variadic list (arguments,
  statements).
- Everything else matches AST structure, not text. Declaration keywords such
  as `const` and `let` are stripped as trivia, so `const $KEY = $VAL` also
  matches `let` declarators — but `$KEY = $VAL` and `const $KEY = $VAL` still
  need separate `[[rule]]` entries (see `hardcoded-credential-*`).
- Constraints use Rust `regex` (no lookahead or lookbehind) via an unanchored
  `is_match`. Anchor with `^...$` unless substring matching is intended.

## SQL surface

`sql` queries read the persisted index. The SELECT must alias `file` as the
source path and `line` as a one-based line number (`1 AS line` when there is
no natural line).

The schema is not copied here; read it live:

1. **Worked queries.** `rules_list` returns every active rule's full `query`,
   exactly what the scanner runs. Start from the closest one.
2. **Tables and columns.** Run `varde-code build`; its `--help` names the
   `index.db` it writes. Read it with `sqlite3 -readonly <index.db> .schema`.
3. **Integer `kind` codes** for `entities.kind` and `resolved_edges.kind`: copy
   the code a shipped rule uses, or sample
   `SELECT name FROM entities WHERE kind = <n> LIMIT 5`.

Semantics the schema does not show:

- Filter `resolved_edges` on `resolved = 1` for real traversal; `0` rows are
  unresolved or external imports.
- `entities.enclosing_function` is a bare name, not an entity id, so
  same-named functions in one file collide.
- `clone_bands` are approximate navigation groups, not proof of duplication.
- `temp.dependency_facts` (SQLite TEMP storage, absent from `.schema`)
  columns: `from_file_id`, `from_unit`, `to_file_id`, `to_unit`, `kind`,
  `certainty`, `source_entity_id`, `specifier`. Base blocking policy on
  `certified` rows, not the persisted graph.

### Query conventions

- Every declared `thresholds`/`strings` key must appear in `query` or it is
  dead; a `:key` with no declaration fails at scan time, not load time.
- `JOIN files f ON f.id = <table>.file_id` exposes `path` as `file`.
- For graph checks, self-join `resolved_edges` with `from` and `to` swapped;
  dedupe symmetric pairs with `e1.from_file_id < e1.to_file_id`.
- Use `GROUP BY ... HAVING` for per-entity aggregates and `MIN(start_line)` for
  a representative line.

## Test entries

Every `[[rule.test]]` needs `name`.

**Pattern rules:** `invalid` snippets must match, `valid` snippets must not.
With `rewrite`, add `expect_rewrite` mapping input to expected output.

```toml
[[rule.test]]
name = "flags a plain assignment"
invalid = ["api_key = \"sk_live_1234567890abcdef\""]
valid = ["api_key = os.environ[\"API_KEY\"]"]

[rule.test.expect_rewrite]
"old_call(x)" = "new_call(x)"
```

**SQL rules:** the inline fixture tree is written to a temporary directory,
indexed through the real build pipeline (with verification when declared), and
queried. `expect_rows` compares final rows as an order-insensitive multiset.

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

Rules merge by `id`, silently: repo (`<repo_root>/.varde-code/rules/`) beats
user (`$VARDE_CODE_USER_RULES_DIR` or `~/.config/varde-code/rules/`), which beats
the built-ins embedded in the binary. `rules_seed` (add `--user` for user
scope) writes built-ins as editable files; `rules_remove` undoes it. The legacy
`VARDE_USER_RULES_DIR` remains a fallback when the canonical variable is unset.
