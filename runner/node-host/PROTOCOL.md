# Node host protocol (version 1)

The runner starts one Node host process per engine kind. The host loads one
engine module and moves JSON Lines between the runner and that engine. The host
knows no sessions, models or product names.

## Ownership

The engine plugin owns its `NodeHost` (`varde_runner.node_host`). It constructs
the host lazily on its first `start` or `resume` and stops it in `close()`.
Nothing else starts or stops a host.

## Transport

- stdin carries runner-to-host frames; stdout carries host-to-runner frames.
- One JSON object per line, UTF-8, `\n` terminated, at most 16 MiB per line
  (`MAX_LINE_BYTES`). A longer line is a fatal protocol error for the side that
  reads it: the host exits; the runner kills the host and counts a crash.
- stderr is free text for logs. The runner keeps a bounded tail only.
- Engines must not write to stdout. The host redirects `process.stdout.write`
  to stderr after capturing the real stream for frames.

## Frames

Host to runner, first line, exactly once:

    {"type":"ready","protocol":1,"engine":"<name>","node":"<version>"}

Runner to host request:

    {"id":<int>,"method":"<str>","params":{...}}

Host reply, one per request, in any order:

    {"id":<int>,"result":{...}}
    {"id":<int>,"error":{"code":"<str>","message":"<str>"}}

Host notification:

    {"event":"<kind>","session":"<id>|null","data":{...},"seq":<int>}

`seq` increases by one per notification for the life of one host process and
restarts at 1 after a restart. A malformed line from the host is skipped and
reported as a `host_frame_error` event; it does not fail pending calls.

Host-owned error codes: `bad_request` (invalid request frame),
`shutting_down`, `bad_result` (engine returned a non-object). An engine
exception replies `error.code = err.code` when it is a string, else
`engine_error`.

## Host-owned events

- `child_tracked` / `child_untracked`, `session: null`, `data: {"pid","pgid"}`:
  an engine registered or released a detached child process group with
  `ctx.trackChild(pid, pgid)` / `ctx.untrackChild(pgid)`. The runner records
  tracked groups so a stale one can be reaped after the runner restarts.

## Runner-synthesised events (session `null`, `seq` -1)

- `host_state`: `data: {"state","reason"}` on every state change.
- `host_down`: `data: {"reason","stderr_tail"}` when the crash policy gives up.
- `host_frame_error`: `data: {"message"}`.

## Engine module contract

ESM default export:

    { name: string,
      init(ctx): Promise<void>,
      handle(method, params, ctx): Promise<object>,
      shutdown(): Promise<void> }

`ctx` provides `emit(event, session, data)`, `log(level, message)` (stderr),
`trackChild(pid, pgid)` and `untrackChild(pgid)`. `init` runs before `ready`;
a failure exits the host with code 4. The runner loads the engine by path
(argv[2] of `host.mjs`).

## Lifecycle

- The runner starts the host in its own session (`start_new_session`), so the
  host is the leader of a process group with `pgid == pid`.
- Stop is SIGTERM to the group, then SIGKILL after a grace period.
- On SIGTERM, SIGINT, stdin EOF or an uncaught error the host calls
  `engine.shutdown()` with a 2 s deadline, SIGKILLs every tracked group, then
  SIGKILLs its own group. Children in the host group die with it; no
  OS-specific parent-death API is used.
- The runner records the host pid, start time, command and tracked groups in a
  state file. At the next start it kills a stale host group and tracked groups
  whose recorded identity still matches.
- Node older than 22.19 makes the host exit with code 3 and a stderr message;
  the runner also checks the version in `ready`.

## Runner behaviour

- Pending calls fail with `HostRestarted` when the child dies. The runner never
  replays a call.
- Crash policy: `next_action(history, now, policy)`. `history` holds the death
  times including the current one. Within `window_s` (default 300 s) the first
  `restart_max` (3) deaths restart after 1, 2 and 4 s; the next death leaves
  state `down` with a `host_down` event. An explicit `restart()` resets the
  history. A failed relaunch counts as a death.
- Calls while `restarting` raise `HostRestarted`; while `down` raise `HostDown`.
