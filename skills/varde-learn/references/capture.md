# Capture observed friction

- Capture only problems that happened; skip predicted risks and general lessons.
- Record obstacles caused by:
  - harnesses;
  - workers or subagents;
  - your own errors;
  - project tooling.
- Use `--global` for friction not tied to this repository.

- Keep friction in `<store dir>/friction.jsonl`, the source of truth; `learn.db` is a rebuildable cache.
- Store it locally or in a private Git repository, where union merge combines entries.
- Delete `learn.db` to rebuild it, and export Markdown only when needed.

- Search open items for a distinctive phrase and inspect likely matches: `varde learn friction list --status open --text "<phrase>" [--repository <ROOT>] --json`, then `friction show <ID> --json`. Use `--repository <ROOT>` to filter to a project.

- Append evidence to a match, or create an item with `varde learn friction add --item <ID> | --source <S> --title <T> --text "<evidence>" --json`; check the similar-item hint before creating a duplicate.

- Keep evidence specific to the failed action, result, and immediate cost.
- Include the user's stated reason when recording a correction.
