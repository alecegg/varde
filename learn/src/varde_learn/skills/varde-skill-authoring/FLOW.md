# varde-skill-authoring flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~216 tok; routes: Write, trim, or rebuild a skill)
  - references/conditions.md (~307 tok; routes: Write, trim, or rebuild a skill)
  - references/criteria.md (~1463 tok; routes: Write, trim, or rebuild a skill)
  - references/outcome.md (~218 tok; routes: Write, trim, or rebuild a skill)
  - references/sentence-style.md (~82 tok; routes: Write, trim, or rebuild a skill)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Write, trim, or rebuild a skill | ~2286 | ~2286 | ~2286 | ~2286 | - | 0 | references/outcome.md, references/conditions.md, references/criteria.md, references/sentence-style.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-skill-authoring/classify-steps | ~240 |
| varde-skill-authoring/flow-ledger-generate | ~316 |
| varde-skill-authoring/flow-ledger-refresh | ~160 |
| varde-skill-authoring/flow-ledger | ~232 |
| varde-skill-authoring/gather-evidence | ~166 |
| varde-skill-authoring/improve-triggering | ~287 |
| varde-skill-authoring/optimize-items | ~272 |
| varde-skill-authoring/review-fix-list | ~281 |
| varde-skill-authoring/review-scope | ~324 |
| varde-skill-authoring/review | ~190 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 4 (Write, trim, or rebuild a skill) | <= 15 | ok |

## Findings

- single caller: references/conditions.md <- SKILL.md: Write, trim, or rebuild a skill
- single caller: references/criteria.md <- SKILL.md: Write, trim, or rebuild a skill
- single caller: references/outcome.md <- SKILL.md: Write, trim, or rebuild a skill
- unreferenced: assets/flow-ledger-prompt.md
