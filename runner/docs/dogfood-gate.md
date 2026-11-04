# Native cutover dogfood gate

Run this gate after the native agent commands and the plans listed in the
native-cutover plan's Needs are available. Record the evidence in
`notes/dogfood-report.md`; do not conclude native-cutover until the report ends
with the user's `Gate: PASS` verdict.

## Before the run

- Install the runner as a service using the existing service layer: a systemd
  user unit on Linux or launchd on macOS.
- Enable native `codex-app-server` and `claude-sdk`; keep `claude-cli` disabled.
  If the Claude adapter has not merged, enable native `claude-cli` only for the
  gate run on the user's instruction, then disable it again.
- Stop the Paseo daemon. Confirm `varde-runner gate check` reports no Paseo
  sessions or address bindings before starting.
- Use a phone browser at 390px. Do not use a terminal during the plan run.
- Record the exact external watchdog or scheduled nudge entry that will be
  disabled. This is any cron, launchd job, or harness monitor that prompts idle
  agents outside the runner relay; include the entry in the report.

## Plan run and restart

Run one plan end to end: planning in a planner thread, implementation by an
orchestrator that launches builders with `varde-runner agent launch` and creates
task worktrees with `varde-runner workspace create`, then review and merge.
Disable the external nudge before the run and leave it disabled during the soak.

During a build wave, restart the runner once from Settings or the phone-reachable
service control. Record the restart time as an ISO 8601 timestamp with timezone.
Immediately after restart, while the wave is still active, run:

```sh
varde-runner gate check --restart-at 2026-10-25T12:00:00Z --json
```

The command reads `.cache/dashboard/runner.sqlite3` without modifying it. A
passing input check has zero Paseo sessions and bindings, one `resume` event
after the restart for every session running at the checkpoint, and no `parked`
event after the restart. `--since` and `--until` optionally bound the restart
events considered; they do not filter the Paseo residue counts. The check does
not determine whether prompts were lost, actions repeated, or liveness was
accurate; record those observations and the user's verdict separately.

## 24-hour relay soak

Keep the external nudge disabled for a full 24-hour soak, then run:

```sh
varde msg soak --window-days 1 --json \
  --threshold delivered-latency=60 \
  --threshold minimum_messages=20
```

The report includes informational `wakes`, `missed`,
`distinct_recipients`, and `max_delivered_latency_s` values. Check that there
are at least 20 wakes across at least 3 recipients, no missed messages, maximum
delivered latency is at most 60 seconds, and `main-nudges` is zero. These fields
do not change the soak's default verdict; `--threshold` overrides existing
criteria for this run only.

After the soak, remove the external nudge entry and record that removal. Put the
gate-check JSON, soak JSON, restart timestamp, exact nudge entry and its removal,
and the user's `Gate: PASS` or `Gate: FAIL` line in
`notes/dogfood-report.md`. A `PASS` is required before starting Paseo removal.
