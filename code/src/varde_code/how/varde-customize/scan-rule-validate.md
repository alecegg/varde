---
topic: varde-customize/scan-rule-validate
version: 1
summary: Scan rule steps 5-8, part 2 of 2, ask when policy is unclear, tests and validation
---

## Steps 5 to 8

5. **Fill the fields.** Choose `severity` and any `thresholds`/`strings`
   defaults from the stated policy; ask when the choice changes its meaning.
6. **Write `[[rule.test]]` self-tests** with at least one positive and one
   negative case, and `expect_rewrite` when `rewrite` is set. Verify positive
   and negative cases separately for every declared language; the runner unions
   matches across languages.
7. **Validate.** Run `varde scan test --json '{"rulesDir":"<dir>"}'` until it
   exits zero, then confirm with `varde scan rules list` that the rule's
   `source` matches the intended scope.
8. **Optional dry-run:** run `varde scan` against real code, especially for
   `sql` rules. On `index_missing` or `index_stale`, follow the code index
   readiness steps; if readiness fails, report the dry-run unavailable.
