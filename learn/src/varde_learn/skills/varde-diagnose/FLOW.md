# varde-diagnose flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~300 tok; routes: Triage supplied agent-session evidence without a session-..., Diagnose an existing or current agent session, Run a multi-session retrospective or orchestrated-build w..., Run a friction cycle over new sessions)
  - references/cycle.md (~260 tok; routes: Run a friction cycle over new sessions)
  - references/diagnose.md (~694 tok; routes: Diagnose an existing or current agent session)
    - references/diagnose-capture.md (~358 tok; routes: Diagnose an existing or current agent session)
    - references/diagnose-current.md (~497 tok; routes: Diagnose an existing or current agent session, Run a multi-session retrospective or orchestrated-build w..., Run a friction cycle over new sessions)
    - references/diagnose-quick.md (~232 tok; routes: Triage supplied agent-session evidence without a session-...)
    - references/diagnose-toz.md (~332 tok; routes: Diagnose an existing or current agent session)
  - references/options.md (~238 tok; routes: Triage supplied agent-session evidence without a session-..., Diagnose an existing or current agent session, Run a multi-session retrospective or orchestrated-build w..., Run a friction cycle over new sessions)
  - references/retro.md (~505 tok; routes: Run a multi-session retrospective or orchestrated-build w..., Run a friction cycle over new sessions)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Triage supplied agent-session evidence without a session-... | ~532 | ~770 | ~532 | ~770 | - | 1 | references/diagnose-quick.md, references/options.md |
| Diagnose an existing or current agent session | ~1352 | ~2419 | ~1352 | ~2419 | - | 2 | references/diagnose.md, references/diagnose-current.md, references/diagnose-toz.md, references/options.md, references/diagnose-capture.md |
| Run a multi-session retrospective or orchestrated-build w... | ~1043 | ~1540 | ~1043 | ~1540 | - | 1 | references/retro.md, references/options.md, references/diagnose-current.md |
| Run a friction cycle over new sessions | ~1303 | ~1800 | ~1303 | ~1800 | - | 1 | references/cycle.md, references/retro.md, references/options.md, references/diagnose-current.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-diagnose/capture-run | ~200 |
| varde-diagnose/capture-steps | ~206 |
| varde-diagnose/current-analyst | ~244 |
| varde-diagnose/current-steps | ~275 |
| varde-diagnose/cycle-steps | ~303 |
| varde-diagnose/diagnose-freeze | ~297 |
| varde-diagnose/diagnose-report | ~259 |
| varde-diagnose/diagnose-steps | ~217 |
| varde-diagnose/retro-analyze | ~216 |
| varde-diagnose/retro-steps | ~212 |
| varde-diagnose/retro-wrapup | ~253 |
| varde-diagnose/toz-route | ~194 |
| varde-diagnose/toz-steps | ~249 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 4 (references/diagnose.md) | < 6 | ok |
| Average links per linking file | 1.8 (9 links, 5 files) | <= 2 | ok |
| Cross-module edges | 6 | - | - |
| Max route cyclomatic | 3 | <= 10 | ok |
| Max route cognitive | 4 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 5 (Diagnose an existing or current agent session) | <= 15 | ok |

## Findings

- chain: references/diagnose-capture.md <- references/diagnose.md
- single caller: references/cycle.md <- SKILL.md: Run a friction cycle over new sessions
- single caller: references/diagnose-quick.md <- SKILL.md: Triage supplied agent-session evidence without a session-...
- single caller: references/diagnose-toz.md <- references/diagnose.md
- single caller: references/diagnose.md <- SKILL.md: Diagnose an existing or current agent session
- shared: references/diagnose-current.md <- references/diagnose.md; references/retro.md
- shared: references/retro.md <- SKILL.md: Run a multi-session retrospective or orchestrated-build w...; references/cycle.md
