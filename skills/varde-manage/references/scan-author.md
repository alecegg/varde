# Author a scan rule

`varde-code <cmd> --help` gives each subcommand's JSON input; `rules_list`
shows what loads.

## Workflow

1. **Get examples.** Reuse concrete code that should and should not match; ask
   for missing cases. A vague request ("catch bad error handling") needs
   before-and-after examples first.
2. **Choose the kind** per Choosing pattern vs sql.
3. **Draft the payload.** Start from the closest active rule: `rules_list`
   returns each rule's full `pattern` or `query`, and `rules_seed` writes the
   built-in packs as TOML files. The `hardcoded-credential-*` pair shows
   multi-pattern, multi-constraint rules; `function-complexity-gate` shows SQL
   aggregation; `circular-import` shows a self-join.
4. **Fill the fields.** Choose `severity` and any `thresholds`/`strings`
   defaults from the stated policy; ask when the choice changes its meaning.
5. **Write `[[rule.test]]` self-tests** with at least one positive and one
   negative case, and `expect_rewrite` when `rewrite` is set. Verify positive
   and negative cases separately for every declared language; the runner
   unions matches across languages.
6. **Place it** per Scopes and precedence (default repo scope; ask when
   unclear). To customize a built-in, `rules_seed` and edit in place, keeping
   its `id`.
7. **Validate.** Run
   `varde-code test --json '{"rulesDir":"<dir-containing-the-toml>"}'` until it
   exits zero, then confirm with `rules_list` that the rule's `source`
   (`custom`, `override`, or `builtin`) matches the intended scope.
8. **Optional dry-run:** `varde-code scan` against real code, especially for
   `sql` rules.

## Rule pack format

A rule pack is a TOML file of `[[rule]]` entries. Unknown fields are ignored;
a rule missing a required field is skipped with a diagnostic, and invalid rule
loading or execution makes scan gates incomplete.

### Choosing pattern vs sql

| | `pattern` | `sql` |
|---|---|---|
| Sees | one file, one AST match at a time | the whole persisted index |
| Good for | a specific call, declaration, or literal shape | thresholds, aggregates, graph relationships (imports, complexity, churn, clones) |

A check needing both a structural shape and a cross-file relationship needs
`sql`, joining `entities` and `resolved_edges`.

### Rule fields

Required (else skipped and diagnosed):

- `id` — stable identifier; a repo or user rule with a built-in's `id`
  replaces it.
- `kind`, `severity` (ordered for `severityThreshold`), `message`, and
  `pattern` or `query` per kind.

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
- `name`, `description`, `remediation` — not validated; set them like the
  built-ins. Rule listings show `name` and `description`; scan output shows
  `remediation` in its rule legend.

```toml
[rule.constraints]
NAME = ["^get", "!^getDeprecated$"]
VALUE = "^[0-9]+$"
```

#### Verification

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

### Pattern syntax

Patterns use the same ast-grep-style matcher as `find_pattern`.

- `$VAR` captures one AST node; `$$$VAR` captures a variadic list (arguments,
  statements).
- Everything else matches AST structure, not text. Declaration keywords such
  as `const` and `let` are stripped as trivia, so `const $KEY = $VAL` also
  matches `let` declarators — but `$KEY = $VAL` and `const $KEY = $VAL` still
  need separate `[[rule]]` entries (see `hardcoded-credential-*`).
- Constraints use Rust `regex` (no lookahead or lookbehind) via an unanchored
  `is_match`. Anchor with `^...$` unless substring matching is intended.

### SQL surface

The SELECT must alias `file` as the source path and `line` as a one-based line number (`1 AS line` when there is
no natural line).

Read the schema live:

1. **Tables and columns.** Run `varde-code build`; its `--help` names the
   `index.db` it writes. Read it with `sqlite3 -readonly <index.db> .schema`.
2. **Integer `kind` codes** for `entities.kind` and `resolved_edges.kind`: copy
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

#### Query conventions

- Every declared `thresholds`/`strings` key must appear in `query` or it is
  dead; a `:key` with no declaration fails at scan time, not load time.
- `JOIN files f ON f.id = <table>.file_id` exposes `path` as `file`.
- For graph checks, self-join `resolved_edges` with `from` and `to` swapped;
  dedupe symmetric pairs with `e1.from_file_id < e1.to_file_id`.

### Test entries

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

**SQL rules:** the inline `fixture` tree is indexed through the real build
(with verification when declared); `expect_rows` compares final rows as an
order-insensitive multiset.

```toml
[[rule.test]]
name = "flags a file over the complexity threshold"
[rule.test.fixture]
"big.py" = "if a:\n if b:\n  if c:\n   pass\n"
[[rule.test.expect_rows]]
file = "big.py"
line = 1
```

### Scopes and precedence

Rules merge by `id`, silently, in this order of precedence:

1. Repo: `<repo_root>/.varde-code/rules/`.
2. User: `$VARDE_CODE_USER_RULES_DIR` (legacy fallback `VARDE_USER_RULES_DIR`),
   else `~/.config/varde-code/rules/`.
3. Built-ins embedded in the binary.
