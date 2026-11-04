---
topic: varde-manage/sync-repo-map
version: 1
summary: Sync repo-map step, part 3 of 3, Proceed prompt on a TTY, apply only after approval
---

## Repo-map prompt and downloads

Repo-map step:

- At the top of a git main checkout, `varde setup sync` adds a
  managed pointer block (read `docs/repo-map/README.md`) to `AGENTS.md`. When
  that README is absent, it also runs `varde map packs build --all`.
- The repo-map step prints a summary first and asks `Proceed? [Y/n]` on a TTY only.
  `--yes` skips the prompt and `--dry-run` prints the summary only.
  `--no-packs`, `--json` and linked worktrees skip the step.
- The repo-map build downloads grammars, which fails in the sandbox
  (`docs/sandbox-permissions.md`).
