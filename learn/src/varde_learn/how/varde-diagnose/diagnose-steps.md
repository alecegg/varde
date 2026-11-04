---
topic: varde-diagnose/diagnose-steps
version: 1
summary: 1 of 3 - resolve private store (ask before writing if access fails), list sessions
---

Resolve private storage:

1. Use the caller-supplied absolute working-store path, else `data.working` from `varde setup paths --json`.
2. On failure, retry unchanged once with escalated access, then ask for the path before writing.

`<resolved-working>` is that path. Name each report `<report-id>` as `<YYYY-MM-DD>-<slug>`; `<new-private-path>` is `<resolved-working>/diagnoses/<report-id>`.

Inspect bounded evidence. List recent sessions and linked workers:

```sh
varde learn sessions show --harness all --repository <repo-root> --json
```

Use `data.sources` and `data.children` to see inspection coverage. The list command groups only verified worker relationships; ambiguous or missing links remain uncovered.
