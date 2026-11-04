---
topic: varde-orchestrate/review-wave
version: 1
summary: Plan review findings, one fix pass, and re-check
---

## Review and fix

- The one agent review is the plan review in `references/build-finish.md`; follow the shared review rule.
- Send its findings to one builder fix pass in the plan worktree, then dispatch a fresh reviewer to re-check only the named findings. Never run a second builder round.
- Integration checks and the plan review stay independent gates.
- Orchestrators never write an `approved` verdict; reviewers do. Only high-severity findings block.
