---
topic: varde-manage/runner-commands
version: 1
summary: What varde runner off, on, and status do to config and the service
---

`[runner] enabled` in `config.toml` (env `VARDE_RUNNER_ENABLED` =
`1|true|0|false` overrides it) defaults off.

- `varde runner off`: write false, then `varde-runner service stop` (skipped
  with a note when the executable or service is absent).
- `varde runner on`: `varde-runner service start`, then write true only if the
  start succeeded; on failure the key is unchanged and the exit is 1.
- `varde runner status`: effective value and source (env, file, default), a
  warning when env disagrees with the file, then service status (read-only).
- `varde-runner service install|start` writes true when the key is absent; an
  explicit false is kept.
- While off, the prune guard names main by its primary checkout; a due
  checkpoint still blocks Stop.
