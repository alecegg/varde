# Plans read index

The runner and CLI can read plans from a derived SQLite snapshot. Markdown
plans, tasks, reviews, and auxiliary files remain the source of truth.

## Storage and refresh

- Database: `<working>/.cache/plans-read-index.sqlite3`.
- SQLite `user_version`: **6**.
- Contents: parsed plans/tasks, invalid-artifact markers, review verdicts,
  task-note and now-line mtimes, and per-plan activity. Raw Markdown is kept
  for record equality and compare-and-swap writes.
- Runner: serves the last published snapshot; a background thread refreshes
  the index and facts about every two seconds. Git facts use a refs-signature
  cache. Message/binding facts are reused until their store version changes.
- CLI: `open_fresh_plans()` refreshes inline; `open_indexed_plans()` opens the
  published snapshot without refresh.

To rebuild, delete the database. The next `refresh()` or
`open_fresh_plans()` recreates it; there is no dedicated rebuild command.
SQLite sidecars and the lock file under `.cache` are derived runtime files.

## Rollback and health

- Runner: set `VARDE_PLANS_BACKEND=files` to use files-backed plan readers.
- CLI/data: set `VARDE_DATA_PLANS_BACKEND=files`, select `plans = "files"` in
  `data.toml`, or call `open_plans(working, "files")`.
- Rollback changes the plans backend only. It neither removes the derived
  index nor switches unrelated SQLite stores (messages, work items, decisions).
- Dashboard `degraded_sources` includes `plan_reads` when index or supporting
  facts fail to refresh or become stale; the runner keeps its last good data.

The runner writes the database, lock, and sidecars below `<working>/.cache`.
Existing sandbox guidance permits runtime and derived caches in data-store
directories ([sandbox permissions](sandbox-permissions.md)); no new permission
is needed.

## Measured runner routes

Measured on 2026-10-24 with direct route calls on an isolated copy of the real
plan tree (268 plans, 1,127 tasks); the real tree was only read. Warm p95 is
over 50 calls.

Before (CLI subprocess readers, same machine): plan status 6.9 s, plan watch
2.0 s, first cold `/api/queue` 9.5-11.4 s, first cold `/api/orchestrators`
12.6 s, warm `/api/orchestrators` about 0.8 s, and 16 concurrent cold queue
requests did not finish in 45 s.

| Route | Persisted index: first / warm p95 | Deleted index: first / data ready |
| --- | ---: | ---: |
| `/api/orchestrators` | 63.9 ms / 0.01 ms | 0.1 ms / 1.434 s |
| `/api/queue` | 192.5 ms / 0.84 ms | 0.1 ms / 1.291 s |
| `/api/plans/<real plan>` | 10.2 ms / 12.46 ms | 0.5 ms / 1.176 s |

Status and watch collection takes about 20 ms each; a no-op index refresh about
0.2 s and a full rebuild 1-3 s, both off the request path. With a persisted
index, queue and plan detail return real data immediately. After index deletion,
queue and orchestrators return the empty last snapshot and plan detail returns
HTTP 503 until the rebuild publishes (1.2-1.4 s). Persisted and rebuilt API
bodies matched after ignoring clock and activity fields. The harness is
`runner/bench/plans_index/measure.py`.
