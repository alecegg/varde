# varde-session-notes flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~181 tok; routes: Write or tidy session notes, Resume a session from notes, or pick up where a previous...)
  - references/resume.md (~396 tok; routes: Resume a session from notes, or pick up where a previous...)
  - references/snapshot.md (~106 tok; routes: Write or tidy session notes, Resume a session from notes, or pick up where a previous...)
  - references/write.md (~589 tok; routes: Write or tidy session notes)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Write or tidy session notes | ~876 | ~876 | ~876 | ~876 | - | 0 | references/write.md, references/snapshot.md |
| Resume a session from notes, or pick up where a previous... | ~683 | ~683 | ~683 | ~683 | - | 0 | references/resume.md, references/snapshot.md, scripts/session-notes-snapshot.py |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-session-notes/resume-label | ~250 |
| varde-session-notes/resume-steps | ~178 |
| varde-session-notes/snapshot-steps | ~132 |
| varde-session-notes/write-links | ~271 |
| varde-session-notes/write-save | ~282 |
| varde-session-notes/write-steps | ~204 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 2 (references/resume.md) | < 6 | ok |
| Average links per linking file | 1.5 (3 links, 2 files) | <= 2 | ok |
| Cross-module edges | 3 | - | - |
| Max route cyclomatic | 3 | <= 10 | ok |
| Max route cognitive | 4 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 3 (Resume a session from notes, or pick up where a previous...) | <= 15 | ok |

## Findings

- single caller: references/resume.md <- SKILL.md: Resume a session from notes, or pick up where a previous...
- single caller: references/write.md <- SKILL.md: Write or tidy session notes
- shared: references/snapshot.md <- SKILL.md: Resume a session from notes, or pick up where a previous...; SKILL.md: Write or tidy session notes; references/resume.md; references/write.md
