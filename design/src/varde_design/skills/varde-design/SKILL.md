---
name: varde-design
description: "Use this skill when the user wants a frontend page (app screen, form, reading page, landing page) built or refined so it reuses the project's own design system, passes the design check and survives a screenshot critique."
recommends: [varde-prototype, varde-review]
---

# Build a page well

Read `references/floor.md` before the first UI edit. If `varde design --help` fails, skip the survey and check and apply the floor by hand.

1. Brief: five lines before markup (user task, the one primary action, data fields, states, density) and the material available. Ask for missing facts once; show at most two as visible placeholders. Invent no figures, logos or quotes.
2. Page type: the closest of `references/page-app.md`, `references/page-form.md`, `references/page-read.md`, `references/page-landing.md`; a second only when its state rules apply.
3. Discovery: `varde design survey` finds the project's tokens, components and best pages, and the page reuses them. With none, say so and start from a neutral fallback with tokens written first.
4. The page has real data and every state rendered (empty, loading, error, populated, long). A first screen or marketing section also follows `references/craft.md`.
5. `varde design check <file> --static-only` shows no `fail`. `varde design check <file>` runs once per fix batch, at most 2 batches; a render tier `not run` is reported.
6. Critique per `references/review.md`; fixes land in one batch.
7. Report in at most 8 lines: the brief, what discovery found or the neutral fallback, checks run, warns left and why. Paste the six-line checklist from `review.md` verbatim as the last lines.
