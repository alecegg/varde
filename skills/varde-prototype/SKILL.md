---
name: varde-prototype
description: >
  TRIGGER: Build a throwaway prototype to answer a visual or logic design
  question collaboratively. Use the visual mockup or logic walkthrough track.
  SKIP: Skip only when the user wants production implementation, planning, or
  review instead of an exploratory artifact.
  Example phrases: "what should this UI look like?" or "does this state model work?".
compatibility: "Requires bash and POSIX tools (mkdir, cp, mv). For rich preview, the harness should support Artifact or mcp__visualize."
---

**Question format.** Ask every question inline, in your message text, as a numbered menu with a stated recommendation — never via a harness's native question-prompt tool (e.g. Claude Code's `AskUserQuestion`), since that renders outside the continuous transcript and breaks the question/answer record.

## Entry point dispatch

| Invocation | Action |
|---|---|
| Standalone (no plan context) | Storage root: `cwd/memory-bank/working/prototypes/<slug>/`. Ask the user what to prototype. |
| `plan=<plan-id>` | Storage root: `cwd/memory-bank/working/plans/<plan-id>/prototypes/<slug>/`. Plan context and feature description are already known — use them directly. |
| "What should this look like?" (a page, layout, or component's visual treatment) | Visual track — `references/VISUAL-TRACK.md` |
| "Does this state model, logic, or data shape feel right?" (state machine, reducer, API shape) | Logic track — `references/LOGIC-TRACK.md` |

If the track is genuinely ambiguous and the user isn't reachable for a quick check, default to Visual for anything describing a page/screen/component and Logic for anything describing states/transitions/data, and state the assumption at the top of your first response.

## Workflow

1. **Follow the always-on cadence for every round, regardless of track.**
   a. Ask one question at a time, waiting for the user's response before asking the next.
   b. For each question, provide your recommended answer.
   c. Explore project context first when a question can be answered that way — use Grep/Glob to find a likely candidate file (design tokens, component library, existing styles) and Read it directly, before falling back to Glob/Read of a conventional `styles/`/`design-system/` directory.
   d. Delivery always produces a plain HTML file on disk and reports its path first; rich preview tools are additive enhancements only, never the sole delivery mechanism.
   e. Only end the session after an explicit closing confirmation question with an affirmative answer.
2. **Establish context, pick the track, and agree on a slug.** If invoked standalone, ask the user what they want to prototype; if invoked from `/varde-plan`, use the known plan context and feature description directly. Pick the track per the dispatch table above. Agree a kebab-case `<slug>` with the user, present the resolved storage path — and if that path already exists, say so and confirm overwrite vs. a new slug — before proceeding.
3. **Classify the design question as narrow or wide before building anything.** Narrow: the question has a small number of close variants on a shared shape (e.g. "should this button be top-right or inline?") — build 2-3 variants on one surface. Wide: the space is genuinely open with no obvious shared shape (e.g. "how should onboarding work?") — diverge first into 3-5 distinct mechanisms before narrowing. State the classification and its variant-count target at the start of the round loop; this is a cheap triage call, not a question to the user unless the classification itself is contested.
4. **Detect preview tooling.** Before the first mockup round, use ToolSearch to check the harness's deferred-tools list for `Artifact` or `mcp__visualize` — never ask the user about tool availability. If found, use it as a bonus preview alongside the file path; if not, the file path is the only delivery mechanism. Do not report this detection to the user unless it changes the workflow.
5. **Run the track-specific round loop.** Full procedure: `references/VISUAL-TRACK.md` (Visual track) or `references/LOGIC-TRACK.md` (Logic track).
6. **Close the session.** Full procedure: `references/CLOSE.md`.
7. **Reflect and consolidate.** Invoke `varde-reflect source=varde-prototype` — it
   captures friction scoped to this skill's own execution and harvests any durable
   knowledge the work produced (no handoff mid-session). If `varde-reflect` isn't
   installed, fall back to `varde-friction` with the same scope.

## Gotchas

- Cap variant count at 5 — more than that stops being radically different options and starts being noise; default to 3.
- If a Visual-track iteration count exceeds 8 without convergence, suggest pausing the session and narrowing scope rather than continuing to grind rounds.
- A user's hybrid pick ("the header from B with the sidebar from C") is the real answer, not a tie to break — treat it as the actual direction and seed `v1.html` from it.
- Do not create plans, write tasks, or implement production code in this skill — that belongs to `/varde-plan` and `/varde-build`. On close, do not write to the Decisions Store or modify plan files.
- The Logic track's pure module (reducer/state machine/function set) must never reach into the DOM or button handlers — that breaks the "lifts directly into the real codebase" property that makes the prototype worth doing.
