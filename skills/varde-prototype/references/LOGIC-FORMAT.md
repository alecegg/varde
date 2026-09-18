# Logic Prototype File Format

## Location

The Logic track produces exactly one file, at the same storage root the Visual track uses:

- **Standalone invocation**: `memory-bank/working/prototypes/<slug>/logic.html`
- **Plan-invoked invocation**: `memory-bank/working/plans/<plan-id>/prototypes/<slug>/logic.html`

That one file, under that exact name, is the track's whole output — `v<N>.html`,
`variant-*.html`, `style.css`, and `README.md` belong to the Visual track, which
may share the same `<slug>` directory.

## Structure rules

`logic.html` must be a single, self-contained HTML document:

- Valid `<!DOCTYPE html>`, `<html>`, `<head>`, `<body>` — no external dependencies (CDN links, web fonts, icon libraries, bundlers). It opens by double-click and survives being emailed or committed as-is.
- One `<script>` block with the **pure logic module** under test: a reducer,
  state machine, or pure functions, kept pure so it can move into the real
  codebase once the question is answered. The page calls it; it never calls the
  page.
- The rest of the page is a thin shell over that module: rendering the current state, dispatching free-play button clicks into it, and driving guided-walkthrough scenarios.

### Required sections, top to bottom

1. **Title and question** — one visible paragraph (not a code comment) naming the exact state model and question this file exists to answer.
2. **Current-state panel** — the full relevant state as labelled fields (never a raw `JSON.stringify` dump), re-rendered after every action.
3. **Free-play buttons** — one per action, always available, dispatching directly into the pure module and re-rendering state.
4. **Guided walkthroughs** — a set of scenario tabs. Each tab: a short plain-language description of the situation and what to watch for, then the ordered buttons to press for that scenario as real, clickable buttons (not a transcript). Opening a tab resets to a known initial state so the scenario reproduces identically every run.

Use domain language for buttons, state fields, and scenario descriptions. A
non-developer should be able to use the file unaided.

## Styling

Inline `<style>` only. Clean typography, generous spacing, one accent color. No animation, no visual flourish that competes with the state panel and the buttons for attention.

## Conventions

- Report the file path after every write, first — same as the Visual track.
- When Artifact or `mcp__visualize` is available, use it as an additive preview only, never as the sole delivery.
- Edit `logic.html` in place (a targeted edit, not a rewrite) across every Propose/Show/Ask/Revise round. There is no iteration history to retain in separate files — the working tree's own history covers that if needed.
- On close, the validated module (the reducer/machine/function set from the `<script>` block) is what gets lifted into the real codebase; the page shell around it does not ship.
