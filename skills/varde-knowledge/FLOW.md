# varde-knowledge flow

Generated for human readers; agents do not load this file. Regenerate
with skill-flow.py --write from varde-agent-doc-authoring. Dotted edges
are conditional loads; min tokens follow only solid edges. Thick edges
are hand-offs to a later stage, outside min and max. Double-bordered
nodes are skill modes run inline or agent dispatches. Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch. Module overview first, then one diagram per module.

## Files

- SKILL.md (~224 tok; routes: Find or record durable knowledge — a decision, pattern, d..., Wrap up finished work or capture what was learned, Write a handoff, Resume a handoff, or pick up where a previous session lef..., Check a knowledge note against current code)
  - references/concepts.md (~156 tok; routes: Find or record durable knowledge — a decision, pattern, d..., Wrap up finished work or capture what was learned)
  - references/handoff-resume.md (~410 tok; routes: Resume a handoff, or pick up where a previous session lef...)
  - references/handoff-snapshot.md (~60 tok; routes: Wrap up finished work or capture what was learned, Write a handoff, Resume a handoff, or pick up where a previous session lef...)
  - references/handoff-write.md (~633 tok; routes: Wrap up finished work or capture what was learned, Write a handoff)
  - references/note.md (~583 tok; routes: Find or record durable knowledge — a decision, pattern, d..., Wrap up finished work or capture what was learned)
  - references/reconcile.md (~95 tok; routes: Wrap up finished work or capture what was learned, Check a knowledge note against current code)
  - references/reflect.md (~343 tok; routes: Wrap up finished work or capture what was learned)
  - references/varde-workflow-cli.md (~230 tok; routes: Find or record durable knowledge — a decision, pattern, d..., Wrap up finished work or capture what was learned)

```mermaid
flowchart TD
  m0["concepts (1 file)"]
  m1["handoff (3 files)"]
  m2["note (1 file)"]
  m3["reconcile (1 file)"]
  m4["reflect (1 file)"]
  m5["scripts (1 file)"]
  m1 -->|"2"| m5
  m2 -->|"2"| m0
  m4 -->|"1"| m1
  m4 -->|"1"| m2
  m4 -->|"1"| m3
```

### concepts

```mermaid
flowchart TD
  n0["references/concepts.md (~156 tok)"]
  n1["note"]
  n1 -.-> n0
```

### handoff

```mermaid
flowchart TD
  n0["references/handoff-resume.md (~410 tok)"]
  n1["references/handoff-snapshot.md (~60 tok)"]
  n2["references/handoff-write.md (~633 tok)"]
  n3["reflect"]
  n4["scripts"]
  n0 -.-> n1
  n0 -.-> n4
  n1 --> n4
  n2 -.-> n1
  n3 -.-> n2
```

### note

```mermaid
flowchart TD
  n0["references/note.md (~583 tok)<br/>ref: references/varde-workflow-cli.md (~230 tok)"]
  n1["concepts"]
  n2["reflect"]
  n0 -.-> n1
  n2 --> n0
```

### reconcile

```mermaid
flowchart TD
  n0["references/reconcile.md (~95 tok)"]
  n1["reflect"]
  n1 -.-> n0
```

### reflect

```mermaid
flowchart TD
  n0["references/reflect.md (~343 tok)"]
  n1["handoff"]
  n2["note"]
  n3["reconcile"]
  n0 -.-> n1
  n0 --> n2
  n0 -.-> n3
```

### scripts

```mermaid
flowchart TD
  n0["scripts/handoff-snapshot.py"]
  n1["handoff"]
  n1 -.-> n0
```

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Find or record durable knowledge — a decision, pattern, d... | ~807 | ~1193 | ~807 | ~1193 | - | 1 | references/note.md, references/concepts.md, references/varde-workflow-cli.md |
| Wrap up finished work or capture what was learned | ~1150 | ~2324 | ~1150 | ~2324 | - | 1 | references/reflect.md, references/note.md, references/handoff-write.md, references/reconcile.md, references/concepts.md, references/varde-workflow-cli.md, references/handoff-snapshot.md, scripts/handoff-snapshot.py |
| Write a handoff | ~857 | ~917 | ~857 | ~917 | - | 0 | references/handoff-write.md, references/handoff-snapshot.md, scripts/handoff-snapshot.py |
| Resume a handoff, or pick up where a previous session lef... | ~634 | ~694 | ~634 | ~694 | - | 0 | references/handoff-resume.md, scripts/handoff-snapshot.py, references/handoff-snapshot.md |
| Check a knowledge note against current code | ~319 | ~319 | ~319 | ~319 | - | 0 | references/reconcile.md |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 3 (references/reflect.md) | < 6 | ok |
| Average links per linking file | 1.8 (9 links, 5 files) | <= 2 | ok |
| Cross-module edges | 7 | - | - |
| Diagram edges | 15 | <= 60 | ok |
| Max route cyclomatic | 6 | <= 10 | ok |
| Max route cognitive | 13 | <= 10 warn, <= 15 error | warning |
| Most files reached by one route | 8 (Wrap up finished work or capture what was learned) | <= 15 | ok |

## Findings

- single caller: references/concepts.md <- references/note.md
- single caller: references/handoff-resume.md <- SKILL.md: Resume a handoff, or pick up where a previous session lef...
- single caller: references/reflect.md <- SKILL.md: Wrap up finished work or capture what was learned
- shared: references/handoff-snapshot.md <- references/handoff-resume.md; references/handoff-write.md
- shared: references/handoff-write.md <- SKILL.md: Write a handoff; references/reflect.md
- shared: references/note.md <- SKILL.md: Find or record durable knowledge — a decision, pattern, d...; references/reflect.md
- shared: references/reconcile.md <- SKILL.md: Check a knowledge note against current code; references/reflect.md
