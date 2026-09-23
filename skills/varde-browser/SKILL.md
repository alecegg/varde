---
name: varde-browser
description: "Validate a local or deployed web experience with read-only browser evidence, including visual, console, network, and accessibility checks. Use when browser validation is requested. Report degraded capability when supported tooling is absent."
---

# Validate browser behavior

Collect browser evidence without changing external systems.

## Workflow

1. **Define the target.** Record the URL, route, viewport, and requested checks.
   Read `references/validation.md` before collecting evidence.

2. **Check available tooling.** Run `scripts/detect-browser.sh` from this
   skill's directory. Use its `capability`, `tool`, `reason`, and `guidance`
   lines as the capability result.

3. **Collect read-only evidence.** If the probe reports
   `capability=available`, inspect the target without submitting forms,
   changing data, or authenticating. Record the exact checks, observed results,
   and artifact paths.

4. **Report degradation.** When the probe reports `capability=degraded`, state
   that browser evidence was not collected. Include the probe's `reason` and
   `guidance` lines. Do not present static inspection as browser validation.

5. **Summarize the result.** Separate passed checks, failed checks, and
   degraded checks. List each missing capability and the next safe step.

## Available scripts

- `scripts/detect-browser.sh` reports supported browser tooling on `PATH`.

## Gotchas

- This skill does not install browser tooling.
- Validation is report-only. External mutations need another authorized flow.
- A missing browser is a bounded degraded result, not a passing check.
