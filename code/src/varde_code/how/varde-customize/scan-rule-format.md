---
topic: varde-customize/scan-rule-format
version: 1
summary: Scan rule required and optional fields, part 1 of 4, more fields, patterns and tests follow
---

A rule pack is a TOML file of `[[rule]]` entries. Unknown fields are ignored.

## Rule fields

Required (else skipped and diagnosed):

- `id` - stable identifier; a repo or user rule with a built-in's `id`
  replaces it.
- `kind`, `severity` (ordered for `severityThreshold`), `message`, and
  `pattern` or `query` per kind.

Optional:

- `thresholds` (string to float) and `strings` (string to string) - SQL only;
  each key binds as a `:key` parameter.
- `verification` - SQL only: `"exact-clone"`, `"dependency-facts"`, or
  `"dependency-boundary"` (topic `rule-verification`).
- `constraints` - capture name to regex string or array of regexes. Every
  listed constraint must pass; a missing capture drops the match; prefix a
  regex with `!` to negate it. Empty arrays and invalid regexes are execution
  diagnostics.
