# Changelog

## Unreleased

- Add `runner.require_user_pairing` (default `false`) to optionally require the paired browser cookie and CSRF header for user-only writes; the dashboard reports changes as requiring a restart.
- Add the generic `node_host` runtime, per-engine package setup, configuration, and Linux portability checks.
- Add `startup_kill_timeout_s` (default the larger of 300 and
  `startup_timeout_s`, tunable per runner; `0` warns without killing) and `stall_after_s`
  (default 600) runner settings; report derived `liveness`,
  count only agent output as progress, and preserve and resend a launch prompt
  once after a silent restart.
- Let stop escape a held send lock and writer lease, and remove persisted native
  session specs when a session is archived while keeping them on stop.
- Add `varde-runner workspace create|list|remove` for native task worktrees.
- Make `varde-runner serve` work without environment variables: the mail relay starts by default (`VARDE_RUNNER_RELAY=0` or `off` disables it), and `allowed_hosts = [...]` in `runner.toml` is merged with `--allowed-host` and `VARDE_RUNNER_ALLOWED_HOSTS`.
- Use pi provider `deepseek` model `deepseek/deepseek-v4-flash` (reasoning high) as the built-in fallback instead of `opencode-go/deepseek-v4.1-flash`, whose key was reported expired.
- Keep OpenCode execution failures non-terminal, persist Pi runner identity across resume, and preserve launch errors when address cleanup fails.
- Set native child `VARDE_AGENT_ID` to the runner session ID and preserve runner binding identity during refreshes.
- Preserve address bindings across turn-level `session_end` events; unbind on terminal process failures.
- Make native mail-wake smokes use the checkout CLI and explicit files backends, expose relay logs, and record binding, pending-mail, and plan diagnostics on timeout.
- Add a native smoke `--mail-wake` mode that launches an addressed session, sends a message through the isolated runner mailbox, and records the wake reply.
- Record the Claude CLI real mail-wake PASS and clarify that real mail-wake turns for Codex, Pi, and OpenCode have not run.

- Keep the mail relay listening while plan reads or stall probes are slow: refresh plans and stall notices beside the wake wait with timeouts, bound the idle-status probe in wake delivery, report `waiting` once the relay is bound, and time out `plan watch` after 120 s.
- Open the runner port before the first plan watch runs, and serve the last orchestrator snapshot while a single shared refresh rebuilds it, and share one mailbox projection among concurrent requests, so polling requests no longer queue behind slow plan reads after a restart.
- Keep concurrent cold queue reads from starving the default executor, and degrade to empty plan rows when plan status is unavailable.
- Show a muted notice on Needs you when plan status or address bindings cannot be refreshed.
- Make `POST /api/jobs/{key}/run` return the running entry without waiting for the run; the Scheduled jobs page polls until the run finishes and a second Run now while a run is active starts nothing.
- Require interrupt-capable runner plugins to implement the interrupt protocol, and detect harness identifiers outside adapter and registry modules.
- Show unanswered design, choice, decision, and approval files from active plans as needs-you cards; record answers in the source file and notify the assigned orchestrator.
- Make queue reorder fast: `POST /api/queue/move` no longer rebuilds the full queue snapshot and now returns `{category, order}` (the new waiting order for that category) instead of the full snapshot; the Queue page updates optimistically and reconciles with the response.
- Add the `/api/agents` runner API to launch a native agent in an existing workspace (harness, workspace, role, prompt) and to prompt, interrupt, respond, resume, stop and archive it, plus `Supervisor.stop`, `archive`, `interrupt` and `resume`; `/api/agents/capabilities` now lists `disabled` harnesses. Harnesses stay off unless enabled in config; write routes need a writer client attached through the watch stream. No schema change.
- Let `/api/agents` optionally bind an orchestrator address slot and plan to the launched session, route relay wakes to its Supervisor session ID, and unbind the address when that session stops or archives.
- Change `runner.toml` to shared `[types.<name>]` model settings and `[roles.<name>] type = ...` mappings. Legacy per-role files still load only when each role exactly matches a built-in type; back up `runner.toml` before migrating.
- Add a Queue view (`/queue`) with one tab per queue, move the queue off the Plans page, and show each plan's mail thread on its detail page. Mail that has no plan (for example to main or guard-escalated prompts) appears as Needs you cards on Plans and opens at `/threads/<id>`; the Mail reliability soak card moved to Settings.
- Remove the Mailbox page and redirect old thread links to plan mail or standalone thread views.
- Let `Supervisor.send` accept an optional `request_id` passed by the relay as the action id; repeated ids return the original SENT outcome without resending, with idempotently created `send_admissions` records (no `user_version` change) pruned after 7 days.

- Add an opt-in scheduled learn review job with a configurable token budget, usage and coverage reporting, and a budget column and route for changing its budget.
- Track sweep warnings separately from failures in job state so oversized OpenCode sessions do not fail the sweep job.
- Show one primary plan per orchestrator, with additional assigned plans listed as `other_plans` beneath it.
- Share version-token-indexed plan reads per working directory instead of the two-second plan-list cache, and run orchestrator row assembly off the event loop.
- Add a permission guard that reviews pending permission requests, records each verdict (prompt and reason redacted), and escalates uncertain ones to you. The dashboard Guard card lists verdicts and approved patterns, and can revoke or restore a pattern (`/api/guard/verdicts`, `/api/guard/approvals`, `/api/guard/revoke`, `/api/guard/unrevoke`). The guard is a role in `runner.toml` (`[roles.guard]`: model, reasoning effort, `enabled`, off by default) editable on `/roles`. Adds runner store schema v5 (guard tables); back up `runner.sqlite3` before deployment.
- Attach to one agent with a snapshot-then-stream watch: `GET /api/agents/{id}/watch` (SSE) and `varde-runner watch <agent>`, which defaults to observer; `--writer` opts in to writer role. Observer write rejection applies to calls that present a client id; HTTP write routes, `newitem` and the IPC socket do not yet pass one. Add an `(session_id, seq)` events index without changing `user_version`, one in-memory writer lease per agent, and a Watch panel on the dashboard agent list.
- Ignore nested orchestrator timestamps, usage, and activity-age fields when deciding whether `/events` has a state change.
- Record a `decision_event` row (redacted request key, role, model, harness, mode, time to answer) for every permission request and decision card; permission requests are never auto-approved.
- Serve loopback-only decision metrics grouped by role, model, harness, request kind, card kind, or `group_by=day|week`.
- Compress dashboard responses, trim orchestrator agent payloads, add a lightweight needs-you count route, and log request timing.
- Page mailbox history in batches of 50 with a wrapped “Show older” control while keeping open decisions complete.
- Send compact `/events` topic change notices with keepalives instead of full dashboard snapshots.
- Run a daily mail-soak job (`VARDE_MAIL_SOAK_TIME`), serve the latest report at `/api/mail-soak`, and show a Mail soak card on the Plans page.
- Persist approval and wake waits in the runner SQLite store (schema v4). Pending approvals are re-presented and expired waits never auto-approve; wake delivery survives runner restarts. The Supervisor IPC exposes pending `waits` and the next `next_deadline`. Opening a v3 store migrates it to v4; back up `runner.sqlite3` before deployment.
- Record an ordered per-session event log with atomic event batches (`append_events`), `tool_intent` and `tool_result` events for Paseo tool calls, and a `resume` event naming tool calls that had no result after a restart. Store schema is now v4.
- Park sessions after `max_no_progress_restarts` (default 3, set in `runner.toml`) consecutive restarts with no new events, including idle sessions. A `parked` event records the reason; a later send resumes a parked or otherwise unresumed session and restores event logging.
- Show each plan's purpose when its dashboard card is expanded.

- Plans cards show "Blocked on you" with the reason for a plan awaiting the user (`awaiting_user`), instead of "Stalled".
- Bound graceful dashboard server shutdown when SSE clients remain connected, and report thread stacks if test servers fail to stop.
- Show plan labels on dashboard cards, queue and finished rows, and mail thread
  names, with group chips on Plans cards, queue and finished rows.
- Plans dashboard separates past orchestrators into a collapsed group, adds confirmed status requests for idle or stalled live plans, and cleans up plan card labels.
- Mailbox: threads open and reply with real ids, inactive items read-only with Dismiss, stale threads collapse under Older with "Dismiss all older than N days", `plan:<id>` threads show a plan chip, message bodies render as Markdown with a Recommended option tag and Sources, and the Open badge no longer wraps.
- Use four-tab navigation and one Plans page, group mailbox messages into threads, add planner model failover, rewrite Roles, add a Repository selector to New item, and add Status to Settings.
- Cache Queue snapshots with background refresh and prewarm; clamp queue row titles to two lines on mobile.
- Queue page shows the first five waiting plans per category with a "Show N more" control and a next-up summary, so long queues stay usable on a phone.
- Enumerate Queue plans from plan files so task-less backlog plans appear in their categories.
- Keep active plans out of waiting, count uncategorized activity in slots, and report hidden queue plans with filter reasons.
- Count bound idle orchestrators in category queue slots and seed categories for active plans.
- Add a Settings page (More menu) with app icon tiles that update the favicon and header logo live, and a Light/Dark/System theme section.
- Add selectable baked Liquid Glass app icons with server-side settings and live icon routes.

- Add realistic decision fixtures and an end-to-end CLI-to-mailbox answer test that verifies replies return as info messages.
- Add approval decision cards with fixed Approve, Hold and Ask more actions; preserve typed approval and hold notes, and require text for Ask more. Project decision evidence notes, remove sender-provided evidence URLs, and serve allowlisted files through the decision evidence route.
- Mobile Mailbox list now uses the same bordered rounded card as other pages, and the open search field no longer crowds the header.
- Add the Varde Runner app icon, browser and home screen icons, and web manifest.
- Correct Queue activity and slot counts, show uncategorized plans, and mark alphabetical queues when no priority has been set.
- Rework the mailbox thread: readable question, one row per option with Recommended and Your choice marks, and a separate Your reply block with sent time and delivery status.
- Add a mobile bottom tab bar (Orchestrators, Mailbox, Queue, More), shared Section and Row patterns used by Queue, and render plan text in the plan viewer as sanitised HTML.
- Split the Orchestrators page into a prominent Needs your attention group and a quieter Running group, and wrap status counts, tabs and option buttons instead of scrolling horizontally.
- Rework the Roles page for phones: one summary row per role that expands to a 2-column editor, numbered fallback rows with icon buttons, and a slim save bar with a short status toast.
- Remove the unused `mailman` role. An existing `[roles.mailman]` table in `runner.toml` still loads, is hidden from the Roles page, and is kept unchanged when saving.
- Handle queue category and delivery failures without returning 500 responses, count only active plans against slots, and keep dashboard plan reads off the event loop.
- Add category queues with persisted ordering, read-only plan details, and stored or delivered plan comments.
- Serve stale dashboard mailbox, plan, and binding snapshots while one background refresh runs, and refresh the mailbox after answers and acknowledgements.
- Cache dashboard inbox reads in-process, share short-lived plan and binding snapshots, and refresh Paseo agents in the background after the first load.
- Keep cached mailbox, orchestrator, and role data visible while each dashboard API refreshes independently.
- Dashboard UI craft: three button levels (primary, secondary, tertiary) at 44 px, one-row Mailbox toolbar with an overflow menu (group by sender, stale after, dismiss stale), 72 px two-line mail rows, a compact reader top bar and composer, an icon theme toggle, and a cleaner Orchestrators page.
- Retheme dashboard surface, border, text and accent tokens to match the dark reference while keeping light cards and controls clearly outlined.
- Redesign the dashboard on an internal component library
  (`runner/ui/src/lib/ui`): mail-client Mailbox, summary-strip Orchestrators
  overview, plain Roles and New item pages, 16 px form controls, dvh and
  safe-area layouts, and a pinned reply that stays above the on-screen
  keyboard. A lint test keeps page styles free of colors, font sizes and
  heights.
- Add the `varde-runner` Python module and loopback-only `varde-runner serve`
  dashboard entry point.
- Add plan-then-queue work items, a decision mailbox, runner registry and
  delivery layers, and role configuration editing.
- Define open mailbox items as unresolved needs-user messages with no later
  reply from the same sender, and add Show all for resolved items.
- Project mailbox messages added after startup through `GET /api/mailbox` and
  show context-free resolved rows with a fallback label.
- Start planner sessions lazily through a persistent supervisor and shut it
  down with the dashboard.
- Map runner role modes to Paseo modes and reject Codex read-only mode because
  Paseo has no equivalent.
- Accept plan-ready work-item events regardless of message kind, while still
  requiring needs-user for planner questions.
- Tell planners to send every message from their work-item address, including
  exactly one needs-user plan-ready message.
- Keep runner dependency rules limited to `varde-core` and lower-level runtime
  dependencies.
- Keep the Mailbox reader on the answered item after sending; show its delivered reply from server state.
