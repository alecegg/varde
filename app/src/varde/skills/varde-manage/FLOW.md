# varde-manage flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~188 tok; routes: Install and configure)
  - references/setup.md (~785 tok; routes: Install and configure)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Install and configure | ~973 | ~973 | ~973 | ~973 | - | 0 | references/setup.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-manage/agent-models | ~165 |
| varde-manage/config-settings | ~221 |
| varde-manage/presets | ~261 |
| varde-manage/runner-commands | ~222 |
| varde-manage/sync-repo-map | ~181 |
| varde-manage/sync-scope | ~207 |
| varde-manage/sync-workflow | ~242 |
| varde-manage/working-memory-setup | ~285 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 1 (Install and configure) | <= 15 | ok |

## Findings

- single caller: references/setup.md <- SKILL.md: Install and configure
