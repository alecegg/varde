# varde-explain flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~343 tok; routes: Answer in chat, Write a page)
  - references/page.md (~152 tok; routes: Write a page)
  - references/varde-code-cli.md (~54 tok; routes: Answer in chat)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Answer in chat | ~397 | ~397 | ~397 | ~397 | - | 0 | references/varde-code-cli.md |
| Write a page | ~343 | ~495 | ~343 | ~495 | - | 0 | references/page.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-explain/read-sources | ~99 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 1 (Answer in chat) | <= 15 | ok |

## Findings

- single caller: references/page.md <- SKILL.md: Write a page
