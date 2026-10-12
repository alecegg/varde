# varde-customize flow

Generated for human readers; agents do not load this file. Regenerate
with `varde doc flow --write`. Dotted edges
are conditional loads; min tokens follow only solid edges. Thick edges
are hand-offs to a later stage, outside min and max. Double-bordered
nodes are skill modes run inline or agent dispatches. Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch. Module overview first, then one diagram per module.

## Files

- SKILL.md (~313 tok; routes: Add a code scan rule or tune its matches, severity, or th..., Customize tool-output previews, sections, or extracted re...)
  - references/scan-author.md (~2066 tok; routes: Add a code scan rule or tune its matches, severity, or th...)
  - references/toz-profiles.md (~959 tok; routes: Customize tool-output previews, sections, or extracted re...)

```mermaid
flowchart TD
  m0["scan (1 file)"]
  m1["toz (1 file)"]
```

### scan

```mermaid
flowchart TD
  n0["references/scan-author.md (~2066 tok)"]
```

### toz

```mermaid
flowchart TD
  n0["references/toz-profiles.md (~959 tok)"]
```

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Add a code scan rule or tune its matches, severity, or th... | ~2379 | ~2379 | ~2379 | ~2379 | - | 0 | references/scan-author.md |
| Customize tool-output previews, sections, or extracted re... | ~1272 | ~1272 | ~1272 | ~1272 | - | 0 | references/toz-profiles.md |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Diagram edges | 2 | <= 60 | ok |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 1 (Add a code scan rule or tune its matches, severity, or th...) | <= 15 | ok |

## Findings

- single caller: references/scan-author.md <- SKILL.md: Add a code scan rule or tune its matches, severity, or th...
- single caller: references/toz-profiles.md <- SKILL.md: Customize tool-output previews, sections, or extracted re...
