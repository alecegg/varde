---
slug: rewrite
type: definition
definition: >-
  A pattern rule's `rewrite` field: a template using the same meta-variable
  syntax as the rule's pattern (e.g. `$VAR`), substituted with the captured
  match's meta-variable values to produce a literal replacement for the
  matched source span.
avoid:
  - fix (that field is unchanged, free-text remediation guidance — not a rewrite template)
---
