---
topic: varde-knowledge/note-create
version: 1
summary: Create, edit, and map knowledge notes with the memory commands
---

- A note is a Markdown entry file `<memory>/<scope>/<key>/<id>.md`. A migrated knowledge note is a `project` entry with a `type` and `surface: false`.
- Create a note with `varde learn memory add --scope project --no-surface --json --text "<body>"`. Its `version` feeds the next step.
- Set `type`, `description` and `topic` with `memory set-field <id> <key> <value> --expected-version <v>`. `memory show` prints the current version.
- Edit a body with `memory update`. Run `memory delete` only on an explicit human call (prefer `retire`).
- After note changes, print the map with `varde learn memory map` (`--write <file>` saves it); never write it by hand. You are done when `varde learn memory lint` exits 0.
- Rename or move with `git mv` (plain `mv` outside a repo).
- For role telemetry, run `varde learn tools --by-role` (add `--friction` to update friction items). Record durable role practices as `pattern` or `decision` notes.
