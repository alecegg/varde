# Workflow commands

## Pull-based role queues

Role queue commands are available as `varde plan queue <action>`. They use
`roles/global` by default; pass `--queue roles/<plan-id>` to operate on a
plan-specific queue. Outputs are JSON; add `--json` for the standard Varde JSON
envelope.

```sh
varde plan queue pull --role builder --slot SLOT_ID --epoch EPOCH
varde plan queue renew --slot SLOT_ID --epoch EPOCH
varde plan queue finish --item ITEM_ID --slot SLOT_ID --epoch EPOCH --outcome done
varde plan queue release --item ITEM_ID --slot SLOT_ID --epoch EPOCH
varde plan queue status
varde plan queue metrics
varde plan queue enqueue --plan-dir PATH --id ITEM_ID --role builder --owned-file PATH
```

`pull` claims the next eligible item for the role and slot. The slot epoch
fences claims and later operations. `renew` renews the slot's claimed items;
`finish` records the outcome and may return a follow-up item; `release` returns
the selected item to its queue. `status` reports per-role queued, claimed, and
ready counts, blocking reasons, and the resource budget. `metrics` reports
queue timing metrics. `enqueue` accepts repeatable `--owned-file`,
`--depends-on`, and `--serialize-with` options; `--kind` defaults to `build`.
All actions accept `--queue` and `--json`.

New starts require a resource snapshot at
`<working>/.cache/data/resources.json`; a missing or stale snapshot blocks
pulling. The runner serves a read-only queue summary at
`GET /api/queue/roles` when the SQLite queue store is active.

`varde plan queue pull`, `varde plan queue status`, and the
`GET /api/queue/roles` endpoint read `[queue_budget]` from the same file,
`$VARDE_RUNNER_CONFIG_DIR/runner.toml` (default
`~/.config/varde/runner.toml`). They do not read
`$VARDE_CONFIG_DIR/config.toml` for limits.

`provider_max` is optional. `rss_mb_max`, `cpu_pct_max`, `processes_max`, and
`global_worker_ceiling` are required; when one is missing or has the wrong
type, new starts are blocked and the reason is
`budget config invalid: queue_budget.<key>`. Without a `[queue_budget]` table
at all, both use the same built-in limits, which do not block starts on
resources and cap live workers at 24: no provider limits, `rss_mb_max`
1000000, `cpu_pct_max` 100000, and `processes_max` 100000.

```toml
[queue_budget]
provider_max = { anthropic = 0.8 }
rss_mb_max = 4096.0
cpu_pct_max = 90.0
processes_max = 500
global_worker_ceiling = 24
```

`provider_max` maps provider names to maximum usage fractions. `rss_mb_max`,
`cpu_pct_max`, and `processes_max` limit sampled runner resources.
`global_worker_ceiling` limits live workers; the snapshot's `live_workers` at
or above it blocks new starts.
