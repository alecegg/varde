# Logic Prototype File Format

## Location

The Logic track produces exactly one file under the Visual track's storage root:

- **Standalone invocation**: `<working>/prototypes/<slug>/logic.html`
- **Plan-invoked invocation**: `<working>/plans/<plan-id>/prototypes/<slug>/logic.html`

That one file, under that exact name, is the track's whole output — `v<N>.html`,
`variant-*.html`, `style.css`, and `README.md` belong to the Visual track, which
may share the same `<slug>` directory.

## Structure rules

`logic.html` must be one self-contained HTML document:

- Use valid `<!DOCTYPE html>`, `<html>`, `<head>`, and `<body>` elements. Use no
  external dependencies, including CDN links, web fonts, icon libraries, or
  bundlers. The file must open by double-click and survive being emailed or
  committed as-is.
- Include one `<script>` block with the **pure logic module** under test. Use a
  reducer, state machine, or pure functions. Keep the module pure so it can move
  into the real codebase after the question is answered. The page calls the
  module; the module never calls the page.
- Use the rest of the page as a thin shell. It renders current state, sends
  free-play button clicks to the module, and runs guided walkthroughs.

### Required sections, top to bottom

1. **Title and question** — Add one visible paragraph, not a code comment. Name
   the exact state model and question under test.
2. **Current-state panel** — Show the full relevant state as labelled fields. Do
   not use a raw `JSON.stringify` dump. Re-render after every action.
3. **Free-play buttons** — Add one always-available button per action. Dispatch
   each button directly into the pure module, then re-render state.
4. **Guided walkthroughs** — Add scenario tabs. Each tab needs a short,
   plain-language description of the situation and what to watch for. Add the
   ordered buttons for that scenario as real, clickable buttons, not a
   transcript. Opening a tab resets to a known initial state, so every run
   matches.

Use domain language for buttons, state fields, and scenario descriptions. A
A non-developer can use the file without help.

## Styling

Inline `<style>` only. Clean typography, generous spacing, one accent color. No animation, no visual flourish that competes with the state panel and the buttons for attention.

## Conventions

- Report the file path first after every write, as in the Visual track.
- When Artifact or `mcp__visualize` is available, use it only as an additional
  preview. Never make it the sole delivery.
- Edit `logic.html` in place with targeted edits across every
  Propose/Show/Ask/Revise round. Do not create separate iteration files. The
  working tree's history preserves changes if needed.
- On close, lift the validated module from the `<script>` block into the real
  codebase. Do not ship the surrounding page shell.
