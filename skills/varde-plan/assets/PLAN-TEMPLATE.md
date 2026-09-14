Frontmatter:

```
---
status: draft
title: "<user's initial prompt>"
type: plan
---
```

Writing style: `Problem` and `Solution` are the only sections that stay prose — 1-3 sentences of high-level explanation. Everything else (`Design`, `Decisions so far`, `Open Questions`, `Assumptions`, `Non-goals`, `Constraints`, `Acceptance criteria`) defaults to structured spec form — bullet lists, `key: value` lines, signatures, small tables — one fact per line, not paragraphs that bury a signature or an edge case inside connective sentences. If a bullet needs a reason, format it as `<decision> — <reason>`, not a run-on sentence.

Body template:

```
## Problem

What's broken, missing, or costly — and why does it matter now? (prose, 1-3 sentences)

## Solution

What will be true after this plan executes that isn't true now? (prose, 1-3 sentences)

## Non-goals

- <item explicitly out of scope>

## Constraints

- <technical or product constraint>

## Design

### Tech choices

(filled during planning — bullets, one choice per line: `<choice> — <reason>`)

### Schema / data model

(filled during planning — field/type list or signature block, not prose)

### API / interface contracts

(filled during planning — one signature or endpoint per line, with behavior/edge cases as sub-bullets)

## Decisions so far

<!-- one line per resolved question: `<question> → <answer>` -->

## Open Questions

<!-- one entry per open item; write "n/a" with a one-line reason if none apply.
     Each entry is answerable either in chat or by editing/commenting this
     line directly — see references/GROW-DOC.md. -->
- **<question>** — <why it matters or what it blocks>. Recommendation: <suggested answer — one-line reason>.

## Assumptions

<!-- guesses made while drafting so progress isn't blocked on every unknown.
     User can confirm, correct, or challenge any line — in chat or by editing
     here. Confirmed-as-is assumptions stay listed as a record of the call;
     corrected ones move into Decisions so far and are removed from here. -->
- <assumption> — affects: <plan split | AC | sequencing | design> — confidence: <low|medium|high>

## Acceptance criteria

<!-- The plan-level contract of "done" — what must be observably true once the
     whole change ships, independent of how build later slices it into tasks.
     Grown and reviewed during planning (references/ACCEPTANCE-CRITERIA.md):
     each item in Given/When/Then form, testability-scored, tagged assert or
     retrieve. build verifies these once at the end of the run; it does NOT
     re-author them per task. -->
- [ ] Given <precondition>
      When <action>
      Then <observable outcome>
      (assert: <command or structural check> → <expected result>
       | retrieve: <file(s) or grep to read> → context for judgment)
```

There is no `## Tasks` section: task decomposition is owned by `/varde-build`,
not the plan. `plan.md` carries the spec and the plan-level acceptance criteria;
build reads them, breaks the work into task files, executes, and verifies the
criteria.

The build orchestrator's run events (dispatch, retry, blocker, completion) live
in a separate `run-state.md` file it owns during execution — not in `plan.md`.
Task-level execution evidence lives in each task's own `#### Progress` section.

