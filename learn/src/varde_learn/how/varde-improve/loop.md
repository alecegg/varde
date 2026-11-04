---
topic: varde-improve/loop
version: 3
summary: Improvement loop step 1, start here - rank skills and agents; then propose, decide, baseline
---

# Skill improvement loop

The loop starts only on request. It runs no model, no eval and no schedule;
every change waits for the user's accept.

## 1. Rank

`varde learn skills candidates [<dir>...]` ranks the synced skills and the shipped agents (no dir). Each skill or agent definition gets one direction:

- `add`: friction, how-skip friction or failed how requests. Promote the step the demand report names (`varde learn skills demand <skill>`).
- `trim`: no friction and a large route (1000+ tokens).
- `reset`: no friction and a very large route (4000+ tokens), by size alone, not by a model or harness change.

Within a direction, sort by friction count, then route tokens. With `--baselines <dir>`, a skill that has a baseline entry lists `add` rows with a fill evidence block. It lists `reset` only as `baseline restore (<gen>)` when it drifted, and nothing while it equals its baseline.
