---
topic: varde-knowledge/note-search
version: 1
summary: Find a note by broad map or ranked search
---

| Need | Do |
|---|---|
| Broad discovery | Run `varde learn memory map`. |
| A precise term | Run ranked search (below), else Grep/Glob `<memory>/` per the fallback rule in `references/varde-workflow-cli.md`. |

Run `varde learn memory search --text "<query>" --limit 10`; add `--topic <t>`, `--scope <s>` or `--field key=value` to narrow. It ranks every entry, knowledge notes included. Read a note in full (`memory show <id>`) only after discovery identifies it.
