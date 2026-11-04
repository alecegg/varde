---
topic: varde-customize/scan-rule-workflow
version: 1
summary: Scan rule steps 1-4, part 1 of 2, ask for examples and scope, validation in scan-rule-validate
---

## Steps 1 to 4

1. **Get examples.** Reuse concrete code that should and should not match; ask
   for missing cases. A vague request ("catch bad error handling") needs
   before-and-after examples first.
2. **Place it** per scopes (default repo scope; ask when unclear). To customize
   a built-in, run `varde scan rules seed` and edit in place, keeping its `id`.
3. **Choose the kind**: `pattern` sees one file, one AST match at a time (a
   specific call, declaration, or literal shape). `sql` sees the whole index
   (thresholds, aggregates, imports, complexity, churn, clones), so a check
   needing both needs `sql`, joining `entities` and `resolved_edges`. Before
   drafting a `sql` rule, request topic `sql-rules`.
4. **Draft the payload** by copying the closest active rule from
   `varde scan rules list` (full `pattern` or `query`) or `varde scan rules
   seed` (`--user` for user scope; writes built-in TOML packs). Study
   `hardcoded-credential-*` (multi-pattern, multi-constraint),
   `function-complexity-gate` (SQL aggregation), and `circular-import`
   (self-join) as models. For clone or dependency checks, request topic
   `rule-verification`.
