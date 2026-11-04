---
topic: varde-code/recover-results
version: 1
summary: Recover truncated context_pack results from the capture handle or by paging
---

- A cut sets `meta.truncated` and `meta.pagination.<section>`.
- Recover missing files from the capture first:

```sh
varde run query --handle <H>
```

- Query again with `includeOccurrences:true` only when matching occurrence rows are needed.
- With no capture, or one lacking needed sections, page with `resultsOffset` or use `fullResults:true`; see `context_pack --help` for paging options and the token estimate's meaning.
