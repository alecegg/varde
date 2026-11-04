---
topic: varde-toz/query-and-run
version: 1
summary: Query a capture by handle and run a batch script
---

- Query: `varde run query --handle <H> "error" "failed"`. Also `--chunk N`, `--lines A:B`, `--list`. Flags and query details: `varde run query --help`.
- Batch: `varde run run --script - <<'JS' ... vardeToz.exec({argv:[...]}) ... JS`. Flags, API, and capture behavior: `varde run run --help`.
- Pass `--timeout-ms` for long runs such as test suites.
- Run one `query` per call, or batch reads inside `run`. Start with `varde run`, not a shell loop or `cd`: capture hooks skip output only when the command starts with `varde run`.
- A `[redacted:...]` marker or `redacted N value(s)/pattern(s): LABEL` notice means the hook masked a secret. The hook cut nothing.
