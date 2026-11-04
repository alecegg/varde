---
topic: varde-pr/save-and-publish
version: 1
summary: Save the PR body file and create or edit the PR
---

- Resolve `<working>` with `varde setup paths --json`, create `<working>/pr/`, save the body as `<working>/pr/<YYYY-MM-DD>-<slug>.md`, and report the path.
- Publish only on an explicit request. If `docs/repo-map/` exists, refresh the repo map first (see the repo-map topic).
- Confirm the head branch is already pushed, since `gh pr create` may prompt to push.
- Run `gh pr create --title <title> --body-file <file> --base <base> [--draft]` or `gh pr edit <number> --body-file <file>`.
- Do not pass body text with `--body` or push the branch.
