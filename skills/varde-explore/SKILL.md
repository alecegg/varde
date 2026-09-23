---
name: varde-explore
description: "Investigate a problem, design, module, or diff without committing to implementation — compare options, trace how code works, or write a self-contained HTML explanation. Not for planning or production changes."
---

# Explore before committing

Do not create a plan or production code unless the user asks.
Read sources before forming conclusions or recommendations.

## Choose a mode

| The request is | Do |
|---|---|
| An open question about a problem, design, tradeoff, or how some code works | Run `## Explore` below. This is the default mode. Answer in the conversation. |
| A direct ask to explain a diff or a code area, where the answer is a document to keep | Read `references/explain.md` and follow it. It produces an HTML file. |

## Explore

Gather evidence directly to answer the question.

1. Restate the decision or uncertainty.
2. Read relevant source, artifacts, and project guidance.
3. Compare credible alternatives against the same constraints.
4. Check each assumption against existing project terminology.
5. Summarize evidence, tradeoffs, and remaining uncertainty.

For structural questions, load `references/varde-code.md`. These questions ask
what exists, what depends on what, or how far a change would reach. If the
optional CLI is absent or fails, use ordinary reads.

Return evidence, tradeoffs, and a recommendation. Do not create planning
artifacts, production code, or prototypes unless the user asks for them by name.

## Gotchas

- A request to explain code always produces the HTML artifact. Open-ended
  investigation never does.
- When intent becomes concrete, offer `varde-change plan`. Transition only after
  direct user confirmation.
