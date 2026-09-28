# Ordered skill layout

## Entry point dispatch

For several invocation shapes, add an entry-point table. Agents act from it
before reading the workflow, so each cell names the actual discovery method,
operation, or reference, not an outcome.

## Workflow

Use one numbered workflow per invocation type, with one imperative action per
step. Give each step one primary procedure, inline or in a reference. Keep short
procedures and gates inline; move branching detail to the reference that owns
it. Keep literal templates inline
or in `assets/`. End `SKILL.md` with a short `## Gotchas` section of concrete
corrections needed whenever the skill fires.

## Reference fan-out

Agents lose their place when one phase needs many files.

- Give each step one primary procedure. Load supplementary requirements only
  when needed; avoid splitting the procedure across cross-referencing peers.
- Split only to improve routing, never to hit a size target or by dropping
  directives.
- **Premature completion** (a step ends before its criterion is met): make
  completion observable; split by sequence only when later work repeatedly
  prompts early completion and evidence shows a handoff helps.
