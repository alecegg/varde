# varde-learn flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~202 tok; routes: Capture an observed friction event, Reconcile an item against evidence, Check whether an adopted change recurred)
  - references/capture.md (~182 tok; routes: Capture an observed friction event)
  - references/reconcile.md (~287 tok; routes: Reconcile an item against evidence)
  - references/recurrence.md (~151 tok; routes: Check whether an adopted change recurred)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Capture an observed friction event | ~384 | ~384 | ~384 | ~384 | - | 0 | references/capture.md |
| Reconcile an item against evidence | ~489 | ~489 | ~489 | ~489 | - | 0 | references/reconcile.md |
| Check whether an adopted change recurred | ~353 | ~353 | ~353 | ~353 | - | 0 | references/recurrence.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-learn/capture-steps | ~225 |
| varde-learn/learn-gotchas | ~98 |
| varde-learn/reconcile-steps | ~323 |
| varde-learn/recurrence-steps | ~148 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 1 (Capture an observed friction event) | <= 15 | ok |

## Findings

- single caller: references/capture.md <- SKILL.md: Capture an observed friction event
- single caller: references/reconcile.md <- SKILL.md: Reconcile an item against evidence
- single caller: references/recurrence.md <- SKILL.md: Check whether an adopted change recurred
