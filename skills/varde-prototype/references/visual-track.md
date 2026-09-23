# Visual Track

For the Visual track, identify any interaction the prototype needs beyond static
layout, such as animations, transitions, or state changes. Add only the
interaction needed to confirm the design with the user.

## Round 1 — Variants

Before the Propose/Show/Ask/Revise loop, make variants so the user can compare
options side by side. Skip variants only when the user already gave a specific
direction. Then start the loop below.

1. **Pick N.** Default to 3 variants; cap at 5 (see Gotchas).
2. **Generate N different variants.** Change layout, information hierarchy, and
   primary action, not just colors or copy. If two drafts are too similar,
   redo one. Write each as a full-page mockup.
3. **Add the same switcher bar to every variant file.** Use a small fixed
   element, such as a bottom-center bar, listing all N variants. Link each
   sibling with real `<a href="variant-b.html">` navigation. Do not use
   JavaScript. Opening any variant must show a full page. Clicking a link must
   navigate to the next full page, not an embedded or scaled preview.
4. **Show the first variant's path** (for example, `variant-a.html`) as the
   round's entry point. Add an Artifact or `mcp__visualize` preview when
   detected, as in every other round. Tell the user that the switcher bar opens
   the other variants at full fidelity.
5. **Ask the user to pick** a winner, or a hybrid (see Gotchas).
6. **Seed `v1.html`** from the winning variant. Apply any hybrid instructions
   from the user. Then continue the Propose/Show/Ask/Revise loop below. Leave
   variant files in place for reference. Only `v<N>.html` files form the
   canonical iteration line.

## Propose, Show, Ask, Revise

Run each round as this exact sequence:

1. **Propose.** Describe the visual direction — layout, color scheme, component placement. Wait for the user to agree or redirect before writing code.
2. **Write.** Create or update the mockup file at `<storage>/v<N>.html`. Use CSS for layout and styling; limit interactivity (JavaScript) to what was agreed. Link to a shared `style.css` from a previous round if one exists.
3. **Show.** Report the file path. If Artifact or mcp__visualize was detected, also present a preview via that tool.
4. **Ask.** Ask one targeted question about what to change. State your recommended next action, then ask if the user agrees.
5. **Revise.** On user direction, increment `N` and repeat (see Gotchas for the iteration-count ceiling).

Each round increments `N` (v1.html, v2.html, ...). Update `README.md` after each round to point to the latest version.

See `prototype-format.md` for the full file naming and structure conventions.
