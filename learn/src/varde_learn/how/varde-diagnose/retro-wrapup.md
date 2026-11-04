---
topic: varde-diagnose/retro-wrapup
version: 1
summary: 3 of 3 - orchestrated-build wrap-up; run ID per harness, skip with a reason if none
---

# Orchestrated-build wrap-up

Orchestrated-build wrap-up. Find the run ID:

- Codex: `$CODEX_THREAD_ID`.
- Claude: the injected `varde session: <session-id>` line.
- OpenCode: use an ID supplied by the user, or skip with a reason.
- Pi: `diagnose` does not support it; skip with a reason.

1. Select the root and workers:

   ```sh
   varde learn sessions show --harness <codex|claude|opencode> --repository <repo-root> --run <session-id> --json
   ```
2. Freeze the orchestrator and workers with `--snapshot-out`. For a cutoff anchor, follow `references/diagnose-current.md` (Set a cutoff); use the first finish record to exclude later records.
3. Send the frozen evidence to the chosen analyst or analysts. Record retained candidates with `varde learn friction list`/`add` (load the learn skill and follow its capture route), tagged with run and session IDs.
