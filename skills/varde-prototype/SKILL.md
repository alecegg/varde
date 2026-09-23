---
name: varde-prototype
description: "Build a throwaway prototype to answer a design question collaboratively — a visual mockup of a page or component, or a logic walkthrough of a state model or data shape. Not for production implementation."
compatibility: "Requires bash and POSIX tools (mkdir, cp, mv). For rich preview, the harness should support Artifact or mcp__visualize."
---

# Prototype a design question

## Pick the track

| The question is | Track |
|---|---|
| "What should this look like?" — a page, layout, or component's visual treatment | Visual — `references/visual-track.md` |
| "Does this state model, logic, or data shape feel right?" — state machine, reducer, API shape | Logic — `references/logic-track.md` |

If the track is ambiguous and you cannot reach the user, use these defaults:
Visual for pages, screens, and components. Logic for states, transitions, and
data. State the assumption at the top of your first response.

## Rules for every round

- Paths written `<working>/…` and `<knowledge>/…` resolve per
  `references/memory-locations.md`. Read it before the first memory read or write.
- Ask one question per turn. Put it in your message as a numbered menu and mark
  your recommended answer. Keep the question and choices in your message;
  harness question tools render outside it.
- First inspect project context. Use `grep` to find likely files such as design
  tokens, component libraries, and existing styles. Read them before using a
  conventional `styles/` or `design-system/` directory.
- Delivery is always a plain HTML file on disk, with its path reported first.
  Rich preview is an addition to that, never a replacement.
- End only after the closing confirmation question gets an affirmative answer.

## Workflow

1. **Establish context and agree on a slug.** Ask what the user wants to
   prototype, unless a plan already supplies the context and feature description.
   Use the plan details directly in that case. Agree a kebab-case `<slug>` and
   present the resolved storage path:
   `<working>/prototypes/<slug>/`, or
   `<working>/plans/<plan-id>/prototypes/<slug>/` when a plan owns
   the work. If the path exists, confirm overwrite or a new slug.
2. **Classify the question before building.** A narrow question has a few close
   variants of one shape, so build 2–3. A wide question compares unrelated
   shapes, so start with 3–5 distinct approaches. State the choice and target
   count, then move on unless the user disputes it.
3. **Detect preview tooling.** Before the first mockup round, use ToolSearch to
   check the deferred-tools list for `Artifact` or `mcp__visualize`. If found,
   use it as a bonus preview alongside the file path. If absent, deliver only
   the file path. Keep this check silent. Report availability only when it
   changes the workflow.
4. **Run the track-specific round loop.** Full procedure:
   `references/visual-track.md` or `references/logic-track.md`.
5. **Close the session.** Full procedure: `references/close.md`.
6. **Record lessons.** Invoke `varde-knowledge reflect` for this run. It records
   friction and durable lessons. It writes no handoff.

## Gotchas

- Keep variants at five or fewer. More than five creates noise. Use three by
  default.
- If eight Visual-track iterations pass without user agreement, suggest pausing
  and narrowing scope.
- A user's hybrid pick ("the header from B with the sidebar from C") is the
  answer. Seed `v1.html` from that combined direction.
- Prototype files are throwaway. Use `varde-change plan` and `varde-change build`
  for plans, tasks, and production code. When closing, leave the Decisions Store
  and plan files untouched.
- Keep the Logic track's module pure. Use no DOM or button handlers. Then it can
  move into production code as-is.
