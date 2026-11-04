---
topic: varde-customize/sql-rules
version: 1
summary: Write a sql rule query against the live index schema
---

`line` is one-based (`1 AS line` when there is none).
`JOIN files f ON f.id = <table>.file_id` exposes `path` as `file`.

Read the schema live:

1. `varde map slice_state --json '{"repoRoot":"<abs-root>"}'` (read-only)
   gives `data.db_path`; if `data.db` is `"missing"`, confirm index coverage
   first (Workflow step 8). Then `sqlite3 -readonly <db_path> .schema`.
2. For integer `kind` codes, copy a shipped rule's code or sample
   `SELECT name FROM entities WHERE kind = <n> LIMIT 5`.

Pitfalls:

- A `:key` with no declaration also fails at scan time, not load time.
- Filter `resolved_edges` on `resolved = 1` for real traversal.
- `entities.enclosing_function` is a bare name; same-named functions collide.
- `clone_bands` are approximate, not proof of duplication.
- Graph checks: self-join `resolved_edges` with `from` and `to` swapped; dedupe
  symmetric pairs with `e1.from_file_id < e1.to_file_id`.
