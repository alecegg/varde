# varde-docs flow

Generated for human readers; agents do not load this file. Regenerate
with `varde doc flow --write`. Dotted edges
are conditional loads; min tokens follow only solid edges. Thick edges
are hand-offs to a later stage, outside min and max. Double-bordered
nodes are skill modes run inline or agent dispatches. Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch. Module overview first, then one diagram per module.

## Files

- SKILL.md (~234 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no..., A generated domain specification under <knowledge>/specs/...)
  - references/refresh.md (~459 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no...)
  - references/review-gates.md (~438 tok; routes: -)
  - references/spec.md (~1396 tok; routes: A generated domain specification under <knowledge>/specs/...)
    - references/spec-format.md (~814 tok; routes: A generated domain specification under <knowledge>/specs/...)
  - references/varde-code-cli.md (~54 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no..., A generated domain specification under <knowledge>/specs/...)

```mermaid
flowchart TD
  m0["refresh (1 file)"]
  m1["scripts (1 file)"]
  m2["spec (1 file)"]
  m2 -->|"3"| m1
```

### refresh

```mermaid
flowchart TD
  n0["references/refresh.md (~459 tok)<br/>ref: references/varde-code-cli.md (~54 tok)"]
```

### scripts

```mermaid
flowchart TD
  n0["scripts/source-hash.py"]
  n1["spec"]
  n1 --> n0
```

### spec

```mermaid
flowchart TD
  n0["references/spec.md (~1396 tok)<br/>ref: references/spec-format.md (~814 tok)<br/>ref: references/varde-code-cli.md (~54 tok)"]
  n1["scripts"]
  n0 --> n1
```

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| User-facing: README.md, docs/*.md, CHANGELOGs, release no... | ~747 | ~747 | ~747 | ~747 | - | 0 | references/refresh.md, references/varde-code-cli.md |
| A generated domain specification under <knowledge>/specs/... | ~2498 | ~2498 | ~2498 | ~2498 | builder ~2489-3856 | 1 | references/spec.md, references/spec-format.md, references/varde-code-cli.md, scripts/source-hash.py |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 2 (references/spec.md) | < 6 | ok |
| Average links per linking file | 1.33 (4 links, 3 files) | <= 2 | ok |
| Cross-module edges | 3 | - | - |
| Diagram edges | 9 | <= 60 | ok |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 4 (A generated domain specification under <knowledge>/specs/...) | <= 15 | ok |

## Findings

- chain: references/spec-format.md <- references/spec.md
- single caller: references/refresh.md <- SKILL.md: User-facing: README.md, docs/*.md, CHANGELOGs, release no...
- single caller: references/spec.md <- SKILL.md: A generated domain specification under <knowledge>/specs/...
