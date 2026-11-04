# varde-doc-authoring flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~152 tok; routes: Write or revise an agent document)
  - references/conditions.md (~111 tok; routes: Write or revise an agent document)
  - references/criteria.md (~550 tok; routes: Write or revise an agent document)
  - references/outcome.md (~131 tok; routes: Write or revise an agent document)
  - references/sentence-style.md (~82 tok; routes: Write or revise an agent document)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Write or revise an agent document | ~1026 | ~1026 | ~1026 | ~1026 | - | 0 | references/outcome.md, references/conditions.md, references/criteria.md, references/sentence-style.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-doc-authoring/cut-order | ~221 |
| varde-doc-authoring/gather-evidence | ~149 |
| varde-doc-authoring/review-fix-list | ~252 |
| varde-doc-authoring/review-scope | ~202 |
| varde-doc-authoring/review | ~195 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 4 (Write or revise an agent document) | <= 15 | ok |

## Findings

- single caller: references/conditions.md <- SKILL.md: Write or revise an agent document
- single caller: references/criteria.md <- SKILL.md: Write or revise an agent document
- single caller: references/outcome.md <- SKILL.md: Write or revise an agent document
