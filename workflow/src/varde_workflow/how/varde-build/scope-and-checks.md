---
topic: varde-build/scope-and-checks
version: 1
summary: Take context from the task file without rereading the plan; slice the checks to the task
---

- Start with the task file named in the brief as task context; do not reread
  the plan. Follow the declared posture, or the default execution path when
  none is declared.
- Test only your slice: the task asserts and the changed package's unit tests.
  Add the one changed integration target only if the task edits an
  integration test or a CLI contract. After a fix, rerun only the failing
  target.
- Install a CLI change after merge from the main checkout, or build a PEX to a
  temp dir; never install from a linked worktree.
