# varde-customize flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~285 tok; routes: Add a code scan rule or tune its matches, severity, or th..., Customize tool-output previews, sections, or extracted re...)
  - references/scan-author.md (~537 tok; routes: Add a code scan rule or tune its matches, severity, or th...)
  - references/toz-profiles.md (~441 tok; routes: Customize tool-output previews, sections, or extracted re...)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Add a code scan rule or tune its matches, severity, or th... | ~822 | ~822 | ~822 | ~822 | - | 0 | references/scan-author.md |
| Customize tool-output previews, sections, or extracted re... | ~726 | ~726 | ~726 | ~726 | - | 0 | references/toz-profiles.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-customize/profile-deploy | ~283 |
| varde-customize/profile-fields | ~224 |
| varde-customize/profile-scripts | ~283 |
| varde-customize/profile-workflow | ~259 |
| varde-customize/rule-verification | ~266 |
| varde-customize/scan-rule-format | ~246 |
| varde-customize/scan-rule-patterns | ~253 |
| varde-customize/scan-rule-rewrite-fields | ~230 |
| varde-customize/scan-rule-tests | ~258 |
| varde-customize/scan-rule-validate | ~250 |
| varde-customize/scan-rule-workflow | ~333 |
| varde-customize/sql-rules | ~257 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 1 (Add a code scan rule or tune its matches, severity, or th...) | <= 15 | ok |

## Findings

- single caller: references/scan-author.md <- SKILL.md: Add a code scan rule or tune its matches, severity, or th...
- single caller: references/toz-profiles.md <- SKILL.md: Customize tool-output previews, sections, or extracted re...
