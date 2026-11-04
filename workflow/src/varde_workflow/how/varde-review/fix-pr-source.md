---
topic: varde-review/fix-pr-source
version: 1
summary: PR intake for review threads and failing checks
---

## PR source

- Run `scripts/pr-intake.py <pr> [--repo-root DIR]` for JSON (`pr`, `threads`, `failing_checks`).
- Write one review folder `<working>/reviews/<YYYY-MM-DD>-pr-<number>/` with categories PR-REVIEW and CI. Add one `Status: open` finding per thread or failing check (location and summary), then follow the fix loop.
