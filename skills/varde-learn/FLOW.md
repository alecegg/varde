# varde-learn flow

Generated for human readers; agents do not load this file. Regenerate
with skill-flow.py --write from varde-agent-doc-authoring. Dotted edges
are conditional loads; min tokens follow only solid edges. Thick edges
are hand-offs to a later stage, outside min and max. Double-bordered
nodes are skill modes run inline or agent dispatches. Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch. Module overview first, then one diagram per module.

## Files

- SKILL.md (~360 tok; routes: Capture an observed friction event, Triage supplied agent-session evidence without a session-..., Diagnose an existing or current agent session, Reconcile an item against evidence, Distill recurring friction into an improvement, Check whether an adopted change recurred, Author query sets or eval cases, or run an approved evalu...)
  - references/capture.md (~322 tok; routes: Capture an observed friction event)
  - references/diagnose.md (~910 tok; routes: Diagnose an existing or current agent session)
    - references/diagnose-capture.md (~503 tok; routes: Diagnose an existing or current agent session)
    - references/diagnose-current.md (~616 tok; routes: Diagnose an existing or current agent session)
    - references/diagnose-quick.md (~206 tok; routes: Triage supplied agent-session evidence without a session-...)
    - references/diagnose-toz.md (~341 tok; routes: Diagnose an existing or current agent session)
  - references/distill.md (~585 tok; routes: Distill recurring friction into an improvement)
  - references/evals.md (~729 tok; routes: Distill recurring friction into an improvement, Author query sets or eval cases, or run an approved evalu...)
  - references/reconcile.md (~340 tok; routes: Reconcile an item against evidence)
  - references/recurrence.md (~186 tok; routes: Check whether an adopted change recurred)

```mermaid
flowchart TD
  m0["capture (1 file)"]
  m1["diagnose (5 files)"]
  m2["distill (1 file)"]
  m3["evals (1 file)"]
  m4["reconcile (1 file)"]
  m5["recurrence (1 file)"]
  m2 -->|"2"| m3
```

### capture

```mermaid
flowchart TD
  n0["references/capture.md (~322 tok)"]
```

### diagnose

```mermaid
flowchart TD
  n0["references/diagnose-capture.md (~503 tok)"]
  n1["references/diagnose-current.md (~616 tok)"]
  n2["references/diagnose-quick.md (~206 tok)"]
  n3["references/diagnose-toz.md (~341 tok)"]
  n4["references/diagnose.md (~910 tok)"]
  n4 --> n0
  n4 -.-> n1
  n4 -.-> n3
```

### distill

```mermaid
flowchart TD
  n0["references/distill.md (~585 tok)"]
  n1["evals"]
  n0 --> n1
```

### evals

```mermaid
flowchart TD
  n0["references/evals.md (~729 tok)"]
  n1["distill"]
  n1 --> n0
```

### reconcile

```mermaid
flowchart TD
  n0["references/reconcile.md (~340 tok)"]
```

### recurrence

```mermaid
flowchart TD
  n0["references/recurrence.md (~186 tok)"]
```

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Capture an observed friction event | ~682 | ~682 | ~682 | ~682 | - | 0 | references/capture.md |
| Triage supplied agent-session evidence without a session-... | ~566 | ~566 | ~566 | ~566 | - | 0 | references/diagnose-quick.md |
| Diagnose an existing or current agent session | ~1773 | ~2730 | ~1773 | ~2730 | - | 0 | references/diagnose.md, references/diagnose-current.md, references/diagnose-toz.md, references/diagnose-capture.md |
| Reconcile an item against evidence | ~700 | ~700 | ~700 | ~700 | - | 0 | references/reconcile.md |
| Distill recurring friction into an improvement | ~1674 | ~1674 | ~4340 | ~5774 | review ~3406, review ~4749-7624 | 0 | references/distill.md, references/evals.md |
| Check whether an adopted change recurred | ~546 | ~546 | ~546 | ~546 | - | 0 | references/recurrence.md |
| Author query sets or eval cases, or run an approved evalu... | ~1089 | ~1089 | ~1089 | ~1089 | - | 0 | references/evals.md |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 3 (references/diagnose.md) | < 6 | ok |
| Average links per linking file | 2.0 (4 links, 2 files) | <= 2 | ok |
| Cross-module edges | 1 | - | - |
| Diagram edges | 14 | <= 60 | ok |
| Max route cyclomatic | 4 | <= 10 | ok |
| Max route cognitive | 7 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 4 (Diagnose an existing or current agent session) | <= 15 | ok |

## Findings

- chain: references/diagnose-capture.md <- references/diagnose.md
- single caller: references/capture.md <- SKILL.md: Capture an observed friction event
- single caller: references/diagnose-current.md <- references/diagnose.md
- single caller: references/diagnose-quick.md <- SKILL.md: Triage supplied agent-session evidence without a session-...
- single caller: references/diagnose-toz.md <- references/diagnose.md
- single caller: references/diagnose.md <- SKILL.md: Diagnose an existing or current agent session
- single caller: references/distill.md <- SKILL.md: Distill recurring friction into an improvement
- single caller: references/reconcile.md <- SKILL.md: Reconcile an item against evidence
- single caller: references/recurrence.md <- SKILL.md: Check whether an adopted change recurred
- shared: references/evals.md <- SKILL.md: Author query sets or eval cases, or run an approved evalu...; references/distill.md
