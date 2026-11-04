---
topic: varde-review-ui/tile-review-verdict
version: 1
summary: Coverage rows, loading capture, journeys, fresh-agent pass and verdict for the UX audit
---

## UX advocate verdict steps

1. Add one coverage row per index section using the header `| Route | Viewport | Scheme | Tile files | What was seen |`. Judge header contents, control placement, control proportions and symmetry.
2. Run `node scripts/ux-loading-capture.mjs <URL> <dir>` on each data view.
3. Attempt each journey: reorder the queue, edit a role, answer a Needs-you item, read a plan, comment on a plan.
4. Give a fresh agent the screenshot directory and findings list; it returns only new defects, or `none` with the tiles checked.
5. The reviewer reports the verdict; orchestrator and main clear `BLOCKED` or `INVALID` after fixing the cause and rerunning affected evidence. Retry only after that.
