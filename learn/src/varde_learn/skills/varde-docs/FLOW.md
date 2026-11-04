# varde-docs flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~224 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no..., A generated domain specification under <knowledge>/specs/...)
  - references/refresh.md (~351 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no...)
  - references/review-gates.md (~408 tok; routes: -)
  - references/spec.md (~679 tok; routes: A generated domain specification under <knowledge>/specs/...)
    - references/spec-format.md (~812 tok; routes: A generated domain specification under <knowledge>/specs/...)
  - references/varde-code-cli.md (~54 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no..., A generated domain specification under <knowledge>/specs/...)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| User-facing: README.md, docs/*.md, CHANGELOGs, release no... | ~629 | ~629 | ~629 | ~629 | - | 0 | references/refresh.md, references/varde-code-cli.md |
| A generated domain specification under <knowledge>/specs/... | ~1769 | ~1769 | ~1769 | ~1769 | builder unresolved | 0 | references/spec.md, references/spec-format.md, references/varde-code-cli.md, scripts/source-hash.py |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-docs/docs-gotchas | ~104 |
| varde-docs/refresh-apply | ~182 |
| varde-docs/refresh-steps | ~298 |
| varde-docs/spec-architecture-status | ~139 |
| varde-docs/spec-architecture | ~221 |
| varde-docs/spec-delegation | ~124 |
| varde-docs/spec-finish | ~149 |
| varde-docs/spec-scoped-runs | ~148 |
| varde-docs/spec-steps | ~266 |
| varde-docs/spec-unclassified-paths | ~159 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 2 (references/spec.md) | < 6 | ok |
| Average links per linking file | 1.33 (4 links, 3 files) | <= 2 | ok |
| Cross-module edges | 3 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 4 (A generated domain specification under <knowledge>/specs/...) | <= 15 | ok |

## Findings

- chain: references/spec-format.md <- references/spec.md
- single caller: references/refresh.md <- SKILL.md: User-facing: README.md, docs/*.md, CHANGELOGs, release no...
- single caller: references/spec.md <- SKILL.md: A generated domain specification under <knowledge>/specs/...
