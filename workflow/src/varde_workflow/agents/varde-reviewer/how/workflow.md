---
topic: varde-reviewer/workflow
version: 1
summary: Order of work for a review request
---

1. Resolve the requested review mode.
2. When briefed with a chunk file list by a report orchestrator, review only that chunk, return findings, and write nothing.
3. Otherwise follow the varde-review report workflow completely: write findings immediately to `review.md` in its review folder, and return that folder and a summary.
4. When the read is over budget, report back to the caller to split the review; never split it yourself.
5. Standalone default modes are `CORRECTNESS`, `CODE`, and `ARCHITECTURE`; in a plan use the mode named in the brief. A thorough or full review covers all categories in `references/report-categories.md`, filtered by relevance.
6. Use repository-relative finding locations and record each finding severity.
