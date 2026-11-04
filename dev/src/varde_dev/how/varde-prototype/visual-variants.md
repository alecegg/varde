---
topic: varde-prototype/visual-variants
version: 1
summary: Produce 2-5 variant pages and stop for the user's choice
---

If the user gave a specific direction or is refining, write the next `v<N>.md` directly. Otherwise make variants only when a real structural choice is unresolved:

1. Pick 2-3 close directions or 3-5 substantially different directions; default to 3 and state the count.
2. Vary hierarchy, layout, and primary action; keep content and scope the same.
3. Save one complete page per direction as `variant-<letter>.md`, each exported with `varde learn docs build`.
4. Report the export paths and ask the user to select a direction or hybrid. Stop before writing the first revision; after selection, seed it from that direction.
