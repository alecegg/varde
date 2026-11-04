---
topic: varde-learn/learn-gotchas
version: 1
summary: Paging truncated lists and handling a missing varde command
---

- For truncated `varde learn` lists (`meta.truncated: true`):
  - Repeat with `--offset` set to `meta.next_offset`.
  - Read every page before counting or judging.
- If `varde` is missing from `PATH`, report that friction cannot be recorded and continue unrelated work.
