# Multi-session retrospective

Use this to identify agent-environment improvements supported by session evidence. Compare root sessions; workers add context but do not count as separate sessions.

## Outcomes

- Compare recent top-level sessions for the repository (default five, `--limit` 1 to 10) for recurrence. Freeze each selected root and its listed workers with a unique private `--snapshot-out` path.
- Analysts get frozen bundles by default (redacted transcripts are also allowed). Each analyst brief starts with the literal first line `varde-retro-analyst`; `diagnose list` filters sessions whose first user record starts with that marker.
- Analysts report environment improvements by category: navigation, automated checks, steering bloat, no-op instructions, tool economy, information access.
- A mechanical finding yields a proposed check; a judgment call yields proposed guidance.
- Candidates are kept only when seen in at least two distinct root sessions, or labelled high-severity single-session.
- The orchestrator records retained candidates as friction; no skill or code edits come from a single run.
- Option and audit rules in `references/options.md` apply.

## Orchestrated-build wrap-up

Optional after an orchestrated run reaches finish when at least one worker was dispatched or any worker was redispatched. Blocked runs wait for a later multi-session retrospective.

- The run ID is the harness session ID:
  - Codex: `$CODEX_THREAD_ID`
  - Claude: the injected `varde session: <session-id>` line
  - OpenCode: a user-supplied ID, else skip with a reason
  - Pi: unsupported; skip with a reason
- Select the root and workers with `sessions show --run <session-id>` then freeze with `--snapshot-out`.
- When a cutoff anchor is needed, follow [`diagnose-current.md`](diagnose-current.md) (Cutoff); the first finish record excludes later records.
- Retained candidates are recorded as friction, deduplicated and tagged with run and session IDs; no skill or code edits come from this single run.
