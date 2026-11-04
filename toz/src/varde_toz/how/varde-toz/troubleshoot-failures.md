---
topic: varde-toz/troubleshoot-failures
version: 1
summary: Toz failures and store access errors, part 2 of 2, ask the user before any fallback
---

## Failures

- macOS `sandbox_apply: Operation not permitted`: retry with host sandbox escalation when available.
- Missing handle, failed retrieval, or apparent truncation: run `varde setup doctor --json`. Report the command, handle, expected result, and actual result. Share tool output only when needed to reproduce the failure.
- Store access error:
  1. Retry the same command with harness escalation when available.
  2. If still denied, tell the user the failing command, store path, and granting sandbox or permission setting, and ask whether to grant it.
  3. Only after they decline and choose a fallback, set `VARDE_TOZ_FALLBACK_DIR` in the harness launch environment and restart the harness so its hooks receive it. Use the same directory for `query` and `run` (or `--fallback-dir`); keep fallback prefixes off normal calls.
- A fallback cannot recover captures that a failed hook never saved.
