# Changelog

- Match message acknowledgements and delivery checks across reader aliases.
- Preserve a torn final message line when a later append supplies its newline
  prefix, instead of discarding it as incomplete.
- Persist concluded addresses in `.cache/inbox/state.json` and read them as a
  union with addresses in `relay/state.json`.

## Unreleased

- Remove the `varde-mailman` skill; receipt states now appear in `varde msg show --help`. Sync drops the retired skill from saved `[sync].skills` with a warning and removes its installed copies when varde owns them.
- Run the Claude `varde-explorer` on `haiku`; sync moves installed explorers still on the shipped `sonnet` default and keeps user-edited models.
- Slim `varde-swarm` references: drop text duplicated between SKILL.md, main-agent and orchestrate references.
- Make `varde-swarm` opt-in: skills, shared references, docs and the main-agent brief no longer route several plans to it; run them one at a time with `varde-orchestrate` or ask the user. An empty `varde-swarm` invocation still reports status.
- Builder finish no longer enqueues reviewer items in pipeline mode (reviewer `findings` still enqueue one builder fix); remove the specialist reviewer routing module.
- Route runner relay and address storage through the shared data layer, with a
  retained CLI rollback adapter for relay commands.
- Reduce orchestrator and main polling and acknowledgement turns with pulse-based watchdogs and batched milestone messages.
- Add read-only `varde plan pulse` for batched plan, mail, decision-file, event,
  and worktree state with idle-round detection.
- Bind and refresh native wake records with `agent_id`, runner `harness` and optional `runner_endpoint` from `VARDE_AGENT_ID`, `VARDE_HARNESS` and `VARDE_RUNNER_ENDPOINT` (while still reading legacy `paseo_id`); add native mailman guidance for runner-delivered wakes and LLM confirmation of `failed` or `no-send` outcomes.

- Define 200k orchestrator handoffs and main's replacement and compaction response.
- Plan Markdown write commands may return `plan_conflict` when content changed
  or `plan_locked` when the per-plan `plans/<plan>/.plan.lock` lock times out
  after 5 seconds. Conclude now patches only the plan status field.
- Add `varde msg nudge` (logs a main nudge to `nudges.jsonl`) and `varde msg soak [--write] [--json]`, which evaluates the mail-reliability sunset criteria over a rolling window and writes a daily report under `metrics/mail-soak/`.
- Shorten varde-orchestrate, varde-build, varde-swarm, varde-plan and varde-review text where a `varde` command already performs the steps.
- Include the first sentence from a plan's Problem section in status JSON.

- Expose unanswered user requests in plan status and suppress stalled or stale
  notices while an assigned orchestrator awaits a reply; include `awaiting_user`
  in `varde plan watch --json` records.
- Add plan `label` (2–4 words) and `group` frontmatter. `varde plan status`
  exposes `label` and `group_name` (inherited from the nearest ancestor plan),
  and `varde plan validate` warns when either is missing.
- Report sibling plan ownership overlaps as warnings in `varde plan readiness`.
- Add the `varde-mailman` skill and agent profile, plus a stub behavior eval
  and a model-assumption measurement replay. One mailman loads one reference,
  about 1.5k–1.8k tokens at start, but the perpetual loop has no fixed total: blocked waits
  use no tokens; empty returns cost 1 foreground request or 2–3 background
  requests, and action cycles cost 4 or 5 requests respectively. These are
  replay assumptions, not measured model usage or cost.
- Fix `varde plan gate` handling of task and repository paths from CLI arguments.
- Add message relay planning, wait/once commands, confirmations, leases,
  escalation, and mailman status.
- Add hook receipt tracking and the explicit `msg ack <id> --as <address>`
  action prompt.
- Slim `varde-plan`: resume, deferred-findings and plan-set steps moved to `varde learn how varde-plan` topics; answer routing, review brief and task ownership stay inline.
- Slim `varde-orchestrate`: tighten references; decision-file shapes, watchdog rounds and slot checkpoint commands stay inline.
- Slim `varde-build`: measured-run, stuck-attempt and shared-surface steps moved to `varde learn how varde-build` topics; condense the debug posture and verify reference, keeping check-rigor, verify-target and debug gates inline.
- `varde-review`: reviewed for slimming and intentionally unchanged (every route's text is used on each normal run of that route; the only true cruft is about 40 tokens).
