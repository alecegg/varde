---
name: varde-prototype
description: "Shape and prototype frontend pages, layouts, and interactions, or build a clickable walkthrough of a state model or data shape. Not for production implementation (varde-change) or formal review of a running UI (varde-review)."
---

# Shape and prototype a design question

Prototype files under `<storage>` need no review gate; production edits go
through `varde-change`.

## Pick the track

| The question is | Track |
|---|---|
| Shape, prototype, or refine a frontend page, layout, or component | Visual — `references/visual-track.md` |
| "Does this state model, logic, or data shape feel right?" — state machine, reducer, API shape | Logic — `references/logic-track.md` |

Ambiguous: pages/components → Visual; states/data → Logic; say which.

## Rules for every round

- Ask one topic per turn (≤3 questions only as facets of one decision) as an
  inline numbered menu with a recommendation.
- Deliver a plain HTML file on disk and report its path first after every
  write; an `Artifact`/`mcp__visualize` preview is additive, never a
  substitute.

## Workflow

1. **Pick a slug and storage path.** Choose a kebab-case `<slug>` and state
   the storage path: `<working>/prototypes/<slug>/`, or
   `<working>/plans/<plan-id>/prototypes/<slug>/` when a plan owns the work;
   the track references call it `<storage>`. Ask only if that path already
   exists.
2. **Run the track's rounds**, per its reference.
3. **Close when the user is done:** report the final file path and key
   decisions (Logic: name the module to lift). If the user asked to plan or
   build, start `varde-change` in the same turn; otherwise offer it and wait.

## Gotchas

- Resolve `<working>` and `<knowledge>` once with `varde-workflow paths --json`; retry once with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.
