---
name: varde-knowledge
description: >
  TRIGGER: Record or look up a durable project fact — an architectural decision
  (ADR), a coding pattern or convention, a glossary/domain definition, a research
  finding, or a reference note. These live as knowledge notes under the project
  (or user) knowledge folder.
  SKIP: Skip for plan/task files, review findings (use /varde-review), or
  user-facing README/docs (use /varde-docs).
  Example phrases: "record this decision", "document this pattern", "define this
  term", "write a knowledge note", "find the architecture note".
---

## Instructions

Read project knowledge notes first; fall back to user knowledge only when the project store doesn't cover it.

Once per session, check whether the optional `varde-docs` CLI is installed on PATH: run `command -v varde-docs >/dev/null 2>&1`. When present, load `references/VARDE-DOCS-CLI.md` and prefer it for finding notes (ranked full-text `search`) and for conflict-safe writes (OCC `create`/`update`/`set-field` on the `memory-bank/knowledge/` bundle); it operates on the same files with the same conventions described below. When absent — or on any failure — use the plain Grep/Glob/Write/Edit flow described here. Don't build or install it.

Use Grep for text search and Glob for structural search, scoped to the knowledge folder, to find candidate notes before reading them in full — don't open every note for a targeted question:

```bash
grep -ril "<search text>" memory-bank/knowledge/
# all notes of a given type
find memory-bank/knowledge/pattern -name "*.md"
```

Read a note's full body only after grep/glob has identified it as relevant — there's no partial-fetch step, so read the whole file rather than using Read to browse the folder.

If a file operation fails, report a hard error and stop.

## Knowledge folder

Project concept notes live under `memory-bank/knowledge/` — an OKF v0.2 Knowledge Bundle (https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md). `memory-bank/knowledge/` is the bundle root.

Use the type-first path — type is a top-level folder, not nested under a domain:

`memory-bank/knowledge/<type>/<slug>.md`

This type-first layout is a producer convention this skill imposes on top of OKF, not something OKF requires — OKF's own spec (https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) leaves bundle structure and `type` values open to the producer. Conventional `type` values (and their folder) used in this project are `definition`, `decision`, `pattern`, `reference`, and `spec` (stored under the plural `specs/` folder, per the `/varde-spec` skill). Consumers (including this skill, reading notes another producer wrote) MUST tolerate other `type` values, not reject them.

Reserved filenames are `index.md` and `log.md` — never use them for concept documents, at any level of the hierarchy.

Working memory lives under `memory-bank/working/`. It contains plans and findings — not OKF Concepts. Use their own plan and task files — this skill does not manage them.

If `memory-bank/knowledge/` (or a type subdirectory you need) doesn't exist yet, create it directly with `mkdir -p` / `Write` before adding notes.

A repo's conventions are captured here directly — there's no separate setup or onboarding step. Write `pattern`/`decision` notes for coding standards and `definition` notes for glossary terms; the notes are the setup, and the folder is created on first write (above).

## Write commands

Keep stored memory compact and factual: structured frontmatter over body prose, no session narrative, tool output, or raw logs.

Create new concept notes at the type-first path with `Write`. Apply a targeted edit to existing notes with `Edit` instead of recreating them.

Every concept needs a non-empty `type` field (OKF's only required field). Also set, per the OKF spec:

- `description`: one sentence — recommended by OKF, and required in practice for this skill's `index.md` entries and for search snippets.
- `generated: { by: <actor>, at: <ISO 8601 datetime> }` — records who/what produced the current content and when. Use `human:<id>` when the user dictated the content verbatim, or `<producer>/<version>` (e.g. `claude/sonnet-4-6`) when you authored/drafted it. This is OKF's own mechanism for provenance/audit-trail — it stands in for "who wrote this and when" instead of relying on `git blame`, which isn't always available (a bundle exported as a tarball, or a note read outside this repo, still carries this).
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

`paths` is a producer-defined extension field (OKF permits arbitrary extra keys, §4.1) — not part of OKF itself. It's how "Reconciling knowledge against code" (below) finds the code a note describes.

If the user (a human) explicitly confirms a note is correct — not just dictated it, but reviewed and signed off — add a `verified` entry rather than re-touching `generated`:

```yaml
verified: { by: human:<id>, at: 2026-08-14T00:00:00Z }
```

`generated.by` (who wrote it) and `verified.by` (who confirmed it) are deliberately separate per OKF §5.2 — don't conflate them. A third, `reconciled: { at, sha }`, is stamped by the reconcile pass ("Reconciling knowledge against code", below) to record when the note was last checked against the code and at what `HEAD` — distinct again from both.

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

To retire a note, prefer OKF's lifecycle field over deletion: set `status: deprecated` (OKF §5.4 — `draft | stable | deprecated`; absent `status` means `stable`). A deprecated concept is kept in place so existing links and history stay resolvable; it just signals "no longer current" to a reader. Reserve `git rm memory-bank/knowledge/<type>/<slug>.md` for content that was wrong or never should have been written. To rename or relocate a note, use `git mv memory-bank/knowledge/<type>/<old-slug>.md memory-bank/knowledge/<type>/<new-slug>.md` — OKF doesn't define a rename operation of its own; this is a filesystem/git concern outside the spec, so plain `git mv` is correct, not a workaround.

## Checking notes for expected shape

There's no automated validator for this skill's own conventions (the `## What`/`## Why`/`## Constraints` shape for `decision`, etc. — OKF itself has no opinion on body structure beyond §4.2's three conventional headings, `# Schema`/`# Examples`/`# Computation`, none of which apply to these types). When it matters, open the note and check by eye that it has the expected frontmatter fields (`type`, `description`, `generated`, plus anything the type requires) and that reserved filenames (`index.md`, `log.md`) aren't misused. Fix anything off with a targeted edit.

## Linking concepts

Link with standard markdown links, not wiki-links — OKF §6.1 defines only `[text](target)` forms; `[[slug]]`-style links are not part of the spec and won't be recognized by any OKF-aware tooling (link resolution, orphan detection, etc.), so a note that only uses them reads as unlinked. Prefer the bundle-relative absolute form (stable if the note moves within its subdirectory):

```markdown
## Related

- [code-review pattern](/pattern/code-review.md) - checks review behavior
```

A relative form (`../pattern/code-review.md`) also works per §6.1, but is more fragile across moves. Always include the `.md` suffix and the full path from `memory-bank/knowledge/` (the bundle root) when using the absolute form. Every non-empty body should include high-signal related links; add prerequisites and dependencies, skip ones that aren't load-bearing. A link to a concept that doesn't exist yet isn't an error (OKF §6.1 requires tolerating broken links), but don't leave one dangling on purpose.

## Index and log files

`index.md` (OKF §8) MAY exist in any directory to list its contents for progressive disclosure. It carries no frontmatter (the sole exception being an optional `okf_version` key on a bundle-root `index.md`) — don't add `type` or anything else to one. Body format:

```markdown
# Section Heading

* [Title](relative-url) - short description, pulled from the concept's `description` field
```

Not required — OKF permits a consumer to synthesize this view on the fly — but worth adding to a type directory once it has enough concepts that browsing markdown links beats grepping.

`log.md` (OKF §9) MAY exist at any level to record a chronological history of changes, newest first, under `YYYY-MM-DD` headings. This skill doesn't require maintaining one; only add it if the user asks for a change history at that level.

## Reconciling knowledge against code

To check whether a concept note has drifted from the code it describes: read the note, read the code paths it references (from its `paths` frontmatter or body links), and reason about whether the description still matches. There is no automated staleness check — this is a manual/LLM comparison. If the note carries `stale_after` (OKF §5.5, an absolute `YYYY-MM-DD` date), treat `today >= stale_after` as another drift signal, not just outdated `paths`.

This runs slower and more carefully than the friction reconcile: a stale knowledge note is *wrong context a future agent will act on*, so the failure cost is higher than clutter. The pass is **evidence-gated and confirm-gated**, and its endpoint is **correct-in-place**, not delete:

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
