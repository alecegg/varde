# Author a scan rule

`varde scan rules <cmd> --help` gives each subcommand's options; `varde scan
rules list` shows what loads.

## Outcomes

- The rule is grounded in concrete code that should and should not match; a
  vague request gets before-and-after examples first.
- The rule sits at the intended scope (default repo; ask when unclear).
  Repo rules live in `.varde-code/rules/`; user rules in
  `$VARDE_CODE_USER_RULES_DIR`, else the user config rules directory. Rules
  merge by `id` silently (repo, then user, then built-ins), so a rule with a
  built-in's `id` replaces it.
- Severity and any `thresholds`/`strings` defaults follow the stated policy;
  ask when the choice changes the rule's meaning.
- `pattern` sees one file; `sql` sees the whole index. A check needing a
  structural shape and a cross-file relationship needs `sql`.
- Every `sql` rule: the SELECT aliases `file` and `line`, and every declared
  `thresholds`/`strings` key appears in `query`, else the scan fails. Clone
  checks need `verification = "exact-clone"`; dependency policy needs
  `dependency-facts` or `dependency-boundary`.
- A rule missing a required field (`id`, `kind`, `severity`, `message`,
  `pattern` or `query`) is skipped with a diagnostic. Invalid rule loading or
  execution makes scan gates incomplete.
- Unknown fields are ignored silently, so field names are checked against the
  built-ins. Constraint regexes are unanchored.
- Every `[[rule.test]]` has `name` and uses `invalid` (must match) and `valid`
  (must not) snippets, or `expect_rows` for `sql`. It has at least one positive and one negative case,
  and `expect_rewrite` when `rewrite` is set. Positive and negative cases are
  verified separately for every declared language.

## Validation

- `varde scan test --json '{"rulesDir":"<dir-containing-the-toml>"}'` exits zero.
- `varde scan rules list` shows the rule's `source` (`custom`, `override`, or
  `builtin`) matching the intended scope.
- Optional dry-run: `varde scan` against real code, especially for `sql` rules.
  If it reports `index_missing` or `index_stale` and readiness fails,
  report the dry-run unavailable.
