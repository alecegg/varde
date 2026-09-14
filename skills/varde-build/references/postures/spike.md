# Spike Posture

## Purpose

Throwaway exploration. The agent writes experimental code to answer a design question, then discards it and records the answer without committing implementation code.

## Cadence

1. State the single question the spike must answer. If there is more than one question, this is not a spike — use a different posture or split into multiple spikes.
2. Write the minimal throwaway code needed to answer the question — skip tests, edge-case handling, and code conventions.
3. Record the answer: apply a targeted edit to the task's own `tasks/<task-id>.md` `#### Progress` section to append it (question, approach tried, answer). Then apply a targeted edit to that same task file's frontmatter `status` to signal completion — the deliverable is the answer, not committed code. Never write to `plan.md` for this.
4. Discard the spike code (`git checkout .` or equivalent). Do not commit spike code.

## Verification

- The task's own `#### Progress` section contains an entry answering the spike's question.
- No spike code is committed.
- The working tree is clean after the spike (no uncommitted spike artifacts).

## When to use

- When a task explicitly says "spike" or "explore" in its title or context.
- When the task's goal is "answer question X" rather than "implement X".
- Time-box: if the spike takes longer than 30 minutes, it's not a spike — mark the task `blocked` instead (per `EXECUTION.md`'s Blocker Handling), not the plan.
