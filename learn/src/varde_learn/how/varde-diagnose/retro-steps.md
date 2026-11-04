---
topic: varde-diagnose/retro-steps
version: 1
summary: 1 of 3 - sample root sessions, freeze each; analyst brief starts varde-retro-analyst
---

Sample and freeze:

1. List recent top-level sessions for the repository:

   ```sh
   varde learn sessions show --harness all --repository <repo-root> --json
   ```

   The default is five sessions, newest first; `--limit` accepts 1 to 10.
2. Compare roots for recurrence, then freeze each selected root and its listed workers with unique private paths:

   ```sh
   varde learn sessions show --harness <codex|claude|opencode> --session <session-id> --snapshot-out <private-new-path>/bundle.json --json
   ```
3. Give analysts frozen bundles by default for repeatability; transcripts may also be shared after redaction. Start each analyst brief with the literal first line `varde-retro-analyst`.
