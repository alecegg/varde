---
topic: varde-customize/rule-verification
version: 1
summary: Add exact-clone or dependency verification to a sql rule
---

`verification` is SQL-only and needs a repository root during scans.

- `exact-clone` reparses candidate spans and compares canonical syntax trees
  (thresholds: see `duplicate-code-clone` in `varde scan rules list`). The
  query returns indexed function spans: `file`, `line`, `start_byte`,
  `end_byte`, `end_line`, optional `start_col`/`end_col`. Only verified rows
  survive.
- `dependency-facts` uses certified dependency facts: `temp.dependency_facts` (TEMP, absent from `.schema`; `from_file_id`, `from_unit`, `to_file_id`, `to_unit`, `kind`, `certainty`, `source_entity_id`, `specifier`). Base blocking policy on `certified` rows.
- `dependency-boundary` also needs `strings.source_prefix` and
  `strings.target_prefix`, each a normalized relative directory or `.`. Both
  blank leaves the policy inactive; one blank is invalid. Only configured
  prefixes match; no blanket prohibition on unresolved dependencies is
  inferred.
