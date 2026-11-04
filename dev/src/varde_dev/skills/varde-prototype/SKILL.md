---
name: varde-prototype
description: "Use this skill when the user wants to shape or prototype a frontend page, layout, or interaction, or to click through a state model, logic, or data shape to see whether it feels right, including wireframes."
recommends: [varde-plan, varde-build]
---

# Shape and prototype a design question

Prototype files under `<storage>` need no review gate.

## Pick the track

| The question is | Track |
|---|---|
| Shape, prototype, or refine a frontend page, layout, or component | Visual — `references/visual-track.md` |
| "Does this state model, logic, or data shape feel right?" — state machine, reducer, API shape | Logic — `references/logic-track.md` |

Ambiguous: pages/components → Visual; states/data → Logic; say which.

## Rules for every round

- One topic per turn (up to 3 questions only as facets of one decision), as an inline numbered menu with a recommendation.
- A prototype is a markdown page of `ui` statements (components: `varde learn docs blocks`).
- Its static export (`varde learn docs build <page> --out <export>.html`) is delivered on disk. Its path is reported first after every write.
- A prototype that needs live behavior (state, network, scripts) is a real app.
- Plan and build a real app as normal project work, not a loose HTML page. Tell the user this when the request needs it.
- `<storage>` is `<working>/prototypes/<slug>/` (kebab-case slug), or `<working>/plans/<plan-id>/prototypes/<slug>/` when a plan owns the work; it is stated before the first write. `<working>` comes from `varde setup paths --json`, never guessed.
- On close, the final file path and key decisions are reported (Logic: the module to lift). When the user asked to plan or build, that route starts in the same turn; otherwise it is offered.
