---
topic: varde-orchestrate/watchdog
version: 1
summary: Send milestone info, run the pulse watchdog, and handle blocked tasks
---

# Milestones and watchdog

- Send one `info` per task integration or completed wave, combining related facts.
- Run one `varde plan pulse <plan>` per watchdog round. On `pulse: idle`, take no further action that round.
- Use `varde-runner agent list` only when pulse shows an event needing follow-up; one call per worker.
- Mail is unreliable; pulse's file scan is the fallback and counts as notice for its caller. A pulse consumes file changes in its caller's state, so another agent's pulse may report idle.
- While work is pending, end the turn and wait for mail or a wake only when `varde msg status` shows the relay alive. Otherwise tell main with `varde msg send --kind blocked`. Never sleep-loop or repeat status calls.
- To await one command, run it once in the background with a long timeout.
- Update progress with `varde plan now <plan> "<status>"` (`--clear` when done).
- For blocked tasks or rejected transitions, resolve the blocker; never edit the file.
