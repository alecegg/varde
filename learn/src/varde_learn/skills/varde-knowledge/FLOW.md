# varde-knowledge flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~247 tok; routes: Find or record a note or a scoped memory lesson, Distill concluded plans or inactive areas, Check a note against current code, Wrap up a session or finished plan (friction, knowledge,...)
  - references/distill.md (~286 tok; routes: Distill concluded plans or inactive areas)
  - references/note.md (~381 tok; routes: Find or record a note or a scoped memory lesson)
  - references/reconcile.md (~79 tok; routes: Check a note against current code)
  - references/reflect.md (~274 tok; routes: Wrap up a session or finished plan (friction, knowledge,...)
  - references/varde-workflow-cli.md (~215 tok; routes: -)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Find or record a note or a scoped memory lesson | ~628 | ~628 | ~628 | ~628 | - | 0 | references/note.md |
| Distill concluded plans or inactive areas | ~533 | ~533 | ~533 | ~533 | - | 0 | references/distill.md |
| Check a note against current code | ~326 | ~326 | ~326 | ~326 | - | 0 | references/reconcile.md |
| Wrap up a session or finished plan (friction, knowledge,... | ~521 | ~521 | ~521 | ~521 | - | 0 | references/reflect.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-knowledge/distill-steps | ~241 |
| varde-knowledge/distill-write | ~229 |
| varde-knowledge/note-create | ~266 |
| varde-knowledge/note-format | ~331 |
| varde-knowledge/note-search | ~143 |
| varde-knowledge/reconcile-steps | ~96 |
| varde-knowledge/reflect-notes | ~258 |
| varde-knowledge/reflect-steps | ~165 |
| varde-knowledge/scoped-memory | ~316 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 1 (Find or record a note or a scoped memory lesson) | <= 15 | ok |

## Findings

- single caller: references/distill.md <- SKILL.md: Distill concluded plans or inactive areas
- single caller: references/note.md <- SKILL.md: Find or record a note or a scoped memory lesson
- single caller: references/reconcile.md <- SKILL.md: Check a note against current code
- single caller: references/reflect.md <- SKILL.md: Wrap up a session or finished plan (friction, knowledge,...
