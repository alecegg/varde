---
topic: varde-knowledge/note-format
version: 1
summary: Frontmatter fields, body shape by type, retiring, and linking notes
---

Frontmatter:

- `type`: required, non-empty.
- `description`: one sentence, used in search snippets.
- `generated: { by: <actor>, at: <ISO 8601 datetime> }`: use `human:<id>` when the user dictated it verbatim, `<harness>/<model-id>` when you wrote it.
- `verified: { by: human:<id>, at: <ISO 8601> }`: add it when a human reviews and signs off; leave `generated` alone.
- `title`: only when the slug is a poor display name.
- `paths`: code the note describes (used by reconcile).
- `reconciled: { at, sha }`: set by the reconcile route.

Body by type:

- `definition`: the one-sentence `description` is the definition. Add a body only for usage notes.
- `pattern`: start with the rule, in short bullets. Add examples only when they prevent misuse.
- `decision`:

```markdown
## What
<one sentence>

## Why
<one sentence>

## Constraints
- <zero to three bullets>
```

Retire a note: set `status: deprecated` (`draft | stable | deprecated`; absent means `stable`) rather than deleting, so links and history resolve.

Link with bundle-absolute paths (`/pattern/x.md`) under `## Related`, covering prerequisites and dependencies. Link a not-yet-written note only if you write it this session.
