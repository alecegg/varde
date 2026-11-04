# varde-plan flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~260 tok; routes: Settle scope before implementation)
  - references/TASK-TEMPLATE.md (~222 tok; routes: Settle scope before implementation)
  - references/plan.md (~1071 tok; routes: Settle scope before implementation)
    - references/plan-decomposition.md (~438 tok; routes: Settle scope before implementation)
  - references/varde-code-cli.md (~54 tok; routes: Settle scope before implementation)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Settle scope before implementation | ~2626 | ~2626 | ~2626 | ~2626 | - | 0 | references/plan.md, references/plan-decomposition.md, assets/PLAN-TEMPLATE.md, references/TASK-TEMPLATE.md, references/varde-code-cli.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-plan/answer-sources | ~200 |
| varde-plan/decomposition-methods | ~237 |
| varde-plan/deferred-findings | ~85 |
| varde-plan/escalation-routes | ~57 |
| varde-plan/finalize-checks | ~148 |
| varde-plan/finalize-review | ~325 |
| varde-plan/interactive-page | ~156 |
| varde-plan/knowledge-and-consumers | ~128 |
| varde-plan/plan-set | ~156 |
| varde-plan/resume-plan | ~134 |
| varde-plan/setup-tools | ~182 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 2 (references/plan.md) | < 6 | ok |
| Average links per linking file | 1.5 (3 links, 2 files) | <= 2 | ok |
| Cross-module edges | 2 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 5 (Settle scope before implementation) | <= 15 | ok |

## Findings

- single caller: references/plan.md <- SKILL.md: Settle scope before implementation
- shared: references/plan-decomposition.md <- SKILL.md: Settle scope before implementation; references/plan.md
