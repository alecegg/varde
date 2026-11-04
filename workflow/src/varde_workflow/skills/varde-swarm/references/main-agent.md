# Main-agent relay

Outcomes and how to validate each:

- Decisions and approvals reach the owning orchestrator as one `varde msg send --to <plan id> --kind info`; an orchestrator proceeds only after an `info` naming the approved action, or main relays `needs-user`.
- A handed-off orchestrator is archived and replaced by a launch that carries its slot and plan. Validate: the replacement resumed via `varde plan slot resume`.
- Every launched orchestrator carries its address marker, so its messages reach main.
- Main's own address is superseded on a fresh main session. Validate: `varde msg migrate` ran once.
- Test requests go to the owning orchestrator or worker; main runs no tests.
- Active orchestrators have a watcher, and idle rounds are skipped. Validate: `varde plan watch` is running; `varde plan pulse` reports all active plans in one call.
- Session notes are refreshed on token nudge, compaction or request; on a nudge the user is told to `/compact` and the session continues.
- Every nudge to an idle or stalled agent is recorded with `varde msg nudge --to <slot> --reason stalled|idle-unread|other`.
- User questions go to the dashboard Mailbox, not chat; replies are `APPROVED[: text]`, `HOLD[: text]` or `ASK-MORE: <text>`, with chat as the fallback when the dashboard is unavailable.
- `plan watch` reports plan state only, not reports. The `stalled` event is a 10-minute heuristic on slot-binding activity.
