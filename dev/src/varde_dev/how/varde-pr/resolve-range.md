---
topic: varde-pr/resolve-range
version: 1
summary: Find the base and head of the PR range
---

- For an existing PR, run `gh pr view <number> --json number,title,body,baseRefName,headRefName,url` and check out its head branch before gathering range facts.
- Otherwise run `gh repo view --json defaultBranchRef` and use the default branch as base.
- Stop if the range has no commits or changed files.
