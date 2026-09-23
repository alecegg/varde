# Knowledge notes

Search project notes first. Use user notes only when project notes do not help.

Read one known note directly when no mutation follows. For discovery or any
note mutation, check `command -v varde-workflow >/dev/null 2>&1`. If present,
read `references/varde-workflow-cli.md`. Otherwise use Grep and Glob for
discovery, report degraded capability, and stop before mutation. Never install
the CLI.

Use Grep for fallback text search. Use Glob for structural search. Scope both
commands to the knowledge folder. Identify candidates before full reads.
Do not open every note for a targeted question:

```bash
grep -ril "<search text>" <knowledge>/
# all notes of a given type
find <knowledge>/pattern -name "*.md"
```

Read a note's full body only after Grep or Glob identifies it as relevant. No
partial fetch exists, so read the whole file instead of browsing the folder
with Read.

If a file operation fails, report a hard error and stop.

## Knowledge folder

Project concept notes live under `<knowledge>/` — an OKF v0.2 Knowledge Bundle. `<knowledge>/` is the bundle root.

Use the type-first path — type is a top-level folder, not nested under a domain:

`<knowledge>/<type>/<slug>.md`

Use these conventional `type` values and folders: `definition`, `decision`,
`pattern`, `reference`, and `spec` (stored under the plural `specs/` folder).
Keep other `type` values when another producer wrote them.

Reserved filenames are `index.md` and `log.md` — never use them for concept documents, at any level of the hierarchy.

Working memory lives under `<working>/`. It contains plans and findings — not OKF Concepts. Use their own plan and task files — this skill does not manage them.

If `<knowledge>/` (or a type subdirectory you need) doesn't exist yet, create it directly with `mkdir -p` / `Write` before adding notes.

Use these notes as the repository's conventions. There is no separate setup or
onboarding step. Write `pattern` or `decision` notes for coding standards and
`definition` notes for glossary terms. Create the folder on the first write,
as described above.

## Write commands

Keep stored memory compact and factual. Put structure in frontmatter instead of
body prose. Do not store session narrative, tool output, or raw logs.

Prepare complete content for new notes. Create them through `concept create`.
For updates, use one `concept show` and OCC-safe `concept update`.

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

`paths` is a producer extension, not part of OKF. The reconcile pass below uses
it to find the code a note describes.

If the user (a human) explicitly confirms a note is correct — not just dictated it, but reviewed and signed off — add a `verified` entry rather than re-touching `generated`:

```yaml
verified: { by: human:<id>, at: 2026-08-14T00:00:00Z }
```

`generated.by` (who wrote it), `verified.by` (who confirmed it), and
`reconciled: { at, sha }` (when it was last checked against code, and at what
`HEAD`) are three separate facts.

For `definition` notes, put the definition in frontmatter when possible.

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
`stable`). Use `concept delete` only for incorrect content. Rename or relocate
with `git mv`.

## Linking concepts

Link with standard markdown links, not wiki-links. Prefer the bundle-relative
absolute form — stable if the note moves within its subdirectory — with the
`.md` suffix and the full path from `<knowledge>/`:

```markdown
## Related

- [code-review pattern](/pattern/code-review.md) - checks review behavior
```

A relative form (`../pattern/code-review.md`) also works per §6.1, but moves can
break it. For an absolute link, include the `.md` suffix and the full path from
`<knowledge>/` (the bundle root). Every non-empty body should include
only high-signal related links: add prerequisites and dependencies, and omit
links that are not load-bearing. A link to a concept that does not exist yet is
allowed, but do not leave one intentionally dangling.

## Index and log files

`index.md` may exist in any directory to list its contents. It carries no
frontmatter, the sole exception being an optional `okf_version` on a
bundle-root one. Body format:

```markdown
# Section Heading

* [Title](relative-url) - short description, pulled from the concept's `description` field
```

Add one to a type directory when browsing its links is easier than grepping.

`log.md` may exist at any level to record a change history, newest first, under
`YYYY-MM-DD` headings. Only add one if the user asks for it.

## Check notes against code

To check a concept note for drift, read the note first. Then read the code paths
listed in its `paths` frontmatter or body links. Compare the description with
that code. No automated staleness check exists; this is a manual comparison. If
the note has `stale_after`, also treat `today >= stale_after` as a drift signal.

Treat this check as more careful than friction reconciliation. A stale note gives
future agents wrong context, so the cost is higher than extra clutter. Require
evidence and user confirmation. Correct the existing note; do not delete it:

- **Cite the evidence, or leave it alone.** A drift claim must point at the code that no longer matches — a changed signature, a removed flag, a moved path. If you can't cite what changed, the note stands. No evidence → no edit. This is what stops a reconcile pass from rewriting notes on a hunch.
- **Confirm before rewriting.** Propose the correction with its evidence and change nothing until the user confirms — don't silently overwrite a note that another engineer authored.
- **Stamp the reconciliation.** After confirming a note is correct or correcting it, record `reconciled: { at: <ISO 8601>, sha: <head_sha> }` in frontmatter. This records the `HEAD` checked. If `reconciled.sha` is far behind `HEAD`, treat it as a staleness signal for the next pass.

## Storage and persistence

Project notes live in `<knowledge>/`. They are versioned and visible
in `git status`. **User knowledge needs extra care:** it lives outside one repo,
is **cross-project by design**, does not appear in a repo's `git status`, and
**survives uninstalling this skill**. Notes can quote source, paths, and error
text from the place where they were captured. A note from a client repo can
therefore copy that repo's internals into the cross-project store. Check
sensitivity before using this store with code you do not own. Prune the user
store according to your retention needs; uninstalling the skill does not prune
it.

## When not to write knowledge

Do not write temporary task state, secrets, or unverified guesses.

Record a concrete workflow obstacle as a friction item instead of a note —
see `references/note-friction.md`.
