# Capture observed friction

Outcome: one friction item or evidence entry per observed problem, specific enough to act on.

- Capture only problems that happened; skip predicted risks and general lessons.
- Use `--global` for friction not tied to this repository.
- Keep friction in `<store dir>/friction.jsonl`, the source of truth; `learn.db` is a rebuildable cache.
- Search open items for a match before creating a duplicate; append to a match, else create an item with a source and title.
- Keep evidence specific to the failed action, result, and immediate cost.
- Include the user's stated reason when recording a correction.

Validate: `varde learn friction list --status open --json` shows the item and its evidence.
