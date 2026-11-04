# varde-build flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~354 tok; routes: Settled standalone change, Diagnose without fixing, Refactor with preserved behavior, Fix a named bug)
  - references/TASK-TEMPLATE.md (~222 tok; routes: Settled standalone change)
  - references/build-execution.md (~193 tok; routes: Settled standalone change, Diagnose without fixing, Refactor with preserved behavior, Fix a named bug)
  - references/build-micro-change.md (~166 tok; routes: Settled standalone change)
  - references/build-posture-debug.md (~436 tok; routes: Diagnose without fixing, Fix a named bug)
  - references/build-posture-refactor.md (~122 tok; routes: Refactor with preserved behavior)
  - references/review-gates.md (~408 tok; routes: Settled standalone change, Diagnose without fixing, Refactor with preserved behavior, Fix a named bug)
  - references/varde-workflow-cli.md (~215 tok; routes: Settled standalone change, Diagnose without fixing, Refactor with preserved behavior, Fix a named bug)
  - references/workflow-state.md (~98 tok; routes: Settled standalone change, Diagnose without fixing, Refactor with preserved behavior, Fix a named bug)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Settled standalone change | ~1343 | ~1656 | ~1343 | ~1656 | - | 0 | references/build-micro-change.md, references/TASK-TEMPLATE.md, references/build-execution.md, references/review-gates.md, references/varde-workflow-cli.md, references/workflow-state.md |
| Diagnose without fixing | ~1391 | ~1704 | ~1391 | ~1704 | - | 0 | references/build-posture-debug.md, references/build-execution.md, references/review-gates.md, references/varde-workflow-cli.md, references/workflow-state.md |
| Refactor with preserved behavior | ~1077 | ~1390 | ~1077 | ~1390 | - | 0 | references/build-posture-refactor.md, references/build-execution.md, references/review-gates.md, references/varde-workflow-cli.md, references/workflow-state.md |
| Fix a named bug | ~1391 | ~1704 | ~1391 | ~1704 | - | 0 | references/build-posture-debug.md, references/build-execution.md, references/review-gates.md, references/varde-workflow-cli.md, references/workflow-state.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-build/debug-loop | ~251 |
| varde-build/debug-no-repro | ~219 |
| varde-build/escalation-routes | ~244 |
| varde-build/measured-runs | ~108 |
| varde-build/mode-and-wrap-up | ~85 |
| varde-build/refactor-steps | ~84 |
| varde-build/scope-and-checks | ~172 |
| varde-build/shared-surface | ~66 |
| varde-build/stuck-attempts | ~76 |
| varde-build/verify-behavior | ~120 |
| varde-build/waiting-and-mail | ~87 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 6 (Settled standalone change) | <= 15 | ok |

## Findings

- single caller: references/build-execution.md <- SKILL.md: What the request needs
- single caller: references/build-micro-change.md <- SKILL.md: Settled standalone change
- single caller: references/build-posture-refactor.md <- SKILL.md: Refactor with preserved behavior
- shared: references/build-posture-debug.md <- SKILL.md: Diagnose without fixing; SKILL.md: Fix a named bug
- unreferenced: scripts/measure-writes.sh
