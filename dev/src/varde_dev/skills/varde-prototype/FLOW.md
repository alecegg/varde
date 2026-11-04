# varde-prototype flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~447 tok; routes: Shape, prototype, or refine a frontend page, layout, or c..., "Does this state model, logic, or data shape feel right?"...)
  - references/logic-track.md (~229 tok; routes: "Does this state model, logic, or data shape feel right?"...)
  - references/visual-track.md (~356 tok; routes: Shape, prototype, or refine a frontend page, layout, or c...)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Shape, prototype, or refine a frontend page, layout, or c... | ~803 | ~803 | ~803 | ~803 | - | 0 | references/visual-track.md |
| "Does this state model, logic, or data shape feel right?"... | ~676 | ~676 | ~676 | ~676 | - | 0 | references/logic-track.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-prototype/browser-iteration | ~145 |
| varde-prototype/logic-page | ~232 |
| varde-prototype/storage-and-close | ~231 |
| varde-prototype/visual-build-check | ~183 |
| varde-prototype/visual-understand | ~187 |
| varde-prototype/visual-variants | ~188 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 1 (Shape, prototype, or refine a frontend page, layout, or c...) | <= 15 | ok |

## Findings

- single caller: references/logic-track.md <- SKILL.md: "Does this state model, logic, or data shape feel right?"...
- single caller: references/visual-track.md <- SKILL.md: Shape, prototype, or refine a frontend page, layout, or c...
