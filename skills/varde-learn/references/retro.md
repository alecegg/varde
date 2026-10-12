# Multi-session retrospective

Use this to identify agent-environment improvements supported by session evidence. Compare root sessions; workers add context but do not count as separate sessions.

## Sample and freeze

1. List recent top-level sessions for the repository:

   ```sh
   varde learn diagnose list --harness all --repository <repo-root> --json
   ```

   The default is five sessions, newest first; `--limit` accepts 1 to 10.

2. Compare roots for recurrence, then freeze each selected root and its listed workers with unique private paths:

   ```sh
   varde learn diagnose inspect --harness <codex|claude|opencode> --session <session-id> --snapshot-out <private-new-path>/bundle.json --json
   ```

3. Give analysts frozen bundles by default for repeatability; transcripts may also be shared with analysts after redaction. Start each analyst brief with the literal first line `varde-retro-analyst`. `diagnose list` filters sessions whose first user record starts with that marker.

## Analyze bundles

Choose analyst count and model to fit each bundle's complexity. Ask for environment improvements in relevant categories:

- **Navigation**: Use when finding files or dependencies took too long.
- **Automated checks**: Use when a mistake could have been caught, or an existing check is unwired or broken.
- **Steering bloat**: Use when long or repeated instructions consume attention.
- **No-op instructions**: Use when steering text does not change behavior.
- **Tool economy**: Use when calls were expensive or repetitive.
- **Information access**: Use when needed evidence was unavailable.

- Mechanical finding: propose a check. Judgment call: propose guidance.
- Keep candidates seen in at least two distinct root sessions, or label a high-severity single-session finding.
- The orchestrator records retained candidates as friction; make no skill or code edits from a single run.
- Apply the option and audit rules in `references/options.md`.

## Orchestrated-build wrap-up

Use this optional review after an orchestrated run reaches finish when at least one worker was dispatched or any worker was redispatched. Leave blocked runs for a later multi-session retrospective. Find the run ID as follows:

- Codex: `$CODEX_THREAD_ID`.
- Claude: the injected `varde session: <session-id>` line.
- OpenCode: use an ID supplied by the user, or skip with a reason.
- Pi: `diagnose` does not support it; skip with a reason.

1. Select the root and workers:

   ```sh
   varde learn diagnose list --harness <codex|claude|opencode> --repository <repo-root> --run <session-id> --json
   ```

2. Freeze the orchestrator and workers with `inspect --snapshot-out`. For a cutoff anchor, follow [`diagnose-current.md`](diagnose-current.md) (Set a cutoff); use the first finish record to exclude later records.
3. Send the frozen evidence to the chosen analyst or analysts. The orchestrator records retained candidates as friction using `references/capture.md` for deduplication and recording, tagged with run and session IDs. Make no skill or code edits from this single run.
