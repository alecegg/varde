# UX advocate mode

Review user-facing workflows end to end against a seeded scratch runner
(`scripts/ux-seed-runner.mjs`; use its printed `URL:` and run its printed
`Teardown:` command at the end). For varde-py mobile web, apply
`runner/docs/ui-ux-standards.md`. Port 8765 is never inspected or mutated.

## Fail-closed preflight

`scripts/ux-preflight.mjs <scratch-url>` passes before review. It verifies:

- WebKit iPhone and Chromium launch.
- The seeded scratch runner responds.
- Preflight screenshots are captured and opened for inspection.
- Browser interaction (one click) works.

A missing capability is reported as `BLOCKED`. Missing route evidence is
`INVALID`. Both are not approved or merge-ready.

## Review

Read `references/ux-personas.md` and use applicable personas. Write findings in the `references/report-format.md` format.

### Coverage

- Tiles come from `node scripts/ux-tile-shots.mjs <URL> <dir>` at 390x844 and 1280x800, in light and dark, each inspected as a first-time user.
- One representative per route template is sampled: `/plans/<id>`, `/threads/<id>`, `/roles/<id>`, every settings section linked from settings navigation (including subpages), and Needs-you items. The sample stays below 40; `routeLimitReached` makes coverage `INVALID`.
- Every page route template in `runner/ui/src/routes` is sampled or listed in `index.md` under `Excluded route templates` with a concrete reason; a missing template makes coverage `INVALID`.
- Timed-out tiles appear as `still loading` in `<dir>/index.md` and do not count as loaded evidence.
- At most eight tiles per page, omissions reported as `Truncated N tiles`. Each JPEG has a 1:2-2:1 aspect ratio, a long side no greater than 800 px, and a size no greater than 150 KB. The index reports unviewable tiles; the count is zero.
- One coverage row per index section, header `| Route | Viewport | Scheme | Tile files | What was seen |`; row count and filenames match the index and every tile filename and observation is listed.
- Notes judge header contents, control placement, control proportions, and symmetry. Each note is written from the tile itself, quotes visible text, and names the distinct content shown. No note is reused or generated from a route template.

### Loading, journeys, second pass

- `node scripts/ux-loading-capture.mjs <URL> <dir>` runs on each data view. Pop-in, layout shift, and empty-state flashes are recorded. `popoverOpenOnLoad: false` is confirmed for every page with `popoverTrigger: true` in `report.json`.
- Each journey's last reachable step is recorded: reorder the queue, edit a role, answer a Needs-you item, read a plan, comment on a plan.
- Every regression rule in `runner/docs/ui-ux-standards.md` is applied.
- A fresh agent given the screenshot directory and findings list returns only new defects, or `none` with the tiles checked. Each result is fixed or listed as open before reporting `0 open`.

## Report gate

Each route x viewport x theme is listed with its viewed screenshot path and
observation, citing the tile index with the required coverage table. Include:

- Loading results for every data view.
- Outcomes for all five journeys.
- Checklist results and the skeptical pass.

## Verdict

Missing route evidence means `INVALID`; `0 open` requires passed preflight,
complete tile inspection, and a resolved second pass. Verdict:
`APPROVED (0 open) | BLOCKED: <capability> | INVALID: <missing routes>`.
The review evidence is linked in the UI merge-ready note.
