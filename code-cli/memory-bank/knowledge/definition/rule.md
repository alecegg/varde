---
slug: rule
type: definition
definition: >-
  A user-authored TOML file with id/message/severity metadata plus either a
  `pattern` (an ast-grep-style AST pattern, matched by varde-code's own
  matcher) or a `query` (a read-only SQL query against varde-code's schema).
  External and user-editable — not compiled into varde-code.
---
