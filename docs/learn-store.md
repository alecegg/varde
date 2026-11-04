# Learn store

The learn root (`~/.config/varde/learn`, or `VARDE_LEARN_STORE`) keeps three
machine-managed domains that can live in files or in one SQLite database,
`<learn root>/learn.sqlite3`:

| Domain | Files | Tables |
| --- | --- | --- |
| `friction` | `friction.jsonl` (plus the rebuildable index `learn.db`) | `friction_events` |
| `ledger` | `analyzed.jsonl`, `digests/DATE.json` | `analyzed`, `digests` |
| `calls` | `cli_calls.jsonl` | `cli_calls` |

Every domain starts on `files`. `sweep.toml`, `review.toml`, the review ledger
and all Markdown documents stay files and are not part of this store.

## Commands

```text
varde learn store status [--domain D] [--json]
varde learn store migrate --domain D [--dry-run] [--json]
varde learn store verify  --domain D [--json]
varde learn store retire  --domain D [--json]
varde learn store prune   --domain calls [--days N] [--dry-run] [--vacuum] [--json]
```

`D` is `friction`, `ledger` or `calls`. `status --json` returns
`{"database", "generation", "domains": {D: {"mode", "rows", "files_present"}}}`
in the usual envelope.

## Calls retention

`varde learn store prune --domain calls` deletes call rows whose parsed `ts`
is older than both the window and the watermark. The window is `--days N` or
`[retention] calls_days = N` in `sweep.toml` beside the learn store (default
30; a non-positive or non-integer value is an error). The watermark is the
meta key `calls_used_through`: `varde learn sessions calls` and `varde learn skills demand`
each raise it to the latest `ts` they ranked, and it never
lowers. With no watermark nothing is deleted. Prune refuses unless `calls` is
on `sqlite` and while `cli_calls.jsonl` still exists (run `retire` first).
Deletes run in batches of 5000, each committed on its own, so appends keep
working. `--dry-run` counts only; `--vacuum` shrinks the file afterwards.
`status` shows the watermark and the oldest `ts`, so a store that no report
advances (and so never prunes) is visible. The daily `varde learn sessions sweep`
prunes after its analysis and reports `calls_pruned`; a prune failure is a
warning. A report window longer than `calls_days` prints a warning and adds
`retention_days` to the envelope meta; `sessions calls --dead` refuses such a
window. `setup watch` and `plan watch` calls are not recorded.

## Switch order

Each domain flips alone; any order works and a mixed store is normal.

1. `migrate --dry-run` reports what would be imported (and calls lines that
   would be skipped).
2. `migrate` takes the exclusive store lock, imports from the files
   idempotently, writes an online backup of the new database
   (`learn.sqlite3.friction-backup`, `.ledger-backup` or `.calls-backup`),
   verifies logical parity, and only then flips that domain in
   `store-mode.json` and bumps its generation. Source files are not touched.
   The flip also appends `learn.sqlite3*`, `store-mode.json` and
   `store-mode.lock` to an existing `.gitignore` in the learn root; it never
   creates one.
3. `verify` checks that the files are still a prefix of the sqlite rows (same
   content, and for friction the same numeric IDs). Rows written after the flip
   do not fail it.
4. `retire` runs `verify` again and then removes the old files. For friction it
   also removes `learn.db`, its init lock and its ID map. For calls it first
   saves lines that were never imported to `cli_calls.skipped.jsonl` and
   removes the calls backup.

## No rollback

Migration is one-way. There is no export or rollback command. The old files are
the backup until `retire`; after `retire` the database is the only copy. A
`migrate` that fails part way leaves imported rows in the database and the
mode on `files`; rerunning is safe.

Friction `retire` also removes a torn last line of `friction.jsonl`, which
replay ignores anyway.

## Writers and flips

`store-mode.lock` and its shared lock apply to files-mode writes too, so a
0-byte `store-mode.lock` appears after any files-mode append, even in a store
that was never migrated.

A flip holds the exclusive lock `store-mode.lock` for backup, import, verify
and marker write. Writers on `files` take the shared lock for each write and
are refused if the marker moved their domain to `sqlite`; they never write to
the old files after the flip. A long-running process reopens the repository
(`open_friction`, `open_ledger`, `open_calls` follow the marker) to continue.
`append_call` never changes a command's outcome: a refused or failed append
returns false, increments the drop count and adds one line to
`cli_calls.dropped.log` (capped at 1 MB).

## Notes from the real-store gate

`learn/tests/loop/test_store_real_copy.py` migrates, verifies, writes after the
flip and retires each domain of a copy of a real learn root
(a manual, opt-in check that skips when the variable is unset; the same
scenario always runs on generated data in the synthetic tests of that module).
Run it with a copy of the real root:

```text
cp -R ~/.config/varde/learn "$TMPDIR/learn-copy"
VARDE_LEARN_REAL_COPY="$TMPDIR/learn-copy" uv run pytest learn/tests/loop/test_store_real_copy.py -q -s
```

It works on a second copy, so the named copy is not modified. Measured on
the 2026-10-30 store (1,368 friction events, 1,615 ledger rows, 234,442 calls):

| Domain | migrate | verify | retire | first write after flip |
| --- | --- | --- | --- | --- |
| friction | 0.06 s | 0.04 s | 0.04 s | 18 ms |
| ledger | 0.16 s | 0.07 s | 0.07 s | 1.6 ms |
| calls | 3.2 s | 1.4 s | 3.1 s | 1.0 ms |

- A stale `learn.db` blocks friction `migrate` (its ID map would be lost) until
  `varde learn friction list` refreshes it.
- The first `record_firing` call in a fresh process opens the store per call
  and costs about 17-27 ms (about 0.4 ms before); a warm calls append is about
  0.6 ms.
- `SqliteFrictionIndex` (`learn.db`) stays because friction on `files` still
  reads it; it is only unused once friction is on `sqlite`.

## Permissions

Agents need read and write access to the whole learn root: `learn.sqlite3`,
its WAL and shared-memory sidecars, the `*-backup` files, `store-mode.json`
and `store-mode.lock`. See [sandbox permissions](sandbox-permissions.md).
