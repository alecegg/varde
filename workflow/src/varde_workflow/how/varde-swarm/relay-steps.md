---
topic: varde-swarm/relay-steps
version: 1
summary: Relay, watchdog, nudge, session notes and dashboard-reply commands for main
---

## Main-agent relay steps

- Relay user decisions and approvals with `varde msg send --to <plan id> --kind info`.
- Start `varde plan watch` when active orchestrators lack a watcher. Use `varde plan pulse` with no argument as the watchdog, and skip the round when idle. Use `varde plan watch` for events rather than periodic status calls, and relay each decision with one `info` message.
- Refresh session notes on token nudge, compaction, or request (`varde-knowledge` session-notes-write).
- Each time you nudge an idle or stalled agent, run `varde msg nudge --to <slot> --reason stalled|idle-unread|other` (stalled: `plan watch` stalled event; idle-unread: unread mail).
- Do not re-ask in chat; direct the user to the dashboard Mailbox. Handle replies as `APPROVED[: text]`, `HOLD[: text]`, or `ASK-MORE: <text>`.
