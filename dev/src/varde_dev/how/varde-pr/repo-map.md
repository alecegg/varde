---
topic: varde-pr/repo-map
version: 1
summary: Refresh the repo map before PR creation
---

If `docs/repo-map/` exists, before `gh pr create`:

- On a main checkout (`.git` is a directory), run `varde map packs build --stale` and commit `docs/repo-map/` by path to the head branch.
- In a linked worktree (`.git` is a file), build refuses, so tell the user to run it on main.
