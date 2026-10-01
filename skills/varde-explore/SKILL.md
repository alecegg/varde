---
name: varde-explore
description: "Compare design options or explain how existing code works, in chat or as an HTML page. Not for planning, prototyping, or implementing."
---

# Explore before committing

## Choose a mode

| The request is | Do |
|---|---|
| An open question: problem, design, tradeoff, or how code works (default) | Answer in chat (default). |
| A direct ask to explain a diff or code area, or compare options, as a document to keep | Read `references/explain.md` and follow it. |

## Chat answers

- Ground answers in files read and cite `path:line`.
- For options, name each one, give its tradeoffs, and recommend one.
- For structure questions (what exists, what depends on what, blast radius), load `references/varde-code-cli.md`.

## Gotchas

- Resolve `<working>` and `<knowledge>` once with `varde-workflow paths --json`; retry once with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.

- If the user explicitly asks to plan or build after exploring, start the
  matching `varde-change` route in the same turn without reconfirming; otherwise,
  offer the next step and wait.
