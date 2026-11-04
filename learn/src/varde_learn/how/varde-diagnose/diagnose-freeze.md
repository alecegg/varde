---
topic: varde-diagnose/diagnose-freeze
version: 1
summary: 2 of 3 - freeze and page one session; pick procedure from data.overlap, verified --current only
---

# Freeze and page a session

Freeze one session:

```sh
varde learn sessions show --harness codex --session <THREAD_ID> --snapshot-out <new-private-path>/bundle.json --json
```

- Select with `--harness {codex,claude,opencode}` and exactly one of `--current`, `--session <ID>`, or `--path <FILE>`.
- `--current` needs a verified harness identity. Claude supplies it only as command-hook JSON on stdin, which an agent session cannot provide; OpenCode does not expose a verified current caller identity.
- Select the analysis procedure from `data.overlap` (`current`, `not_current`, or `unknown`), never from the selector: a path or ID can alias the invoking session.

Page a saved bundle:

```sh
varde learn sessions show --snapshot-in <bundle.json> --offset N --limit N --json
```

Inspect `data.coverage.unknown_events`, `data.coverage.inherited_events` (events from a copied or forked history prefix), and warnings. Unknown events retain a bounded `unknown_payload_excerpt`, so inspect it before interpreting the event.
