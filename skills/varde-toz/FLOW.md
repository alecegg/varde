# varde-toz flow

Generated for human readers; agents do not load this file. Regenerate
with skill-flow.py --write from varde-agent-doc-authoring. Dotted edges
are conditional loads; min tokens follow only solid edges. Thick edges
are hand-offs to a later stage, outside min and max. Double-bordered
nodes are skill modes run inline or agent dispatches. Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch. Module overview first, then one diagram per module.

## Files

- SKILL.md (~842 tok; routes: Run a batch script)
  - references/troubleshooting.md (~381 tok; routes: Run a batch script)

```mermaid
flowchart TD
  m0["troubleshooting (1 file)"]
```

### troubleshooting

```mermaid
flowchart TD
  n0["references/troubleshooting.md (~381 tok)"]
```

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Run a batch script | ~842 | ~1223 | ~842 | ~1223 | - | 0 | references/troubleshooting.md |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Diagram edges | 1 | <= 60 | ok |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 1 (Run a batch script) | <= 15 | ok |

## Findings

- single caller: references/troubleshooting.md <- SKILL.md: Run a batch script
