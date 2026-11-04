# claude-sdk engine contract (protocol version 1 host)

Engine module for the generic Node host (`runner/node-host/PROTOCOL.md`). It wraps
the Claude Agent SDK `query()` (npm `@anthropic-ai/claude-agent-sdk`, pinned in
`package.json`; verified against the registry and the package's `sdk.d.ts` at
0.3.310). It never reads or stores credentials: the SDK uses the user's own
Claude login, and Anthropic key and token variables are removed from every child
environment.

The Python plugin (`plugins/claude_sdk`, task s3) owns persistence of the SDK
session handle, cwd and launch prompt; the engine only reports them.

## Methods

All params are objects; every reply is an object. Errors use the host error
frame with the codes below.

| Method | Params | Result |
| --- | --- | --- |
| `session.start` | `cwd` (absolute path), `model` (string), `effort?` (`low\|medium\|high\|xhigh\|max`), `mode` (runner mode), `prompt?` (string), `env?` (string map), `resume_handle?` (SDK session id), `session?` (runner-chosen id), `stream_idle_timeout_s?` (silence-flag threshold, default 300) | `{session, resumed}` |
| `session.send` | `session`, `text` | `{}` |
| `session.interrupt` | `session` | `{}` |
| `session.stop` | `session` | `{}` (idempotent; forgets the session) |
| `permission.respond` | `session`, `request_id`, `decision` (`approve\|deny`) | `{}` (needs the permission module, s2) |
| `session.alive` | `session` | `{alive, state}`; `state` is `running`, `idle`, or `ended` |

- `session` is the engine session id. If `session.start` omits it, the engine
  generates a UUID. Events carry it as the notification `session` field.
- `resume_handle` becomes the SDK `resume` option; the original `cwd` must be
  passed again. With no handle the session starts fresh. `resumed` reports which.
- `prompt` is sent as the first user message when non-empty.
- `mode` mapping (same as `claude-cli`): `read-only` -> `plan`;
  `workspace-write` and `auto` -> `acceptEdits`; `full-access` ->
  `bypassPermissions` (sets `allowDangerouslySkipPermissions`). Any other mode
  fails with `invalid_mode`.
- `env` is passed as the SDK child-process `env`. When absent the engine copies
  its own `process.env`. Either way `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`
  and `CLAUDE_CODE_OAUTH_TOKEN` are deleted before use. Values are never logged.
- `model` is passed through unchanged; `effort` outside the list fails with
  `invalid_effort`.

Error codes: `invalid_params`, `invalid_mode`, `invalid_effort`,
`unknown_request` (no pending permission request with that id), `unknown_session` (never started, or already stopped), `session_ended` (the query ended; `session.send` on it), `session_interrupting`, `session_exists`, `unsupported` (a seam with
no module installed), `sdk_unavailable` (the SDK package cannot be loaded),
`unknown_method`.

## Events

Notification `data` payloads (the plugin maps these onto runner events with the
same names and the same payload keys as `claude-cli`):

| Event | Data |
| --- | --- |
| `handle` | `{handle, cwd}`: the SDK session id, sent once per start from the first system message. The plugin persists it. |
| `text` | `{text}` |
| `tool_intent` | `{call_id, name, status: "running", input}` |
| `tool_result` | `{call_id, status: "completed"\|"failed", content}` |
| `permission_requested` | `{request_id, tool_use_id, kind: "tool", tool, summary, input}` (emitted by the permission module, s2) |
| `permission_resolved` | `{request_id, decision: "approve"\|"deny"\|"expired"}` (s2) |
| `status` | `{status: "running"\|"idle", silent?}`: `silent: true` flags a quiet stream, `silent: false` clears it on the next activity |
| `usage` | see below |
| `session_end` | `{status: "completed"\|"failed", result, subtype}`: one turn finished (the session stays open) |
| `error` | `{message}` |
| `exit` | `{reason: "stopped"\|"stream_ended"\|"error"\|"interrupted", message?}`: the query is gone; no more events for this session |

`usage` data, sent after each result message:

    {source: "claude",
     usage: {input_tokens, output_tokens, cache_read_input_tokens,
             cache_creation_input_tokens},
     context_window,            // largest contextWindow across models, or null
     total_cost_usd,            // cumulative for the query (latest result)
     model_usage: {<model>: {input_tokens, output_tokens, cache_read_input_tokens,
                              cache_creation_input_tokens, cost_usd, context_window}}}

A rate-limit message becomes `usage` with `{source: "claude", limit: <info>}`.

Per turn the order is: `status running` (on send), `text`/`tool_*`, then
`session_end`, `status idle`, `usage`.

## Permission, silence and process behavior (s2)

- A tool permission request becomes `permission_requested` (`request_id` is the SDK tool use id). It resolves exactly once: `permission.respond` approve or deny, or `expired` when the SDK aborts it, the session is interrupted or stopped, or the query ends. An expired request is denied to the SDK with a message that the tool call was not run. A second respond for the same id fails with `unknown_request`. Nothing is replayed; after a host restart the callbacks are gone, so the plugin expires its persisted waits itself.
- Silence: when a turn is running, no tool is in flight and no SDK message or send arrived for `stream_idle_timeout_s`, the engine emits `status {status: "running", silent: true}` once. It never interrupts, aborts or kills the query. The next activity emits `silent: false`.
- Processes: each session's Claude child is spawned through the SDK spawn hook in its own process group (pgid equals pid) and registered with `ctx.trackChild`. `session.stop` closes the query (SIGTERM to the group), waits 5 s, then SIGKILLs the group. When a child exits, its group is swept with SIGKILL so tool subprocesses die too, and the group is untracked.
- Interrupt: `session.interrupt` expires pending permissions, asks a running turn to stop softly (SDK `interrupt()`), and waits for its result for up to 5 s. It then SIGKILLs that session's process group (at once when the session was idle). The query ends with `exit {reason: "interrupted"}` and no `error` event; the result events arrive first. Sends fail with `session_interrupting` from the moment interrupt starts, then `session_ended`, so the kill never hits a later turn. Other sessions are untouched. The plugin resumes from the handle on the next send.

## Seams (all installed by default; pass `null` to remove one)

`createEngine(deps)` (default export is `createEngine()`):

- `deps.loadSdk()`: returns the SDK module; tests inject `test/fake-sdk.mjs`.
  The default imports the package, or the file named by `VARDE_CLAUDE_SDK_MODULE`.
- `deps.permission`: `{canUseTool(session) -> fn, respond(session, id, decision), expireAll(session)}` (`permission.mjs`). Without it the SDK `canUseTool` option is unset and `permission.respond` fails with `unsupported`.
- `deps.watchdog`: `{attach(session), touch(session), detach(session)}` (s2, `watchdog.mjs`); the engine calls `touch` for every SDK message and send.
- `deps.processes`: `{spawnOptions(session) -> {spawnClaudeCodeProcess}, interrupt(session), stop(session)}` (s2, `interrupt.mjs`): per-session process group, `ctx.trackChild`, group kill. Without it the SDK spawns its own child and `session.interrupt` calls `query.interrupt()`, `session.stop` calls `query.close()`.

A `session` object passed to these seams has: `id`, `cwd`, `handle`, `state`,
`query`, `ctx`, `emit(event, data)`.
