# varde-swarm flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~406 tok; routes: Report current work or an empty invocation, Select, order and launch plans, Relay, watch and keep notes, Progress reply to the user, A command was denied, Change a status)
  - references/main-agent.md (~358 tok; routes: Relay, watch and keep notes)
    - references/main-agent-replies.md (~78 tok; routes: Progress reply to the user)
  - references/orchestrate.md (~335 tok; routes: Select, order and launch plans)
  - references/status.md (~263 tok; routes: Report current work or an empty invocation)
  - references/varde-workflow-cli.md (~215 tok; routes: A command was denied)
  - references/workflow-state.md (~98 tok; routes: Change a status)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Report current work or an empty invocation | ~669 | ~669 | ~669 | ~669 | - | 0 | references/status.md |
| Select, order and launch plans | ~741 | ~741 | ~741 | ~741 | - | 0 | references/orchestrate.md |
| Relay, watch and keep notes | ~764 | ~764 | ~764 | ~764 | - | 0 | references/main-agent.md |
| Progress reply to the user | ~484 | ~484 | ~484 | ~484 | - | 0 | references/main-agent-replies.md |
| A command was denied | ~621 | ~621 | ~621 | ~621 | - | 0 | references/varde-workflow-cli.md |
| Change a status | ~504 | ~504 | ~504 | ~504 | - | 0 | references/workflow-state.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-swarm/launch-and-assign | ~256 |
| varde-swarm/orchestrator-handoff | ~262 |
| varde-swarm/relay-steps | ~239 |
| varde-swarm/select-plans | ~280 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 1 (Report current work or an empty invocation) | <= 15 | ok |

## Findings

- single caller: references/main-agent.md <- SKILL.md: Relay, watch and keep notes
- single caller: references/orchestrate.md <- SKILL.md: Select, order and launch plans
- single caller: references/status.md <- SKILL.md: Report current work or an empty invocation
- unreferenced: scripts/select-plans.py
