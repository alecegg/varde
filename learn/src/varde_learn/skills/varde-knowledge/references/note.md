# Knowledge notes

Entry: find or record a durable note, or a scoped memory lesson.

## Search

- Discover with `varde learn memory map` or ranked `varde learn memory search`. Read a note in full only after discovery identifies it.

## Knowledge notes

- A note is a `project` memory entry with a `type` and `surface: false`. New notes use type `definition`, `decision`, `pattern`, or `reference`. Keep other producers' `type` values.
- A note records what another session needs. Never record session narrative, tool output or logs, temporary task state, secrets, or unverified guesses.
- Frontmatter requires a non-empty `type`, a one-sentence `description`, and `generated: { by, at }`. Only a human sign-off adds `verified`.
- Update an existing note over adding a new one. Retire with `status: deprecated` rather than deleting. Delete only incorrect content, and run `memory delete` only on an explicit human call.
- Link with bundle-absolute paths under `## Related`. Link a not-yet-written note only if you write it this session.
- Done when `varde learn memory map` regenerates the map (never edit it by hand) and `varde learn memory lint` exits 0.

## Scoped memory

- A lesson is short, has one scope (`agent`, `skill`, `project`, `global`), and holds no secrets.
- Read skill memory listed at session start before using that skill.
- `promote` commits to a local branch and never pushes. A person reviews the text for secrets and project-specific detail before it is shared. Do not promote project-scope entries.
