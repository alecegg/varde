# Changelog

## Unreleased

- Add the `learn.sqlite3` backends for friction events, the session ledger with digests, and the new `CallsRepository`, the per-domain `store-mode.json` switch with a flip lock, and `open_calls`; `open_friction` and `open_ledger` follow the marker.
- Add the session ledger repository (`analyzed.jsonl` and digests) and a validated `sweep_config` parser for `sweep.toml` (not yet used by learn).
- Preserve runner binding identity when a refresh supplies a different agent ID; allow refreshes from the bound runner ID.
- Add the address repository for bindings, tokens, slots, address events, and
  relay state, including `.events.lock` and `slots/.lock` coordination.
- Add the SQLite plan state store for queues and plan/task workflow state, with
  Markdown import/export, migration, backup, restore and rollback, coordinated
  by the working-root `.queue.mode.lock` barrier.
