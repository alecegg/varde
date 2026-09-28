# Visual Track

Before the first mockup, grep the project for design tokens, component
libraries, and existing styles, and build from them; fall back to a
conventional `styles/` or `design-system/` directory only when none exist. Add
only the interaction (animation, transition, state change) needed to confirm
the design.

## Files

| File | Rules |
|---|---|
| `<storage>/variant-<a\|b\|c...>.html` | Round 1 only, one per structurally distinct direction. Keeps its name after `v1.html` is seeded. |
| `<storage>/v<N>.html` | The mockup for the current revision, starting at `v1.html` from the round-1 winner; each later revision writes the next `v<N>.html`. Earlier versions stay. |

Each mockup is a valid, self-contained HTML document with its CSS inlined in a
`<style>` tag, so earlier versions never change. A static mockup is plain HTML
and CSS; JavaScript and external dependencies (CDN links, web fonts, icon
libraries) need the user's explicit agreement.

## Round 1 — Variants

If the user already gave a specific direction, skip variants, write `v1.html`
from that direction, and continue with the rounds below.

1. **Pick N.** 2–3 close variants (narrow) or 3–5 unrelated shapes (wide);
   default 3, max 5; state N.
2. **Generate N different variants** as full-page mockups. Vary layout,
   information hierarchy, and primary action, not just colors or copy; redo a
   draft that is too similar.
3. **Add the same switcher bar to every variant**: a small fixed element, such
   as a bottom-center bar, with plain `<a href="variant-b.html">` links to
   every sibling and no JavaScript. Each variant opens as its own full page,
   never an embedded or scaled preview.
4. **Say** the switcher bar opens the others at full fidelity.
5. **Ask the user to pick** a winner or a hybrid ("the header from B with the
   sidebar from C"). End round 1 here; do not write `v1.html` before the user
   selects a direction.
6. **After the selection, seed `v1.html`** from the winner, applying any hybrid
   instructions, and continue with the rounds below.

## Rounds

Each round: ask one targeted question, then write `v<N+1>.html`.
