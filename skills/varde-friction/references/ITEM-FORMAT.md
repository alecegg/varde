# Item format

New items use this frontmatter:

```yaml
type: friction-item
source: <skill, task, or manual-review source>
status: open
signal: <obstacle | positive>
created: <YYYY-MM-DD>
head_sha: <HEAD sha at capture, short is fine — or `none` outside a repo>
session_label: <session name, or sanitized first prompt, capped at 46 chars>
```

`signal` defaults to `obstacle` (a problem, gap, or confusion) when omitted
by older items. Use `positive` for a technique that worked well or an
explicit user confirmation worth generalizing — `friction-distillation`
uses this field to decide whether a cluster should add/tighten guidance or
confirm/promote existing guidance as-is.

`head_sha` and `session_label` are the item's **provenance anchor** — a cheap
answer to "where did this come from?" that a later reconcile pass reads. The
SHA is the machine-readable anchor (`git log <head_sha>..HEAD -- <path>` tells
a reconcile pass whether the code moved since capture); the label is the
skimmable one — the session name if set, otherwise the session's sanitized
first prompt truncated to 46 chars. Keep the label lossy on purpose; it is a
hint, not a record. Outside a git repo, set `head_sha: none`.

`status` follows a lifecycle: `open` → `resolved` (a reconcile pass found
evidence the obstacle is gone) → `archived`, or a `positive`/durable lesson is
promoted into a knowledge note before it leaves. **Capture only ever writes
`open`** — status transitions belong to the reconcile pass (`varde-reflect`),
never to capture.

The body is free-form Markdown. Include the concrete event, impact, evidence,
workaround or cost, and possible improvement target. Keep separate events
separate unless they clearly describe the same recurring friction.

## Creating a new item

When step 5's search finds no matching open item, create a new
markdown file under `memory-bank/friction/` with the frontmatter above and a
free-form body. Use a short kebab-case filename that identifies the topic,
e.g. `memory-bank/friction/<slug>.md`.

## Appending to an existing item

When step 5's search finds a matching item, append a new occurrence instead
of creating a duplicate. Preserve the item's existing frontmatter and status.

Recurrence is **intentional signal**, not noise to collapse — how often a
friction recurs is exactly what `friction-distillation`'s "≥2 similar items"
threshold reads. So keep every occurrence; do not merge or dedup them away.
For the count to be legible later, stamp each appended occurrence with its own
provenance — start the occurrence with a line like
`- <YYYY-MM-DD> · <head_sha short> · <session_label>` so occurrences stay
correlatable across sessions even though the item-level `head_sha` records
only the first.

1. `Read` the item file to get its current content.
2. Apply a targeted `Edit` that appends the new occurrence to the body,
   leaving the frontmatter and prior occurrences untouched.

Use only `Glob`, `Grep`, and `Read` for discovery, and `Write`/`Edit` for
mutations. Do not invent friction-specific tooling.
