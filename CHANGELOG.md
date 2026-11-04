# Changelog

## 1.0.1

- README and docs refreshed for the public release.
- MIT LICENSE added.
- Baseline and release tooling unchanged.

## 1.0.0

First release of the rewritten project. It replaces the earlier 1.x and 2.x releases, which were removed; the entries below record the history that led here.

### Since 2.1.0

- Merge the `doc` and `knowledge` modules into `learn`. The `varde doc` and `varde knowledge` groups and the flat `varde learn` verbs are replaced, with no aliases, by the grouped `varde learn` surface: `check`, `how`, `measure <skill> <kind>`, `sessions`, `friction`, `knowledge`, `docs`, `skills demand`. The approved old-to-new table is in `learn/AGENTS.md`. The `doc` and `knowledge` presets map to `learn` with a notice, and the `varde-docs`, `varde-skill-authoring`, `varde-doc-authoring` and `varde-knowledge` skills now install with `learn`; setup sync removes the retired `varde-agent-doc-authoring` install. Run `varde setup sync` once after upgrading.

## 2.1.0

- Speed up `varde scan`.
- Add per-file fix lists to the scan quality verdict and make `--vs repo` the default reference.
- Add the `varde-visualize` skill.
- Mark the code quality feature (scan quality verdict, `varde score`, `--vs` references, fix lists, calibration) as under construction: all languages are report-only and verdicts are advisory.
- Slim `varde-customize`: move sql-rule, rule-verification, and Toz profile-script detail to `varde doc how varde-customize` topics.
- Learn data (friction, ledger and digests, CLI calls) can move to `learn.sqlite3` with `varde learn store migrate`; see `docs/learn-store.md`.
- Move the learn analyzed-session ledger and digests behind `varde-data` repositories (learn still parses `sweep.toml` itself); on-disk formats are unchanged.
- Replace the runner dashboard with a chat-first home, agent conversations and
  read-only profiles. Old home, chat, queue, roster and profile URLs redirect to
  their new routes; the manager conversation requires the opt-in
  `[roles.manager-bot] enabled = true` setting (see `runner/docs/chat-first-ui.md`).
- Add the manager-bot forbidden-action suite and `runner/docs/manager-bot.md` (allowlist, never-list, caps, pause and kill, audit, delegation, residual risk).
- Add mobile settings and home browser coverage, and document runner settings,
  restart behavior, backups, change logging, and status probes.
- Add runner startup silence recovery and derived `liveness`, including the
  `startup_kill_timeout_s` and `stall_after_s` settings, stop that escapes held
  send locks, and one-time launch-prompt resend after a silent restart.
- Add editable runner identity profiles, a role-grouped roster on `/agents`, and a configurable runner-wide live instance cap.
- Add profile editing from the `/agents` roster, with inline validation and a single source for role descriptions.
- Add persistent manager and per-agent chat threads, user takeover with a durable message queue, and validated handoff summaries.

- Add native runner workspace create, list, and remove commands.
- Add an `/agents` page for launching and managing runner agents, including
  permission requests in Needs You.
- Add `runner/deploy/deploy.py`: installs the CLI into a private release
  directory, smoke tests it, and swaps the `~/.local/bin/varde` symlink
  atomically, then builds the UI if stale and restarts the runner with endpoint
  checks. The newest 3 releases are kept for rollback.
- Add a SQLite message store with mirrored cutover, verified transfer commands,
  a 2-second prompt-hook lock bound, and dashboard signatures that track WAL
  updates; document inbox permissions and the cutover and rollback runbook.
- Add a rebuildable SQLite plans read index for runner and data readers, with
  background refresh, indexed status/watch queries, and a files-backend
  rollback switch (`VARDE_PLANS_BACKEND=files`).
- Preserve native runner wake targets across inbox hook refreshes, scrub ambient
  child identity variables, and record binding snapshots in smoke diagnostics.
- Make native mail-wake smoke messages immediate, record relay state and relay logs on timeout, and ignore replayed Claude user frames with string content.
- Persist native agent address bindings and clean them up on launch failure or session end.
- Surface Codex app-server turn status and protocol failures, forward valid reasoning effort, and log a structured terminal observation.
- Surface Pi RPC provider, command, startup-silence, and process-exit failures with bounded diagnostics.
- Add a native adapter smoke driver that runs one adapter in a throwaway runner
  and records its session lifecycle.
- Rename the message-status urgent-mail relay flag and remove legacy `mailman` / `mailmen` JSON keys.
- The runner relay wakes main and orchestrators on merge-ready, done, decision-needed and stall events without waiting out the recent-activity grace; one coalesced line per recipient, no polling prompt.
- Runner startup no longer waits for the dashboard cache prewarm: it runs in the
  background, is cancelled on shutdown, and a failure or timeout lists
  `startup_prewarm` in the degraded sources. `varde plan status` reads the
  message log and local branch list once per run instead of once per plan
  (about 9 s to about 1.5 s on 270 plans).
- Document the friction repository protocol, canonical event stream, derived
  cache, store resolution, migration, locking, redaction, and import dry-run
  behavior; enforce that friction storage filenames stay in the data layer.
- Skip `runner/tests/test_agent_watch_ui.py` with the unbuilt-UI reason instead of
  failing when the runner UI is not built, as in fresh worktrees.
- Show an owner for every dashboard orchestrator row: fall back to the plan's
  `assigned_to`, then the bound address, when no plan owner is set.
- Share runner adapter process code: one `process_state` module now holds process identity, spec persistence, orphan stop, process-group waits and tool-input redaction for the Claude, Codex, Pi and OpenCode adapters; Codex enablement is parsed in config, the Codex probe matches exact methods keyed by binary path and mtime, and Codex per-session state is one record.
- Cap review rounds per target at one full review plus one re-check, and require a
  target in every reviewer brief.
- Add an opt-in native OpenCode HTTP/SSE runner adapter with session control,
  permission and question responses, usage reporting, and version/API checks.
- Add an opt-in native Pi RPC runner adapter with prompt control, session
  resume, usage reporting, and approval-free read-only role validation.
- Document slot assignment and merge-state workflow commands.
- Add the quality call resolver and quality-pass call edges, import text,
  receiver text, creation sites, type facts, and function qualifiers.
- Add the `varde-runner` module with a loopback-only dashboard server, supervised
  work-item intake, decision mailbox, role editor, and runner package checks.
- Include model, worktree, and `last_event_at` values in
  `varde plan watch --once --json` plan snapshots.
- Allow the runner's dependency-rule edge to `varde-core`; runner may not depend
  on higher-level capability modules.
- Message wake routing: refresh bound Paseo IDs with `varde msg address refresh`, retry main after repeated relay failures, and include address markers in orchestrator launch prompts.
- Document the messages repository API, cursor and reader semantics, and message-store locking.
- Move work-item storage behind backend-neutral repositories with SQLite and in-memory backends; document migration, versioning, and compatibility behavior.
- Move decision storage and answer delivery behind the decision repository and `AnswerFlow`; document SQLite migration, durability, recovery, and runner compatibility behavior.
- Add the `varde-mailman` skill, its agent profile, a stub eval, and a
  measurement replay. The relay runs as a perpetual loop: a blocked wait uses
  no tokens, but each empty return starts another model request. The replay's
  request counts are assumptions, not measured usage or cost.
- Message relay: add `msg relay --once|--wait`, confirm/renew/end commands,
  delivery receipts, escalation, and mailman status reporting.
- Message inbox: sessions bind to an address with a one-time
  `[varde-address: <name> <token>]` marker (`varde msg address new|bind|unbind|list`);
  unbound sessions and subagents no longer read `main`'s mail. Deliveries are
  logged in `deliveries.jsonl`; new `varde msg status`, `msg ack`, and
  `msg migrate` (run once after binding `main`); the inbox is also delivered on
  SessionStart, PostToolUse, and Stop. `VARDE_ADDRESS=main` or a marker is now
  needed for `main` to receive mail in hooks.
- Breaking: `varde setup sync` no longer saves `--skills-dir`, `--agents-dir`,
  `--link-mode`, `--skills`, or `--preset` implicitly. Add `--save` to persist
  these values in `[sync]`; `--save` also pins the resolved Toz store. Toz
  resolves existing stores and honors `[default].toz`, so the pin only freezes
  the location against later directory changes.
- Made the learn process-group timeout test synchronize with its child instead
  of relying on fixed sleeps, and removed a Ruff exclusion for a missing fixture
  directory.
- Completed the capability-module layout: each module owns its project, tests,
  and single packaged copy of its skills, with discovery through provider entry
  points and no bundle step.
- Generated setup presets from module manifests: `scan` is now `code`, `docs`
  is now `doc`, `dev` is available, and `workflow` includes 11 skills. The old
  names are removed without aliases.
- Removed the parity package, goldens, and Rust comparison tooling; tests now
  assert behavior directly.
- Cut over the Varde CLI and module workspace to Python, with parity comparisons
  against committed goldens and the `varde-rust` oracle.
- Install the CLI with `uv tool install`; repository guidance and skill setup
  now target the Python workspace.
- Renamed the `varde-md-core` distribution and `varde_md_core` import package to `varde-knowledge` and `varde_knowledge`; its module entry point is now `knowledge`.
