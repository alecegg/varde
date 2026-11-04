---
topic: varde-learn/capture-steps
version: 1
summary: Where friction lives and the search, append and create commands
---

- Record obstacles caused by:
  - harnesses;
  - workers or subagents;
  - your own errors;
  - project tooling.
- Keep friction in `<store dir>/friction.jsonl`, the source of truth; `learn.db` is a rebuildable cache.
- Store it locally or in a private Git repository, where union merge combines entries.
- Delete `learn.db` to rebuild it, and export Markdown only when needed.
- Search for a distinctive phrase with `varde learn friction list --status open --text "<phrase>" [--repository <ROOT>] --json`, then inspect likely matches with `varde learn friction show <ID> --json`.
- Append evidence or create an item with `varde learn friction add --item <ID> | --source <S> --title <T> --text "<evidence>" --json`; review the similar-item hint before creating a duplicate.
