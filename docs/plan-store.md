# Plan state store

The plan store keeps queue items and plan/task workflow state in SQLite while
keeping Markdown as the editable and versioned representation. The database is
shared by code worktrees for the same working directory:

```
<working>/.cache/data/queue.sqlite3
```

`<working>` is the Varde memory working directory containing `plans/`. Unless
configured, it is `<data>/varde/projects/<name>-<hash>/working` (`<data>` is
`$XDG_DATA_HOME` or `~/.local/share`). Grant agents read and write
access to the whole `.cache/data/` directory. SQLite may create WAL sidecars;
mode coordination and queue writes also create lock files there.

## Commands

Run commands from a directory where Varde resolves the intended working tree.
The supported commands are:

```text
varde plan store status
varde plan store migrate
varde plan store import
varde plan store export
varde plan store verify
varde plan store backup
varde plan store restore <backup>
varde plan store rollback
```

Every command accepts `--json`. `migrate`, `import`, `export`, `backup`,
`restore`, and `rollback` also accept `--dry-run`. `status` reports the active
mode, database path, schema version and row counts when a database exists.

## Migration and daily operation

1. Run `varde plan store migrate --dry-run` to inspect verification differences
   and any unsupported queue formats or skipped task state.
2. Run `varde plan store migrate`. It imports recognized pipe-table queues,
   `notes/queue.md` line queues, plan frontmatter and task state. Unknown queue
   formats are reported and not imported; task files without recognized state
   frontmatter are reported as skipped. Existing queue IDs duplicated across
   queue files cause a conflict. If a database already exists, migration
   creates and verifies a backup first. It verifies the import before switching
   the stored mode to `sqlite`. Markdown files remain in place.
3. In SQLite mode, state operations use the database. `import` brings Markdown
   queue and plan/task state into the database. `export` writes the stored state
   to the Markdown files represented in the store. `verify` compares stored
   state with Markdown and reports differences; it does not repair them.

For line queues, migration stores task names as namespaced IDs and retains
unknown `key:value` fields and unchanged source lines. `varde plan queue check`
in SQLite mode reads the line queue from the store and requires the supported
strict line format; rows imported from looser formats are reported as invalid
by the check.

The queue metadata records hashes from exports. When a later import finds a
different hash, a hand-edited Markdown state field is imported as a state
transition with source `markdown`. Export projects database state back into
Markdown, so review reported differences before exporting over edits.

## Backup, restore and rollback

`backup` uses SQLite's online backup API and verifies database integrity,
schema and row counts. It writes a timestamped `.sqlite3` file and JSON
manifest under `<working>/.cache/data/backups/`; the newest ten backups are
retained. Migration backs up an existing database before changing it.

Restore a verified backup with:

```text
varde plan store restore <working>/.cache/data/backups/queue-<timestamp>.sqlite3
```

Restore validates the manifest, checksum, integrity, schema, row counts and
supported schema version. If a database already exists, restore saves that
database and its manifest beside it with a `.pre-restore` name (adding a number
if needed), then installs the backup. It holds the exclusive mode barrier
during restore.

`rollback` exports the store state to queue and plan/task Markdown, verifies
the result, then switches the stored mode to `markdown`. It creates a fresh
verified backup before export. After rollback, Markdown is authoritative and
the database remains available for a later migration.

## Mode lock and barrier

Every operation that reads or writes plan, task or queue state takes a shared
lock at `<working>/.queue.mode.lock`, then reads the active mode.
Migration, rollback and restore take the exclusive lock across their mode
transition work. They wait for in-progress operations to finish, and new
operations wait until the transition completes. This prevents a state write
from crossing the mode flip. Lock waits time out and are reported as errors;
retry after the competing operation finishes.

Queue database writes also coordinate through
`<working>/.cache/data/queue.lock`. Migration records the schema version at
`<working>/.cache/data/queue.version`. Plan frontmatter writes use each plan's
`.plan.lock`. Keep the working root and parent directories writable so lock
files, SQLite journal/WAL files, backup files, manifests and atomic-write
temporary files can be created.
