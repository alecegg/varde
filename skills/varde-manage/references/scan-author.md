# Author a scan rule

Use examples and intent from the request; ask only for missing match criteria.
Field reference, pattern syntax, SQL surface, tests, and scopes: `references/scan-rule-format.md`.

## Workflow

1. **Get examples.** Reuse concrete code that should and should not match; ask
   for missing cases. A
   vague request ("catch bad error handling") needs before-and-after examples
   first.
2. **Choose the kind** per "Choosing pattern vs sql" in
   `references/scan-rule-format.md`.
3. **Draft the payload.** Start from the closest active rule: `rules_list`
   returns each rule's full `pattern` or `query`, and `rules_seed` writes the
   built-in packs as TOML files. The `hardcoded-credential-*` pair shows
   multi-pattern, multi-constraint rules; `function-complexity-gate` shows SQL
   aggregation; `circular-import` shows a self-join.
4. **Fill the fields.** Choose `severity` and any `thresholds`/`strings`
   defaults from the stated policy; ask when the choice changes its meaning.
5. **Write `[[rule.test]]` self-tests** with at least one positive and one
   negative case, and `expect_rewrite` when `rewrite` is set. Verify positive
   and negative cases separately for every declared language: the runner
   unions matches across languages, so one passing multi-language test does
   not certify every grammar.
6. **Place it** per scan-rule-format `## Scopes and precedence` (default repo
   scope; ask when unclear). To customize a built-in, `rules_seed` and edit in
   place, keeping its `id`.
7. **Validate.** Run
   `varde-code test --json '{"rulesDir":"<dir-containing-the-toml>"}'` until it
   exits zero, then confirm with `rules_list` that the rule's `source`
   (`custom`, `override`, or `builtin`) matches the intended scope.
8. **Optional dry-run:** `varde-code scan` against real code, especially for
   `sql` rules.
9. **Record lessons.** Record real obstacles through `varde-learn` and durable
   decisions through `varde-knowledge`; otherwise skip.
