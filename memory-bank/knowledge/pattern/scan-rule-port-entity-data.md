---
type: pattern
description: Before porting a native varde-code scan rule to TOML or SQL, check that every entity.data field it reads is actually persisted.
generated: { by: claude/opus-5-5, at: 2026-09-24T07:48:31Z }
paths:
  - clis/code/crates/varde-code/src/rules/
  - clis/code/crates/varde-code/src/persist.rs
  - clis/code/crates/varde-code/src/db.rs
---

Check data availability before planning or decomposing a port of a native scan
rule to TOML or SQL.

- Native rules can read `entity.data.<field>` values the persisted schema never
  populates. A task scoped as "just port this rule to SQL" finds the gap only
  when the executor reads the native source mid-task, forcing a mid-run stop.
- Read each rule's implementation and list every `entity.data.<field>` it
  accesses.
- Check each field against the persisted schema by reading the db or schema
  module directly — never by assuming it matches a sibling rule's data shape.
- Any field not persisted is a data-foundation scope item: record it in the
  plan's spec and acceptance criteria as a prerequisite, and make it its own
  upfront indexer task with a `depends_on` edge from the port — not an "adjust
  if needed" note inside the porting task.
