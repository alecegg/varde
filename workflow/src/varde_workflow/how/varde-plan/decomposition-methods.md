---
topic: varde-plan/decomposition-methods
version: 1
summary: Compute ownership overlap, find consumers, order and enqueue tasks, write task asserts
---

- Execution-wave computes overlap by glob intersection; keep genuinely
  overlapping tasks in separate waves, and compare ownership with active plans.
- Use `varde map` for consumers and generated/deleted paths and their readers;
  add dependencies for consumers.
- Under limited capacity, advance the longest dependency path.
- For a rename, also search split-string forms (`$VARDE work`,
  `['varde','work']`, `[[ $1 == work ]]`) and extend `owns`.
- The test-env helper in the `core/scripts` directory is source-only, so asserts
  run as `bash -c 'source <that helper>; uv run pytest <args>'`.
- Enqueue each task with `varde plan queue enqueue` as it is written; builders can
  pull ready tasks before the full list is written. Unknown dependency IDs show
  as `waiting-on-unwritten`.
