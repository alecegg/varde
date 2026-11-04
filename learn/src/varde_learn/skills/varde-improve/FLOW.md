# varde-improve flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~413 tok; routes: Distill recurring friction into an approved improvement, Review recurring friction for an improvement proposal)
  - references/distill.md (~618 tok; routes: Distill recurring friction into an approved improvement)
  - references/improve.md (~286 tok; routes: Review recurring friction for an improvement proposal)
  - references/options.md (~238 tok; routes: Distill recurring friction into an approved improvement, Review recurring friction for an improvement proposal)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Distill recurring friction into an approved improvement | ~1269 | ~1269 | ~1269 | ~1269 | - | 0 | references/distill.md, references/options.md |
| Review recurring friction for an improvement proposal | ~937 | ~937 | ~937 | ~937 | - | 0 | references/improve.md, references/options.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-improve/distill-apply | ~216 |
| varde-improve/distill-steps | ~256 |
| varde-improve/evals-calibrate | ~197 |
| varde-improve/evals-compare | ~228 |
| varde-improve/evals-grade | ~169 |
| varde-improve/evals-run | ~194 |
| varde-improve/evals-trigger | ~208 |
| varde-improve/evals | ~320 |
| varde-improve/improve-steps | ~204 |
| varde-improve/loop-baseline | ~283 |
| varde-improve/loop-decide | ~244 |
| varde-improve/loop-propose | ~302 |
| varde-improve/loop | ~262 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 1 (references/improve.md) | < 6 | ok |
| Average links per linking file | 1.0 (2 links, 2 files) | <= 2 | ok |
| Cross-module edges | 2 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 2 (Distill recurring friction into an approved improvement) | <= 15 | ok |

## Findings

- single caller: references/distill.md <- SKILL.md: Distill recurring friction into an approved improvement
- single caller: references/improve.md <- SKILL.md: Review recurring friction for an improvement proposal
