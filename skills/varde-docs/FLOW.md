# varde-docs flow

Generated for human readers; agents do not load this file. Regenerate
with skill-flow.py --write from varde-agent-doc-authoring. Dotted edges
are conditional loads; min tokens follow only solid edges. Thick edges
are hand-offs to a later stage, outside min and max. Double-bordered
nodes are skill modes run inline or agent dispatches. Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch. Module overview first, then one diagram per module.

## Files

- SKILL.md (~227 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no..., A generated domain specification under <knowledge>/specs/...)
  - references/refresh.md (~458 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no...)
  - references/review-gate-plan.md (~508 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no..., A generated domain specification under <knowledge>/specs/...)
  - references/review-gate-record.md (~546 tok; routes: -)
  - references/review-gate-worktree.md (~469 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no..., A generated domain specification under <knowledge>/specs/...)
  - references/review-gates.md (~1352 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no..., A generated domain specification under <knowledge>/specs/...)
  - references/spec.md (~1445 tok; routes: A generated domain specification under <knowledge>/specs/...)
    - references/spec-format.md (~813 tok; routes: A generated domain specification under <knowledge>/specs/...)
  - references/varde-code-cli.md (~46 tok; routes: User-facing: README.md, docs/*.md, CHANGELOGs, release no..., A generated domain specification under <knowledge>/specs/...)

```mermaid
flowchart TD
  m0["refresh (1 file)"]
  m1["review (4 files)"]
  m2["scripts (2 files)"]
  m3["spec (1 file)"]
  m1 -->|"2"| m2
  m3 -->|"3"| m2
```

### refresh

```mermaid
flowchart TD
  n0["references/refresh.md (~458 tok)<br/>ref: references/varde-code-cli.md (~46 tok)"]
```

### review

```mermaid
flowchart TD
  n0["references/review-gate-plan.md (~508 tok)"]
  n1["references/review-gate-record.md (~546 tok)"]
  n2["references/review-gate-worktree.md (~469 tok)"]
  n3["references/review-gates.md (~1352 tok)"]
  n4["scripts"]
  n0 --> n4
  n3 -.-> n0
  n3 -.-> n2
  n3 --> n4
```

### scripts

```mermaid
flowchart TD
  n0["scripts/risk-tier.py"]
  n1["scripts/source-hash.py"]
  n2["review"]
  n3["spec"]
  n2 --> n0
  n3 --> n1
```

### spec

```mermaid
flowchart TD
  n0["references/spec.md (~1445 tok)<br/>ref: references/spec-format.md (~813 tok)<br/>ref: references/varde-code-cli.md (~46 tok)"]
  n1["scripts"]
  n0 --> n1
```

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| User-facing: README.md, docs/*.md, CHANGELOGs, release no... | ~685 | ~3060 | ~685 | ~3060 | review* ~3406, review* ~4749-7624 | 1 | references/refresh.md, references/review-gates.md, references/varde-code-cli.md, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |
| A generated domain specification under <knowledge>/specs/... | ~2531 | ~4860 | ~2531 | ~4860 | executor ~3823-7625, review* ~3406, review* ~4749-7624 | 1 | references/spec.md, references/review-gates.md, references/spec-format.md, references/varde-code-cli.md, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py, scripts/source-hash.py |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 3 (references/review-gates.md) | < 6 | ok |
| Average links per linking file | 1.6 (8 links, 5 files) | <= 2 | ok |
| Cross-module edges | 5 | - | - |
| Diagram edges | 18 | <= 60 | ok |
| Max route cyclomatic | 4 | <= 10 | ok |
| Max route cognitive | 7 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 8 (A generated domain specification under <knowledge>/specs/...) | <= 15 | ok |

## Findings

- chain: references/spec-format.md <- references/spec.md
- single caller: references/refresh.md <- SKILL.md: User-facing: README.md, docs/*.md, CHANGELOGs, release no...
- single caller: references/spec.md <- SKILL.md: A generated domain specification under <knowledge>/specs/...
