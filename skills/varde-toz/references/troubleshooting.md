# Troubleshooting varde-toz

## Sandbox

- **No `[sandbox]` section:** `run` inherits the launching shell's
  permissions, so `vardeToz.exec()` can launch arbitrary commands; a harness
  sandbox still covers them.
- **`[sandbox]` present** (unless `enabled = false`): Seatbelt (macOS) or
  Bubblewrap (Linux) with workspace read/write and no network by default; `run`
  fails if the backend cannot start. Use `run` only for commands within its
  grants, and the harness tool otherwise.

## Troubleshooting

- **macOS `sandbox_apply: Operation not permitted`:** retry with host sandbox
  escalation when available.
- **Missing handle, failed retrieval, or apparent truncation:** run
  `varde-toz doctor --json` and report the command, handle, expected result,
  and actual result. Share tool output only when needed to reproduce it.
- **Store access error:**
  1. Retry the same command with harness escalation when available.
  2. If still denied, tell the user the failing command, store path, and
     granting sandbox or permission setting, and ask whether to grant it.
  3. Only after they decline and choose a fallback, set
     `VARDE_TOZ_FALLBACK_DIR` in the harness launch environment and restart
     the harness so its hooks receive it. Use the same directory for `query`
     and `run` (or `--fallback-dir`); keep fallback prefixes off normal calls.

  A fallback cannot recover captures a failed hook never saved.

