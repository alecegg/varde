---
slug: pattern-rule
type: definition
definition: >-
  A [[rule]] whose `pattern` field is an ast-grep-style structural AST
  pattern (with optional relational constraints such as inside/has/precedes),
  matched per-file against the parsed tree. Covers structural/shape checks;
  cannot express counts, thresholds, or joins across entities.
---
