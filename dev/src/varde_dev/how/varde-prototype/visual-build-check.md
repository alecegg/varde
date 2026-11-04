---
topic: varde-prototype/visual-build-check
version: 1
summary: Build a revision and run the design check after each write
---

- Artifact: a `ui`-statement page and its `varde learn docs build` export. No script, framework, external asset or hand-written HTML.
- Revisions: saved revisions stay unchanged; each refinement writes the next `v<N>.md` and its export. When the direction is clear, make the focused refinement and state the assumption; otherwise ask per the round rules.
- Check: `varde learn check <page>`, then, when `varde design --help` succeeds, run `varde design check --json <export>`.
- Exit 2 means `fail` findings: fix them. Report `warn` findings without blocking, and report exit 1 (a tier did not run).
