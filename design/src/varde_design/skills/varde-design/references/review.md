# Review: user checklist and screenshot critique

## Six-line checklist (end of the report, for the user)
1. Primary action: is the one thing to do obvious in two seconds?
2. Hierarchy: do title, groups and details read in the right order?
3. Spacing and density: is related close, unrelated far, nothing cramped or empty by accident?
4. States: do empty, loading, error and long content look finished?
5. Feedback: do hover, focus, pressed and busy states respond?
6. Overall feel: would you ship it under your name?

## Screenshot critique pass
Runs after the checker passes, on PNGs at 390 and 1440 px for each state. With no harness browser tool or Playwright script, skip the pass and say so in the report.
- Spawn a fresh-context reviewer that did not build the page, sees screenshots only and gets no explanation of intent.
- If no subagent can be spawned, the report says the critique was self-review, not independent.
1. Capture validity first. A screenshot with a blank region, missing image, wrong width or content that does not match the brief: the first word is `recapture`; stop.
2. First word of the reply: `ship`, `fix` or `rebuild`. Then at most 5 findings, worst first, each: where, what the eye sees, one change.
3. The eye lands on the primary action first, then the main content. A page that could belong to a competitor with logo and nouns covered is a `no idea` finding.
Fixes land in one batch with one rerender; unresolved findings stay in the report.
