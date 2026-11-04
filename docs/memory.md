# Memory

One store holds both scoped lessons and knowledge notes. Each entry is a
Markdown file with front matter. One search layer and one session pointer read
it, and one command group, `varde learn memory`, edits it.

## Model

- Layout: `<memory root>/<scope>/<key>/<id>.md`. Global entries have no key.
- Scopes: `agent` (key: agent name, needs `model` and `harness_version`), `skill`,
  `project` (key: `<name>-<16 hex>`) and `global`. Shared entries live in a separate
  git checkout and are index lines only (`shared:<id>`).
- Fields: `type` (`decision`, `pattern`, `definition`, `reference`, `lesson`),
  `topic` (slug), `status` (`active`, `retired`, `archived`), `created`, `valid_until`,
  `surface` (bool), `tags`, `title`, `aliases`, `description`. Unknown keys are kept.
- Defaults: a memory entry reads as `type: lesson`, `surface: true`. A knowledge
  concept reads as `project` scope, `surface: false`, with its own type.
- Summary: `description`, else the first non-heading line. A surfaced summary over 80
  characters is truncated on the pointer; `lint` rejects new ones.

## Pointer

SessionStart prints one block within `[memory] budget` (1200 characters):
the header, a `Topics:` line (at most 8 topics, names cut to 32 characters,
then `+<k> more`), the skill line, then index lines for `surface: true`
entries. Lines go by scope (skill, agent, project, global), then newest
`created`, then id. Expired entries are left out. Bodies never appear; read one
with `memory show <id>`. The hook scans the files (about 10 ms for 200 entries)
and never writes the search index.

## Search

`varde learn memory search --text <q>` ranks entries with SQLite FTS5 (bm25;
title and aliases weigh more than the body). `--topic`, `--scope` and
`--field key=value` narrow. The derived index lives under `<data>/varde/memory-index/`
and is safe to delete. Without FTS5 the command falls back to the term scorer.
Commands refresh the index; the hooks do not.

## Expiry

An entry past `valid_until` is hidden from the pointer and from search.
`memory list --expired` reports them. Nothing is deleted: a person retires each one.

## Commands

`add`, `list`, `show`, `search`, `update`, `set-field`, `retire`, `delete`, `map`,
`lint`, `reset`, `surface`, `promote`, `pull` and `migrate`. Run
`varde learn memory --help` for each.

## Aliases

Each old path still works for one release. It prints a deprecation notice on
stderr and runs the old behavior, so `--json` output is unchanged and keeps the
old knowledge shape (`slug,type,score,preview`), not the shape of `memory search`.

| Old path | New path |
| --- | --- |
| `learn knowledge create` | `learn memory add` |
| `learn knowledge show`, `update`, `set-field`, `delete` | `learn memory <same verb>` |
| `learn knowledge search` | `learn memory search` |
| `learn knowledge map`, `lint` | `learn memory map`, `lint` |

For a migrated bundle, `knowledge search --text` and `knowledge show` read the
unified store; `search` without `--text`, `map` and `lint` still read the bundle. `create`,
`update`, `delete` and `set-field` refuse and name the `memory` verb.

## Set up and migrate

1. Point the memory root at a subdirectory, never the repository top:
   `varde setup paths set --memory <agent-memory>/memory`. Check with
   `varde setup paths --json`. This command writes the user config; run it yourself.
2. Entries already under `<data>/varde/memory` are not moved by step 1. Move them by
   hand into the new root, or they vanish from the pointer.
3. Dry run, which writes nothing:
   `varde learn memory migrate --knowledge <bundle> --project-root <repo>`.
   It prints counts per type, collisions, secret rejects (only that file) and
   links. On the `varde-py` bundle it reports 29 files, 29 entries, 0 collisions.
4. Apply: add `--apply`. It writes the entries and a record in
   `<memory root>/.migrations/`. The bundle is never edited.
5. Undo: `varde learn memory migrate --knowledge <bundle> --undo` removes only the
   files in the record whose bytes still match (and lie under the memory root). It
   removes the record, then reads return to the bundle. If a changed file is
   skipped, the record is kept (listing only those files) so reads stay on the
   store; restore or delete the file and run `--undo` again.

While a record exists, `knowledge search --text` and `knowledge show` read only
the entries the record lists, so each fact appears once and another project's
notes never appear. `memory lint` exits 2 when it finds errors. `memory add`
applies the new-entry rules (a surfaced summary over 80 characters is an error);
use `--no-surface` for notes. Apply writes entries one by one, then the record;
a crash leaves entries without a record, and running `--apply` again finishes.

## Agent names at subagent start

SubagentStart exists on Claude Code (2.1.296) and Codex (0.162.1). Its payload
carries `agent_id` and `agent_type`, and `additionalContext` reaches the subagent.
`varde setup hooks install` registers it with SessionStart; the `memory` provider
gives the subagent its pointer. SessionStart carries `agent_type` on Claude Code only
for a session started with an agent, and never on Codex. Pi and opencode have no
SubagentStart: their subagents get no pointer.
