# Frontend design track

- Context: inspect the project's design system and surrounding routes, and preserve them unless the user asks otherwise. Keep the surface in realistic page context and cover the states that affect the design.
- Direction: when the user gave a specific direction or is refining, write the next `v<N>.md` directly.
- Otherwise, when a real structural choice is unresolved, save 2-5 complete variant pages (default 3, state the count).
- Name variants `variant-<letter>.md`, each exported with `varde learn docs build`.
- A variant round ends before the first revision until the user selects a direction or hybrid.
- Artifact: a `ui`-statement page in `<storage>` (components: `varde learn docs blocks`) and its static export. No JavaScript and no hand-written HTML.
- Quality: the page system supplies readable contrast and labelled controls. Describe in prose the states and responsive behavior it cannot draw.
- Revisions: saved revisions stay unchanged; each refinement writes the next `v<N>.md` and its export.
- Check: `varde learn check <page>` after each write.
- Then, when `varde design --help` succeeds, run `varde design check --json <export>` on the export. Exit 2 means `fail` findings: fix them until none remain. Report `warn` findings, and report exit 1 (a tier did not run).
- Browser: use only a user-supplied URL or command, never a guessed one; report what could not be inspected.
