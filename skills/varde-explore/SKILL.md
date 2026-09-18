---
name: varde-explore
description: "Investigate a problem, design, module, or diff without committing to implementation — compare options, trace how code works, or write a self-contained HTML explanation. Not for planning or production changes."
---

# Explore before committing

Create no plan or production code by default.
Read sources before forming conclusions or recommendations.

## What the request needs

| The request is | Read |
|---|---|
| An open question about a problem, design, tradeoff, or how some code works | `references/explore.md` |
| A direct ask to explain a diff or a code area, where the answer is a document to keep | `references/explain.md` |

A request to explain code always produces the HTML artifact. Open-ended
investigation never does.

Load only the reference the request needs.
Then load its explicitly required supporting files.

Offer `varde-change plan` once intent becomes concrete, and transition only on
direct user confirmation.
