# Message store cutover runbook

Main owns the backups, mode changes, and restarts.

## Gates and behavior

- `msg_soak.gather` compares a mirrored store and adds a `parity` criterion to
  the soak report (nothing on `files` or `sqlite`). Fewer than the required
  comparisons is `no-data` and fails; require at least one compare and zero
  divergence, lag, and mirror failures throughout a three-day soak. The
  comparison window is the soak's `--window-days` value. `compare()` drains
  pending mirror writes first, so a repairable difference is recorded as lag,
  not divergence; the gate still requires zero lag. Periodic comparison is not
  scheduled; the operator or a soak run triggers it.
- The runner dashboard signature includes the SQLite store's
  `repository.version()` (it opens the store itself when none is passed), so
  mail that sits in the `-wal` file still changes it. Check that new mail
  refreshes the dashboard during the mirror soak.
- `set_store_mode(working, mode)` allows only adjacent transitions:
  `files` -> `mirror-files` -> `mirror-sqlite` -> `sqlite`. There is no
  `varde msg store mode` CLI command. Use the data API shown below for each
  transition. Each flip takes the exclusive mode lock and updates the mode
  marker and database metadata. A flip out of a mirrored mode also drains
  pending writes and verifies both stores while holding the lock; a flip from
  an unmirrored mode has no prior mirror to verify. Repository opening takes the
  shared mode lock, so readers wait for a flip for at most their `busy_timeout`
  (2 seconds in the prompt hook). A timeout raises `Locked`, which the hook
  treats as an empty inbox for that prompt.
- SQLite uses WAL and `synchronous=FULL`. On macOS this code path uses SQLite's
  fsync behavior and does not request `F_FULLFSYNC`. WAL readers also need write
  access to `.cache/inbox` so SQLite can create and update `-wal` and `-shm`.
  Keep the current harness directory grants.
- The hook latency ceiling is 70 ms for SQLite and mirror-sqlite. A generated
  live-shaped fixture (3,067 messages, 32,744 deliveries, reader at start, three
  new unread) measured fresh-process open-plus-claim medians of 49.7 ms for
  SQLite, 48.1 ms for mirror-sqlite, 64.4 ms for files, and 65.9 ms for
  mirror-files (five samples per mode). All measured modes were below 70 ms.
  cProfile showed the files and mirror-files paths make the same history-related
  calls, with no extra mirror-side history scan. SQLite's claim query uses the
  `deliveries(reader,message_id,event)` index and does not materialize delivery
  history. These are generated-fixture measurements, not a copied live inbox.

Resolve the working directory and define a helper for the supported API
transition. Run these commands from the repository root with the current
checkout installed in the `uv` environment:

```sh
export VARDE_WORKING="$(uv run varde setup paths --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["working"])')"
set_store_mode() {
  uv run python -c 'import os,sys; from pathlib import Path; from varde_data.store_mode import set_store_mode; set_store_mode(Path(os.environ["VARDE_WORKING"]), sys.argv[1])' "$1"
}
```

`varde msg store` supports `import`, `sync`, `verify`, and `export`; the parser
accepts `--from {files,sqlite}`, `--to {files,sqlite}`,
`verify --repair-mode [--force-adopt]`,
and `export --dest PATH`. The workflow help snapshot currently has no
`msg store` route, so check these arguments against the workflow parser when
the CLI changes.

## Cutover

1. **Main: back up the inbox and runner databases.** Choose an empty backup
   directory and set `BACKUP` to its absolute path. Copy the non-database inbox
   files and marker, excluding
   `messages.sqlite3`, `messages.sqlite3-wal`, and `messages.sqlite3-shm`:

   ```sh
   export BACKUP="/absolute/path/to/backup"
   mkdir -p "$BACKUP/inbox" "$BACKUP/dashboard/decisions"
   rsync -a --exclude='messages.sqlite3*' "$VARDE_WORKING/.cache/inbox/" "$BACKUP/inbox/"
   ```

   If the message database exists, make its consistent backup with SQLite:

   ```sh
   sqlite3 "$VARDE_WORKING/.cache/inbox/messages.sqlite3" ".backup '$BACKUP/inbox/messages.sqlite3'"
   ```

   For each existing runner database (`.cache/dashboard/runner.sqlite3`,
   `.cache/dashboard/inbox.sqlite3`, `.cache/dashboard/workitems.sqlite3`, and
   `.cache/dashboard/decisions/decisions.sqlite3`), use the same command
   pattern and preserve its relative path under `$BACKUP/dashboard/`:

   ```sh
   sqlite3 "$VARDE_WORKING/.cache/dashboard/runner.sqlite3" ".backup '$BACKUP/dashboard/runner.sqlite3'"
   ```

   Never copy a live WAL database and its sidecars as ordinary files. An
   alternative is SQLite `VACUUM INTO` on each database.

2. **Main: import the legacy files.** Run `varde msg store import`. Require exit
   code 0, matching source and target counts, `skipped=0`, `torn-tail=0`, and no
   mismatch lines. Resolve malformed or torn source records before proceeding.

3. **Main: enable the files-primary mirror, then close the import gap.** Run
   `set_store_mode mirror-files` using the helper above, then immediately rerun
   `varde msg store import`. Require the same clean report. This second import
   replays messages written between the first import and mirror activation.

4. **Main: soak for at least three full days in `mirror-files`.** Run
   `varde msg soak --window-days 3 --write --json` daily. Require every criterion
   to pass, including the parity gate described above, and at least one
   comparison per report. A missing parity result is not a pass.

5. **Main: drain, verify, restart, then switch the primary.** Run
   `varde msg store sync` and `varde msg store verify`; require exit code 0,
   zero skips/torn tails, equal counts, and no mismatches. Restart the
   long-lived runner and relay processes so they close files-primary
   repositories. Then run `set_store_mode mirror-sqlite`. The mode flip drains
   and fully verifies the mirror while holding the exclusive mode lock.

6. **Main: verify the harness path manually in `mirror-sqlite`.** Repeat this
   check for each bound Codex, Pi, OpenCode, and Paseo worker address. Set
   `ADDRESS` to that bound address and use a unique check ID. Main sends:

   ```sh
   varde msg send --from main --to "$ADDRESS" --kind info "sqlite-check/$ADDRESS/<unique-id>"
   ```

   In that harness, read the message and reply:

   ```sh
   varde msg read --as "$ADDRESS"
   varde msg send --from "$ADDRESS" --to main --kind info "sqlite-check-reply/$ADDRESS/<unique-id>"
   ```

   Confirm every reply at `main`. Exercise the prompt hook by delivering one
   message during a prompt, the plain CLI by running its read and send commands
   in that harness, and the runner relay by confirming one normal delivery.
   This checks database open, read, and write under each consumer's actual
   sandbox.

7. **Main: finish the cutover after the rollback window.** Run
   `set_store_mode sqlite`. This adjacent flip drains and verifies the files
   mirror before disabling it. Keep the backups until the rollback window
   closes.

## Rollback

1. **Main: stop long-lived message writers.** This prevents a process holding a
   plain SQLite repository from writing during the rollback copy and mode
   transitions.
2. **Main: refresh and verify the files store.** Run
   `varde msg store sync --from sqlite --to files`, then
   `varde msg store verify --from sqlite --to files`. Require exit code 0,
   zero skipped/torn-tail rows, equal counts, and no mismatches.
3. **Main: return through the adjacent modes.** If the current mode is `sqlite`,
   first run `set_store_mode mirror-sqlite`. From `mirror-sqlite`, run
   `set_store_mode mirror-files`, then `set_store_mode files`. If already in
   `mirror-files`, go straight to `files`. Each flip out of a mirrored mode
   drains and verifies both stores; flips from an unmirrored mode do not.
4. **Main: restart the runner and relay processes** after the final files-primary
   mode is active. Confirm a hook claim and one CLI read/send before declaring
   rollback complete.

If mode metadata is interrupted, stop writers and run
`varde msg store verify --repair-mode`; verify the mode again before resuming.
