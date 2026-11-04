---
topic: varde-builder/checks
version: 1
summary: Which checks to run and how to wait on them
---

- Run only the assigned lint and verification checks before recording completion.
- Test only your slice: task asserts plus unit tests of the changed package, and the one changed integration target only if the task edits an integration test or a CLI contract.
- After a fix rerun only the failing target.
- Do not poll a running command or agent; wait on completion or use one long wait.
- Follow the selected skill completely; load `references/build-execution.md`, this role file, and the task file, and a posture reference only when the task declares one.
