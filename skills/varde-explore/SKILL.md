---
name: varde-explore
description: "Compare design options or explain how existing code works, in chat or as an HTML page. Not for planning, prototyping, or implementing."
---

# Explore before committing

## Choose a mode

| The request is | Do |
|---|---|
| An open question — problem, design, tradeoff, or how code works (default) | Answer in chat, grounded in files read (cite path:line). For options, name each one, its tradeoffs, and one recommendation. For structure (what exists, what depends on what, blast radius), load `references/varde-code.md`. |
| A direct ask to explain a diff or code area, or compare options, as a document to keep | Read `references/explain.md` and follow it. It saves an HTML file under `<working>/explanations/` by default. |

## Gotchas

- Resolve `<working>` (local, uncommitted) and `<knowledge>` (committed) only
  when a route uses them; chat answers without a knowledge lookup skip this.
  Before first use, run `varde-workflow paths --json`; use its absolute
  `data.working`/`data.knowledge` paths for this session and pass them to
  subagents. If the command fails, retry it once with escalated access; if it
  still fails, ask the user for the paths. Do not guess storage paths. A
  location outside the repo skips git ops (`check-ignore`, `mv`, `status`);
  use plain file ops.

- If the user explicitly asks to plan or build after exploring, start the
  matching `varde-change` route in the same turn without reconfirming the
  request. Settled work uses bounded build; unresolved choices follow the
  plan's own approval gates. Otherwise, offer the next step and wait.
