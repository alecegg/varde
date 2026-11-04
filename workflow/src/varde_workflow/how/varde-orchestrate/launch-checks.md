---
topic: varde-orchestrate/launch-checks
version: 1
summary: Bind worker addresses, check message delivery, and recover lost worktrees
---

# Launch checks

- Pass `--slot <SLOT> --plan <PLAN>` to `varde-runner agent launch`; it prefixes the worker prompt with a one-time `[varde-address: ...]` marker for address binding.
- Check `varde msg status` for delivery lag and pending mail before merge, sync, or conclusion.
- Never run `git worktree prune`; if worktree admin dirs are lost, move the worktree aside, run `git worktree add <path> <branch>`, then copy uncommitted files back (not its `.git` file).
