---
topic: varde-plan/setup-tools
version: 1
summary: Resolve paths, set label and group, and research the prompt on the first turn
---

- Run `varde setup paths --json` once to resolve `<working>` and `<knowledge>`.
  Outside repos, use `mv`, not `git mv`.
- Run Varde commands and read `--help` when unclear.
- Set `group` by inheriting the parent's, else reuse a `varde plan status --json`
  `group_name`.
- Research the prompt with `varde map context_pack` (topic query; see its `--help`).
- Research an unknown with a `[needs prototype]` run by loading `varde-prototype`:
  use your skill tool, or read `../../varde-prototype/SKILL.md`.
- Tell the user the plan path, welcome direct edits, then ask one question and wait.
