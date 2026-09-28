---
name: varde-prototype
description: "Build a throwaway HTML prototype to answer a design question — a visual mockup, or a clickable walkthrough of a state model or data shape. Not for comparing options in chat."
---

# Prototype a design question

Before implementation edits, apply `references/review-gates.md`. Carry its
verdict through execution and completion, including changes made by this skill.

## Pick the track

| The question is | Track |
|---|---|
| "What should this look like?" — a page, layout, or component's visual treatment | Visual — `references/visual-track.md` |
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
3. **Close when the user is done.** Report the final file path and key
   decisions. For Logic, name the validated module to hand to `varde-change`;
   the page shell is disposable.
4. **Record lessons.** Record real obstacles through `varde-learn` and durable
   decisions through `varde-knowledge`; otherwise skip.

## Gotchas

- `<working>` (local, uncommitted) and `<knowledge>` (committed): resolve once
  before first use with `varde-workflow paths --json`; use its absolute
  `data.working`/`data.knowledge` paths for this session and pass them to
  subagents. If the command fails, retry it once with escalated access; if it
  still fails, ask the user for the paths. Do not guess storage paths. A
  location outside the repo skips git ops (`check-ignore`, `mv`, `status`);
  use plain file ops.
- Prototype files are throwaway. If the user explicitly asks to plan or build
  afterward, start the matching `varde-change` route in the same turn without
  reconfirming the request. Settled work uses bounded build; unresolved choices
  follow the plan's own approval gates. Otherwise, offer the next step and wait.
