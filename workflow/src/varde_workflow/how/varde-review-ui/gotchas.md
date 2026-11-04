---
topic: varde-review-ui/gotchas
version: 1
summary: Git, path and wrap-up habits for a running-UI review
---

## Gotchas

- Run git as `git -C <absolute worktree path>`; never rely on the shell cwd, which may be an unreadable worktree.
- At the end of a write flow, load `varde-learn` and record real obstacles with it; load `varde-knowledge` and record durable decisions with it; otherwise skip.
- Run `varde setup paths --json` once; if it fails, retry with escalated access, then ask; never guess.
- After findings exist, fix them with `varde-review` (`fix`); this skill reports and does not edit source.
