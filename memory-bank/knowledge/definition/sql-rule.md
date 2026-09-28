---
slug: sql-rule
type: definition
definition: >-
  A [[rule]] whose `query` field is a SQL statement run read-only against
  varde-code's own intelligence-DB schema. Covers metric-threshold checks
  (god-file, complexity, fan-in/out), relational checks (dead code,
  duplication), and string-pattern checks (dependency boundary violations)
  that a [[pattern-rule]] cannot express.
---
