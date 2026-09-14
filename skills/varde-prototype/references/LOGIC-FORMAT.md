# Logic Prototype File Format

## Location

The Logic track produces exactly one file, at the same storage root the Visual track uses:

- **Standalone invocation**: `memory-bank/working/prototypes/<slug>/logic.html`
- **Plan-invoked invocation**: `memory-bank/working/plans/<plan-id>/prototypes/<slug>/logic.html`

No `v<N>.html` numbering, no `variant-*.html`, no shared `style.css`, no `README.md` — the single file is its own canonical pointer. If a prototype session decides mid-way that it also needs a Visual mockup (or vice versa), that's a second track in the same `<slug>` directory, not a rename of `logic.html`.

## Structure rules

`logic.html` must be a single, self-contained HTML document:

- Valid `<!DOCTYPE html>`, `<html>`, `<head>`, `<body>` — no external dependencies (CDN links, web fonts, icon libraries, bundlers). It opens by double-click and survives being emailed or committed as-is.
- One `<script>` block holding the **pure logic module** under test — a reducer, an explicit state machine, or a set of pure functions. This block must not reference `document`, touch the DOM, or contain button-handler code; it is called by the page, never the reverse. This is the part that lifts into the real codebase once the question is answered.
- The rest of the page is a thin shell over that module: rendering the current state, dispatching free-play button clicks into it, and driving guided-walkthrough scenarios.

### Required sections, top to bottom

1. **Title and question** — one visible paragraph (not a code comment) naming the exact state model and question this file exists to answer.
2. **Current-state panel** — the full relevant state as labelled fields (never a raw `JSON.stringify` dump), re-rendered after every action.
3. **Free-play buttons** — one per action, always available, dispatching directly into the pure module and re-rendering state.
4. **Guided walkthroughs** — a set of scenario tabs. Each tab: a short plain-language description of the situation and what to watch for, then the ordered buttons to press for that scenario as real, clickable buttons (not a transcript). Opening a tab resets to a known initial state so the scenario reproduces identically every run.

All labels — buttons, state fields, scenario descriptions — are in the domain's language, not the module's internal names, so a non-developer can drive the file unaided.

## Styling

Inline `<style>` only. Clean typography, generous spacing, one accent color. No animation, no visual flourish that competes with the state panel and the buttons for attention.

## Conventions

- Report the file path after every write, first — same as the Visual track.
- When Artifact or `mcp__visualize` is available, use it as an additive preview only, never as the sole delivery.
- Edit `logic.html` in place (a targeted edit, not a rewrite) across every Propose/Show/Ask/Revise round. There is no iteration history to retain in separate files — the working tree's own history covers that if needed.
- On close, the validated module (the reducer/machine/function set from the `<script>` block) is what gets lifted into the real codebase; the page shell around it does not ship.
