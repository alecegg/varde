# Visual Track

For the Visual track, determine whether the prototype needs any interactive behavior (animations, transitions, state changes) beyond static layout — limit interactivity to the minimum needed for user-agent alignment.

## Round 1 — Variants

Before the Propose/Show/Ask/Revise loop, make variants so the user can compare
options side by side. Skip variants only when the user already gave a specific
direction. Then start the loop below.

1. **Pick N.** Default to 3 variants; cap at 5 (see Gotchas).
2. **Generate N different variants.** Change layout, information hierarchy, and
   primary action, not just colors or copy. If two drafts are too similar,
   redo one. Write each as a full-page mockup.
3. **Bake an identical switcher bar into every variant file** — a small fixed-position link bar (e.g. bottom-center) listing all N variants, linking to each sibling file by real `<a href="variant-b.html">` navigation (no JavaScript needed — this is plain HTML, consistent with the static-mockup rule). Opening any variant is a true full-page view; clicking a link is a real navigation to the next full-page view, not an embedded/scaled preview.
4. **Show the first variant's path** (e.g. `variant-a.html`) as the round's entry point, plus an Artifact/mcp__visualize preview of that file if detected — same delivery convention as every other round. Tell the user the in-page switcher bar lets them flip through the rest at full fidelity.
5. **Ask the user to pick** a winner, or a hybrid (see Gotchas).
6. **Seed `v1.html`** from the winning variant (copy it, applying any hybrid instructions the user gave) and continue into the Propose/Show/Ask/Revise loop below for refinement. Leave the variant files in place for reference; only `v<N>.html` files are the canonical iteration line going forward.

## Propose, Show, Ask, Revise

Run each round as this exact sequence:

1. **Propose.** Describe the visual direction — layout, color scheme, component placement. Wait for the user to agree or redirect before writing code.
2. **Write.** Create or update the mockup file at `<storage>/v<N>.html`. Use CSS for layout and styling; limit interactivity (JavaScript) to what was agreed. Link to a shared `style.css` from a previous round if one exists.
3. **Show.** Report the file path. If Artifact or mcp__visualize was detected, also present a preview via that tool.
4. **Ask.** Ask one targeted question about what to change. State your recommended next action, then ask if the user agrees.
5. **Revise.** On user direction, increment `N` and repeat (see Gotchas for the iteration-count ceiling).

Each round increments `N` (v1.html, v2.html, ...). Update `README.md` after each round to point to the latest version.

See `PROTOTYPE-FORMAT.md` for the full file naming and structure conventions.
