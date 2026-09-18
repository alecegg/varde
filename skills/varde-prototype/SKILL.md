---
name: varde-prototype
description: "Build a throwaway prototype to answer a design question collaboratively — a visual mockup of a page or component, or a logic walkthrough of a state model or data shape. Not for production implementation."
compatibility: "Requires bash and POSIX tools (mkdir, cp, mv). For rich preview, the harness should support Artifact or mcp__visualize."
---

# Prototype a design question

## Pick the track

| The question is | Track |
|---|---|
| "What should this look like?" — a page, layout, or component's visual treatment | Visual — `references/VISUAL-TRACK.md` |
| "Does this state model, logic, or data shape feel right?" — state machine, reducer, API shape | Logic — `references/LOGIC-TRACK.md` |

When the track is genuinely ambiguous and the user isn't reachable, default to
Visual for a page, screen, or component and Logic for states, transitions, or
data — and state the assumption at the top of your first response.

## Rules for every round

- Ask one question per turn, inline in your message text as a numbered menu with
  your recommended answer. Your own text keeps the question and its answer
  together in one readable record, which a harness question tool renders outside.
- Answer from project context where you can: grep for the likely file (design
  tokens, component library, existing styles) and read it before falling back to
  a conventional `styles/` or `design-system/` directory.
- Delivery is always a plain HTML file on disk, with its path reported first.
  Rich preview is an addition to that, never a replacement.
- The session ends only after a closing confirmation question gets an
  affirmative answer.

## Workflow

1. **Establish context and agree on a slug.** Ask what the user wants to
   prototype, unless a plan already supplies the context and feature description
   — then use those directly. Agree a kebab-case `<slug>` and present the
   resolved storage path: `cwd/memory-bank/working/prototypes/<slug>/`, or
   `cwd/memory-bank/working/plans/<plan-id>/prototypes/<slug>/` when a plan owns
   the work. If that path exists, confirm overwrite versus a new slug.
2. **Classify the question before building.** A narrow question has a few close
   variants on one shared shape — build 2–3. A wide question has no shared shape
   — start with 3–5 distinct approaches. State the choice and target count, and
   move on unless the user disputes it.
3. **Detect preview tooling.** Before the first mockup round, use ToolSearch to
   check the deferred-tools list for `Artifact` or `mcp__visualize`. Found, it
   becomes a bonus preview alongside the file path; absent, the file path is the
   whole delivery. This is a silent check — tool availability is yours to
   determine, and worth reporting only if it changes the workflow.
4. **Run the track-specific round loop.** Full procedure:
   `references/VISUAL-TRACK.md` or `references/LOGIC-TRACK.md`.
5. **Close the session.** Full procedure: `references/CLOSE.md`.
6. **Record lessons.** Invoke `varde-knowledge reflect`, scoped to this run. It
   records friction and saves durable lessons, and writes no handoff.

## Gotchas

- Cap variants at 5 — past that they stop being radically different options and
  start being noise. Default to 3.
- Past 8 Visual-track iterations without convergence, suggest pausing and
  narrowing scope rather than grinding more rounds.
- A user's hybrid pick ("the header from B with the sidebar from C") is the real
  answer, not a tie to break — seed `v1.html` from it as the actual direction.
- Everything here is throwaway. Plans, tasks, and production code belong to
  `varde-change plan` and `varde-change build`; on close, the Decisions Store and
  plan files stay untouched.
- Keep the Logic track's module pure — no DOM, no button handlers — so it can
  move into production code as-is.
