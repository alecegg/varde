---
topic: varde-review-ui/tile-review-steps
version: 1
summary: Seeded runner, preflight, tile capture and route sampling for the UX advocate audit
---

## UX advocate steps

1. Start `node scripts/ux-seed-runner.mjs <repo-root>`; use its printed `URL:` and run its printed `Teardown:` command when the review ends. Read `runner/docs/ui-ux-standards.md` first.
2. Run `scripts/ux-preflight.mjs <scratch-url>` before review.
3. Run `node scripts/ux-tile-shots.mjs <URL> <dir>` at 390x844 and 1280x800, in light and dark. Inspect each tile as a first-time user.
4. Sample one representative per route template: `/plans/<id>`, `/threads/<id>`, `/roles/<id>`, every settings section linked from settings navigation (including subpages), and Needs-you items. Check `runner/ui/src/routes` for every page route template.
