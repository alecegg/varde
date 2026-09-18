# Knowledge notes

Search project notes first. Use user notes only when project notes do not help.

Once per session, check for `varde-docs` with `command -v varde-docs >/dev/null 2>&1`.
If present, read `references/varde-docs-cli.md`. Use its search and safe
write commands. If it is absent or fails, use Grep, Glob, Write, and Edit.
Do not build or install it.

Use Grep for text search and Glob for structural search, scoped to the knowledge folder, to find candidate notes before reading them in full — don't open every note for a targeted question:

```bash
grep -ril "<search text>" memory-bank/knowledge/
# all notes of a given type
find memory-bank/knowledge/pattern -name "*.md"
```

Read a note's full body only after grep/glob has identified it as relevant — there's no partial-fetch step, so read the whole file rather than using Read to browse the folder.

If a file operation fails, report a hard error and stop.

## Knowledge folder

Project concept notes live under `memory-bank/knowledge/` — an OKF v0.2 Knowledge Bundle. `memory-bank/knowledge/` is the bundle root.

Use the type-first path — type is a top-level folder, not nested under a domain:

`memory-bank/knowledge/<type>/<slug>.md`

Conventional `type` values (and their folder) are `definition`, `decision`,
`pattern`, `reference`, and `spec` (stored under the plural `specs/` folder).
Tolerate other `type` values in notes another producer wrote.

Reserved filenames are `index.md` and `log.md` — never use them for concept documents, at any level of the hierarchy.

Working memory lives under `memory-bank/working/`. It contains plans and findings — not OKF Concepts. Use their own plan and task files — this skill does not manage them.

If `memory-bank/knowledge/` (or a type subdirectory you need) doesn't exist yet, create it directly with `mkdir -p` / `Write` before adding notes.

A repo's conventions are captured here directly — there's no separate setup or onboarding step. Write `pattern`/`decision` notes for coding standards and `definition` notes for glossary terms; the notes are the setup, and the folder is created on first write (above).

## Write commands

Keep stored memory compact and factual: structured frontmatter over body prose, no session narrative, tool output, or raw logs.

Create new concept notes at the type-first path with `Write`. Apply a targeted edit to existing notes with `Edit` instead of recreating them.

Every concept needs a non-empty `type` field (OKF's only required field). Also set, per the OKF spec:

- `description`: one sentence — recommended by OKF, and required in practice for this skill's `index.md` entries and for search snippets.
- `generated: { by: <actor>, at: <ISO 8601 datetime> }` — who produced the
  current content and when. Use `human:<id>` when the user dictated it
  verbatim, `<producer>/<version>` (e.g. `claude/sonnet-4-6`) when you wrote it.
- `title`: optional, only when the slug alone is a poor display name.

```markdown
---
type: pattern
description: One-sentence summary of the rule.
generated: { by: claude/sonnet-4-6, at: 2026-08-14T00:00:00Z }
paths:
  - src/foo/bar.ts
---

Start with the rule...
```

`paths` is a producer extension, not part of OKF — it is how the reconcile pass
below finds the code a note describes.

If the user (a human) explicitly confirms a note is correct — not just dictated it, but reviewed and signed off — add a `verified` entry rather than re-touching `generated`:

```yaml
verified: { by: human:<id>, at: 2026-08-14T00:00:00Z }
```

`generated.by` (who wrote it), `verified.by` (who confirmed it), and
`reconciled: { at, sha }` (when it was last checked against code, and at what
`HEAD`) are three separate facts.

For `definition` notes, put the definition in frontmatter when practical.

For `decision` notes, use:

```markdown
## What
<one sentence>

## Why
<one sentence>

## Constraints
- <zero to three bullets>
```

For `pattern` notes, start with the rule. Prefer short bullets. Include examples only when they prevent misuse. Put documented paths in the `paths` frontmatter field.

To retire a note, set `status: deprecated` rather than deleting it, so existing
links and history stay resolvable (`draft | stable | deprecated`; absent means
`stable`). Reserve `git rm` for content that was wrong or never should have been
written. Rename or relocate with `git mv`.

## Linking concepts

Link with standard markdown links, not wiki-links. Prefer the bundle-relative
absolute form — stable if the note moves within its subdirectory — with the
`.md` suffix and the full path from `memory-bank/knowledge/`:

```markdown
## Related

- [code-review pattern](/pattern/code-review.md) - checks review behavior
```

A relative form (`../pattern/code-review.md`) also works per §6.1, but is more fragile across moves. Always include the `.md` suffix and the full path from `memory-bank/knowledge/` (the bundle root) when using the absolute form. Every non-empty body should include high-signal related links; add prerequisites and dependencies, skip ones that aren't load-bearing. A link to a concept that doesn't exist yet isn't an error , but don't leave one dangling on purpose.

## Index and log files

`index.md` may exist in any directory to list its contents. It carries no
frontmatter, the sole exception being an optional `okf_version` on a
bundle-root one. Body format:Body format:

```markdown
# Section Heading

* [Title](relative-url) - short description, pulled from the concept's `description` field
```

Add one to a type directory once it has enough concepts that browsing links
beats grepping.

`log.md` may exist at any level to record a change history, newest first, under
`YYYY-MM-DD` headings. Only add one if the user asks for it.

## Check notes against code

To check whether a concept note has drifted from the code it describes: read the note, read the code paths it references (from its `paths` frontmatter or body links), and reason about whether the description still matches. There is no automated staleness check — this is a manual/LLM comparison. If the note carries `stale_after` , treat `today >= stale_after` as another drift signal, not just outdated `paths`.

This runs slower and more carefully than the friction reconcile: a stale knowledge note is *wrong context a future agent will act on*, so the failure cost is higher than clutter. The pass is **requiring evidence and user confirmation**, and its endpoint is **correct-in-place**, not delete:

- **Cite the evidence, or leave it alone.** A drift claim must point at the code that no longer matches — a changed signature, a removed flag, a moved path. If you can't cite what changed, the note stands. No evidence → no edit. This is what stops a reconcile pass from rewriting notes on a hunch.
- **Confirm before rewriting.** Propose the correction with its evidence and change nothing until the user confirms — don't silently overwrite a note that another engineer authored.
- **Stamp the reconciliation.** After confirming a note is still correct (or after correcting it), record `reconciled: { at: <ISO 8601>, sha: <head_sha> }` in frontmatter. For a knowledge note, "last reconciled against SHA" is the provenance that matters — more than which session first wrote it — because it answers "has the code moved since anyone last checked this note?" A `reconciled.sha` far behind `HEAD` is itself a staleness signal for the next pass.

## Storage and persistence

Project notes live in-repo under `memory-bank/knowledge/` — visible in `git
status`, versioned, obvious. **User knowledge is the exposure to be honest
about:** it lives outside any one repo, is **cross-project by design** (that's
its whole value), does not show in a repo's `git status`, and **survives
uninstalling this skill** — the notes remain after the skill is gone. Notes may
quote source, paths, and error text from wherever they were captured, so a note
written while working a client repo can carry that repo's internals into a
cross-project store. Reason about sensitivity before pointing this at a
codebase you don't own, and prune the user store per your own retention needs —
uninstalling won't do it for you.

## When not to write knowledge

Do not write temporary task state, secrets, or unverified guesses.

Record a concrete workflow obstacle as a friction item instead of a note —
see `references/note-friction.md`.
