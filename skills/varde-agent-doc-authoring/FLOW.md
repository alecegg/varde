# varde-agent-doc-authoring flow

Generated for human readers; agents do not load this file. Regenerate
with skill-flow.py --write from varde-agent-doc-authoring. Dotted edges
are conditional loads; min tokens follow only solid edges. Thick edges
are hand-offs to a later stage, outside min and max. Double-bordered
nodes are skill modes run inline or agent dispatches. Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch. Module overview first, then one diagram per module.

## Files

- SKILL.md (~286 tok; routes: Author or revise a skill or agent document, Review a skill or agent document, Improve triggering)
  - references/author.md (~236 tok; routes: Author or revise a skill or agent document)
  - references/criteria.md (~1455 tok; routes: Author or revise a skill or agent document, Review a skill or agent document)
  - references/review.md (~549 tok; routes: Review a skill or agent document)
    - references/review-gate-plan.md (~508 tok; routes: Author or revise a skill or agent document, Review a skill or agent document, Improve triggering)
    - references/review-gate-record.md (~546 tok; routes: Review a skill or agent document)
    - references/review-gate-worktree.md (~469 tok; routes: Author or revise a skill or agent document, Review a skill or agent document, Improve triggering)
    - references/review-gates.md (~1352 tok; routes: Author or revise a skill or agent document, Review a skill or agent document, Improve triggering)
  - references/specification.md (~174 tok; routes: Author or revise a skill or agent document, Review a skill or agent document, Improve triggering)

```mermaid
flowchart TD
  m0["author (1 file)"]
  m1["review (5 files)"]
  m2["scripts (4 files)"]
  m0 -->|"3"| m2
  m1 -->|"6"| m2
```

### author

```mermaid
flowchart TD
  n0["references/author.md (~236 tok)<br/>ref: references/criteria.md (~1455 tok)<br/>ref: references/specification.md (~174 tok)"]
  n1["scripts"]
  n0 -.-> n1
```

### review

```mermaid
flowchart TD
  n0["references/review-gate-plan.md (~508 tok)"]
  n1["references/review-gate-record.md (~546 tok)"]
  n2["references/review-gate-worktree.md (~469 tok)"]
  n3["references/review-gates.md (~1352 tok)"]
  n4["references/review.md (~549 tok)<br/>ref: references/criteria.md (~1455 tok)<br/>ref: references/specification.md (~174 tok)"]
  n5["scripts"]
  n0 --> n5
  n3 -.-> n0
  n3 -.-> n2
  n3 --> n5
  n4 -.-> n1
  n4 --> n5
```

### scripts

```mermaid
flowchart TD
  n0["scripts/check-length.py"]
  n1["scripts/risk-tier.py"]
  n2["scripts/skill-flow.py"]
  n3["scripts/validate-frontmatter.py"]
  n4["author"]
  n5["review"]
  n4 -.-> n0
  n4 -.-> n2
  n4 --> n3
  n5 --> n1
  n5 --> n0
  n5 --> n2
  n5 -.-> n3
```

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Author or revise a skill or agent document | ~2151 | ~4480 | ~2151 | ~4480 | review* ~3406, review* ~4749-7624 | 0 | references/author.md, references/review-gates.md, references/criteria.md, references/specification.md, scripts/validate-frontmatter.py, scripts/check-length.py, scripts/skill-flow.py, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |
| Review a skill or agent document | ~2290 | ~5339 | ~2290 | ~5339 | review* ~3406, review* ~4749-7624 | 1 | references/review.md, references/review-gates.md, references/review-gate-record.md, references/criteria.md, references/specification.md, scripts/validate-frontmatter.py, scripts/check-length.py, scripts/skill-flow.py, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |
| Improve triggering | ~460 | ~2789 | ~460 | ~2789 | review* ~3406, review* ~4749-7624 | 0 | references/specification.md, references/review-gates.md, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 6 (references/review.md) | < 6 | warning |
| Average links per linking file | 3.75 (15 links, 4 files) | <= 2 | warning |
| Cross-module edges | 12 | - | - |
| Diagram edges | 27 | <= 60 | ok |
| Max route cyclomatic | 6 | <= 10 | ok |
| Max route cognitive | 11 | <= 10 warn, <= 15 error | warning |
| Most files reached by one route | 11 (Review a skill or agent document) | <= 15 | ok |

- fan-out: references/review.md (6 links out, target < 6)
- density: average 3.75 links per linking file (target <= 2)

## Findings

- single caller: references/author.md <- SKILL.md: Author or revise a skill or agent document
- single caller: references/review.md <- SKILL.md: Review a skill or agent document
- shared: references/criteria.md <- references/author.md; references/review.md
- shared: references/specification.md <- SKILL.md: Improve triggering; references/author.md; references/review.md
