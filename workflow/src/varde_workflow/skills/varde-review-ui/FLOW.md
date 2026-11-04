# varde-review-ui flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~160 tok; routes: Inspect a running web, iOS simulator, or macOS app visual..., Audit a running dashboard UI from user personas and rank...)
  - references/report-format.md (~937 tok; routes: Inspect a running web, iOS simulator, or macOS app visual...)
  - references/ux-advocate.md (~874 tok; routes: Audit a running dashboard UI from user personas and rank...)
  - references/ux-personas.md (~430 tok; routes: Audit a running dashboard UI from user personas and rank...)
  - references/visual.md (~998 tok; routes: Inspect a running web, iOS simulator, or macOS app visual...)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Inspect a running web, iOS simulator, or macOS app visual... | ~2095 | ~2095 | ~2095 | ~2095 | - | 0 | references/visual.md, references/report-format.md, scripts/walk-mobile-ui.mjs |
| Audit a running dashboard UI from user personas and rank... | ~1464 | ~1464 | ~1464 | ~1464 | - | 0 | references/ux-advocate.md, scripts/ux-seed-runner.mjs, references/ux-personas.md, scripts/ux-loading-capture.mjs |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-review-ui/capture-tools | ~321 |
| varde-review-ui/gotchas | ~153 |
| varde-review-ui/persona-authoring | ~57 |
| varde-review-ui/platform-steps | ~323 |
| varde-review-ui/tile-review-steps | ~204 |
| varde-review-ui/tile-review-verdict | ~219 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 3 (references/ux-advocate.md) | < 6 | ok |
| Average links per linking file | 2.5 (5 links, 2 files) | <= 2 | warning |
| Cross-module edges | 4 | - | - |
| Max route cyclomatic | 2 | <= 10 | ok |
| Max route cognitive | 2 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 4 (Audit a running dashboard UI from user personas and rank...) | <= 15 | ok |

- density: average 2.5 links per linking file (target <= 2)

## Findings

- chain: references/ux-personas.md <- references/ux-advocate.md
- single caller: references/ux-advocate.md <- SKILL.md: Audit a running dashboard UI from user personas and rank...
- single caller: references/visual.md <- SKILL.md: Inspect a running web, iOS simulator, or macOS app visual...
- unreferenced: scripts/shot.sh
- unreferenced: scripts/ux-visual-helpers.mjs
- unreferenced: scripts/walk-mobile-ui-heuristics.mjs
