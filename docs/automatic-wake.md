# Automatic wake-ups for plan events

`varde plan watch` reports plan events (stale, blocked, needs-decision,
merge-ready, finished). It runs no model. This page covers the parts the
`--help` text leaves out: a headless timer and per-harness wake recipes. Event
kinds, flags, `wake_command` and the inbox are in `varde plan watch --help`.

## Delivery order

1. **Push**: `orchestration.wake_command` in the user config starts the owning
   session's turn after the inbox write.
2. **Subscribe**: the harness runs `varde plan watch` as a background process
   and turns stdout lines into notifications. It may have a time cap.
3. **Inbox baseline**: every event is appended once to the `main` inbox, and the
   per-prompt hook prints it on the next turn. It cannot wake an idle agent.

## Headless timer

`docs/service/watch-service.plist` (launchd) or
`docs/service/watch-service.service` and `.timer` (systemd user) run
`varde plan watch --once --repo <path>` every minute, with no agent running.
Keep the basenames, set `/path/to/varde` and `/path/to/repository` to absolute
paths, then enable:

- launchd: copy the plist to `~/Library/LaunchAgents`, then
  `launchctl bootstrap gui/$(id -u) <plist>`.
- systemd: copy both files to `~/.config/systemd/user`, then
  `systemctl --user enable --now watch-service.timer`.

Run one watcher per cache key (the `--notes` path, else the repository). A
Monitor watcher started with `--notes` and a timer without it would both append
events and run `wake_command`, so run only one. Under a timer, use absolute
program paths in `wake_command`; `--once` retries a failed wake on every run.

## Harness integration

Claude Code Monitor is the one verified subscribe route: run `varde plan watch`
under Monitor and use its stdout event lines as notifications. Monitor has a
30-minute time cap, so re-arm it when needed. Other harness push and subscribe
routes remain unverified; configure `wake_command` only with a route you have
verified for your environment.
