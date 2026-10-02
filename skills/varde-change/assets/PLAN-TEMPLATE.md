<!-- kind: reference -->
Frontmatter:

```
---
status: backlog
title: "<user's initial prompt>"
type: plan
depends_on: []       # optional; sibling plan dir names (a child's slug, never `<group>/<child>`) that must be `completed` first
observed_specs: []   # optional; <knowledge>/specs/<domain>.md domains this plan touches
---
```

Writing style: only `Problem` and `Solution` are prose (1-3 sentences). Every other section is structured spec — bullets, `key: value` lines, signatures, small tables — one fact per line. A bullet that needs a reason reads `<decision> — <reason>`.

Body template:

```
## Problem

What's broken, missing, or costly, and why now?

## Solution

What will be true after this plan that isn't now?

## Non-goals

- <item explicitly out of scope>

## Constraints

- <technical or product constraint>

## Design

### Tech choices

(none) unless needed — `<choice> — <reason>`

### Schema / data model

(none) unless needed — fields/types or signatures

### API / interface contracts

(none) unless needed — one signature per line, edge cases as sub-bullets

## Decisions so far

<!-- one line per resolved question: `<question> → <answer>` -->

## Open Questions

<!-- answerable in chat or by editing here; if none, replace the bullet with plain text (not a bullet): n/a — <reason> -->
- **<question>** — <why it matters or what it blocks>. Recommendation: <suggested answer — one-line reason>.

## Assumptions

<!-- guesses made instead of asking; confirm or correct in chat or here -->
- <assumption> — affects: <plan split | AC | sequencing | design> — confidence: <low|medium|high>

## Acceptance criteria

<!-- plan-level definition of done -->
- [ ] Given <precondition>
      When <action>
      Then <observable outcome>
      (assert: <command or structural check> → <expected result>
       | retrieve: <file(s) or grep to read> → context for judgment)

## Progress

<!-- one line per event; first line: subject: <review-subject-id> -->

## Related

<!-- knowledge this plan relies on: [title](/decision/x.md), /specs/, /pattern/, /definition/ -->
```

No `## Tasks`: build writes task files; task evidence lives in each task's
Progress.
