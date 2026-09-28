# Knowledge notes

## Search

Read a known note directly. To discover one, use ranked search per
`references/varde-workflow-cli.md` if `varde-workflow` is on PATH; else
Grep/Glob `<knowledge>/` and name the lost ranked search once. Read a note
in full only after search identifies it.

## Knowledge folder

`<knowledge>/` is the root of a markdown knowledge bundle. Use the type-first
path — type is a top-level folder, not nested under a domain:

`<knowledge>/<type>/<slug>.md`

Use `definition`, `decision`, `pattern`, `reference`, or `spec` (stored under
the plural `specs/` folder) for new notes. Keep other
`type` values another producer wrote, and leave folders another producer owns
(such as `conclusions/`, `promotions/`, or `flows/`) as they are, even when
their notes carry a different `type`.

`index.md` and `log.md` at the bundle root are reserved; never use them for
concept notes, and don't create them unless asked. An `index.md` inside a type
folder is a curated list, not a violation.

Plans and review findings in `<working>/` are not notes.

## Write notes

Never store session narrative, tool output, logs, temporary task state,
secrets, or unverified guesses. An obstacle belongs to the `varde-learn` skill;
write a durable lesson here only when it is a lasting decision, pattern, or
definition. Put note structure in frontmatter.

Frontmatter:

- `type`: required, non-empty.
- `description`: one sentence, used in search snippets.
- `generated: { by: <actor>, at: <ISO 8601 datetime> }` — `human:<id>` when the
  user dictated it verbatim, `<harness>/<model-id>` when you wrote it.
- `title`: only when the slug is a poor display name.
- `paths`: producer extension listing the code the note describes.

```markdown
---
type: pattern
description: One-sentence summary of the rule.
generated: { by: <harness>/<model-id>, at: 2026-08-14T00:00:00Z }
paths:
  - src/foo/bar.ts
---

Start with the rule...
```

When a human reviews and signs off on a note, add
`verified: { by: human:<id>, at: <ISO 8601> }` and leave `generated` alone.
`generated`, `verified`, and `reconciled` are three separate facts.

Body by type:

- `definition`: put the definition in frontmatter when possible.
- `pattern`: start with the rule, in short bullets; add examples only when they
  prevent misuse.
- `decision`:

```markdown
## What
<one sentence>

## Why
<one sentence>

## Constraints
- <zero to three bullets>
```

To retire a note, set `status: deprecated` rather than deleting it, so links
and history resolve (`draft | stable | deprecated`; absent means `stable`).
Delete only incorrect content. Rename or move with `git mv`.

## Link notes

Link with bundle-absolute paths (`/pattern/x.md`) under `## Related`,
covering prerequisites and dependencies. Link a not-yet-written note only if
you write it this session.
