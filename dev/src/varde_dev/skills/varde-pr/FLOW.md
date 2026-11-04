# varde-pr flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~417 tok; routes: 4. Write and validate the body)
  - references/template.md (~196 tok; routes: 4. Write and validate the body)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| 4. Write and validate the body | ~613 | ~613 | ~613 | ~613 | - | 0 | references/template.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-pr/gather-evidence | ~85 |
| varde-pr/gather-facts | ~125 |
| varde-pr/repo-map | ~95 |
| varde-pr/resolve-range | ~101 |
| varde-pr/save-and-publish | ~164 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 1 (4. Write and validate the body) | <= 15 | ok |

## Findings

- single caller: references/template.md <- SKILL.md: 4. Write and validate the body
- unreferenced: scripts/pr-facts.py
