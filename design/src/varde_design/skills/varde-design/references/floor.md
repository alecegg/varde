# Floor: rule IDs and neutral defaults

Read before editing a frontend page. Each rule line is a checker rule (`varde design check`, core profile) and the default that passes it. A project's own tokens override a default.

- S2: set headline text in one solid colour; no gradient fill through background-clip.
- S4: body text at least 16 px; nothing below 12 px, and UI labels at least 11 px.
- S5: `<html lang>`, a `<title>`, and a `width=device-width` viewport meta on every page.
- S6: every `<img>` has an `alt` (empty for decoration) and a source that loads.
- R1: text contrast 4.5:1 against its background, 3:1 for text 24 px, or 18 px bold, and larger.
- R2: no horizontal scroll at 390, 768 or 1440 px; let wide content wrap or scroll inside its own box.
- R3: buttons, links and inputs at least 44 px tall and wide at 390 px.
- R5: name a font that renders (system-ui stack by default); the first family declared is the one shown.
- R6: a clean console: no script, network or missing-asset errors on load.
- R8: reading paragraphs 45 to 75 characters per line (about 640 px wide at 20 px type).

Unchecked defaults: a 4 px spacing scale, 8 px radius, one accent colour, a 2 px focus ring, and visible empty, loading and error states.

Tiers: Gate = a `fail` finding, never waivable; Advisory = `warn`, waive with `design-ignore <id> reason: <24+ characters>`.

## Opinion rules

Rules (kicker labels, accent borders, colour literals, placeholder copy, spacing scale, motion, headline length, focus ring) run only with `--profile opinion`. No workflow step runs it, so page files list them as "Judgement (not checked)".
