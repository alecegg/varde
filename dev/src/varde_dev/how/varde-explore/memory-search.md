---
topic: varde-explore/memory-search
version: 1
summary: Search plans, reviews and other agent memory without flooding output
---

- Search plans and reviews by topic with `varde search "<query>" --in plans`. It indexes only `<working>/plans` and `<working>/reviews` and needs a git repository. The first run in a new repo root or worktree re-indexes and can take a while.
- For exact terms or other memory dirs under the agent-memory root (`session-notes`, `skills`, `general`, `notes`, `review-gates`), use `rg -l <term> <dir>` and read the files. Cap `rg -n` with `-m 3` or `| head -40`; one term can print megabytes.
