---
type: pattern
title: SQL rule function identity
description: Function rules must join call sites through declaration identity.
generated: { by: codex/gpt-5, at: 2026-09-08T00:00:00+02:00 }
paths:
  - crates/varde-code/src/rules/builtin/vertical_slice_sprawl.toml
  - crates/varde-code/src/extract/entity.rs
  - crates/varde-code/src/extract/langs/cs.rs
---

# SQL rule function identity

Bare function names are not declaration identities.

- Use containment spans for call-site attribution.
- Include owning types when names support grouping.
- Test C# overloads and same-named methods.
- Treat property accessors as callable function scopes.

## Related

- [entity](/definition/entity.md) - entity fields and spans
- [SQL rule](/definition/sql-rule.md) - SQL rule execution
