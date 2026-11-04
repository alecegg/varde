---
topic: varde-review/gotchas
version: 1
summary: Shell, git, path, role-dispatch and wrap-up pitfalls for review work
---

## Gotchas

- `varde-review` is a skill invoked by the harness, not a shell executable; do not check it with `command -v` or report a missing CLI.
- Run git as `git -C <absolute worktree path>`; never rely on the shell cwd, which may be an unreadable worktree.
- Run `varde setup paths --json` once; if it fails, retry with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.
- Use the role registered for the active harness when dispatching a reviewer or builder. Verify full documented `varde` argv against current help, and search split-string callers as well as literal command text.
- At the end of a write flow, load `varde-learn` with your skill tool and record real obstacles with it. Also load `varde-knowledge` and record durable decisions with it; otherwise skip both.
