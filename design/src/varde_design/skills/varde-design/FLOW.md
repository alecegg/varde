# varde-design flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~419 tok; routes: Build a page well, Build a page well / step 2: Page type: the closest of references/..., Build a page well / step 4: The page has real data and every stat..., Build a page well / step 6: Critique per references/review.md; fi...)
  - references/craft.md (~225 tok; routes: Build a page well / step 4: The page has real data and every stat...)
  - references/floor.md (~408 tok; routes: Build a page well)
  - references/page-app.md (~210 tok; routes: Build a page well / step 2: Page type: the closest of references/...)
  - references/page-form.md (~239 tok; routes: Build a page well / step 2: Page type: the closest of references/...)
  - references/page-landing.md (~165 tok; routes: Build a page well / step 2: Page type: the closest of references/...)
  - references/page-read.md (~164 tok; routes: Build a page well / step 2: Page type: the closest of references/...)
  - references/review.md (~370 tok; routes: Build a page well / step 6: Critique per references/review.md; fi...)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Build a page well | ~827 | ~827 | ~827 | ~827 | - | 0 | references/floor.md |
| Build a page well / step 2: Page type: the closest of references/... | ~1197 | ~1197 | ~1197 | ~1197 | - | 0 | references/page-app.md, references/page-form.md, references/page-read.md, references/page-landing.md |
| Build a page well / step 4: The page has real data and every stat... | ~644 | ~644 | ~644 | ~644 | - | 0 | references/craft.md |
| Build a page well / step 6: Critique per references/review.md; fi... | ~789 | ~789 | ~789 | ~789 | review ~1091 | 0 | references/review.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-design/app-hierarchy | ~222 |
| varde-design/app-recipes | ~225 |
| varde-design/brief-and-discovery | ~215 |
| varde-design/craft-headline | ~208 |
| varde-design/craft-recipes | ~336 |
| varde-design/form-hierarchy | ~203 |
| varde-design/form-recipes | ~231 |
| varde-design/landing-hierarchy | ~227 |
| varde-design/landing-recipes | ~241 |
| varde-design/read-hierarchy | ~235 |
| varde-design/read-recipes | ~208 |
| varde-design/review-steps | ~148 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 4 (Build a page well / step 2: Page type: the closest of references/...) | <= 15 | ok |

## Findings

- single caller: references/craft.md <- SKILL.md: Build a page well / step 4: The page has real data and every stat...
- single caller: references/floor.md <- SKILL.md: Build a page well
- single caller: references/page-app.md <- SKILL.md: Build a page well / step 2: Page type: the closest of references/...
- single caller: references/page-form.md <- SKILL.md: Build a page well / step 2: Page type: the closest of references/...
- single caller: references/page-landing.md <- SKILL.md: Build a page well / step 2: Page type: the closest of references/...
- single caller: references/page-read.md <- SKILL.md: Build a page well / step 2: Page type: the closest of references/...
- single caller: references/review.md <- SKILL.md: Build a page well / step 6: Critique per references/review.md; fi...
