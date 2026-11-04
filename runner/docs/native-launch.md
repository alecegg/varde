# Native runner launch

Enable a native adapter and configure a role in `runner.toml`, then launch a session in an existing workspace:

```sh
curl -sS -X POST "$RUNNER_URL/api/agents" \
  -H 'content-type: application/json' \
  -d '{"harness":"pi-rpc","workspace":"/path/to/workspace","role":"orchestrator","prompt":"Start the task","address":{"slot":"orchestrator-2","plan":"2026-10-24-example"}}'
```

Replace `$RUNNER_URL` with the runner base URL. The default is `http://127.0.0.1:8765`; use the port passed to `serve --port` if you changed it. The required fields are `workspace`, `role`, and `prompt`. Optional `harness` must match the role's resolved harness (omitted, the role's harness is used); optional `mode` overrides the role's mode; optional `parent_id` is stored on the session. `workspace` must be an existing directory or a workspace ID listed by the adapter. Optional `address` contains a `slot` and optional `plan`. Success returns HTTP 201 with `agent_id`.

## Prompt or interrupt from a shell

A write is accepted only from a client attached to the agent's watch stream as a writer. `varde-runner agent` holds that stream and posts the write in one process:

```sh
varde-runner agent prompt <agent-id> "<text>" [--port 8765]
varde-runner agent interrupt <agent-id> [--port 8765]
```

```sh
varde-runner agent stop <agent-id> [--port 8765]
varde-runner agent archive <agent-id> [--port 8765]
varde-runner agent mode <agent-id> <mode> [--port 8765]
```

`agent mode` stops the session, then resumes it with the new mode. It validates the mode first and leaves the session running when the mode is invalid or the harness cannot change it (`pi-rpc` accepts `read-only` only; `opencode-http` fixes the mode at launch; the `claude-sdk` and `pi_durable` plugins must accept the optional `settings` argument on `resume` before they support it).

It prints the runner's JSON outcome and exits nonzero with the HTTP status and body on failure. A `write client is not authorized` reply right after attach is retried for up to five seconds; other errors fail at once.

## Launch and list from a shell

```sh
varde-runner agent launch --role <role> --workspace <id|path> --prompt <text|-> \
  [--harness <name>] [--mode <mode>] [--slot <slot> [--plan <plan>]] [--parent <agent-id>] [--port 8765]
varde-runner agent list [--parent <agent-id>] [--port 8765]
```

`launch` prints `{"id": "<agent id>", "address": "<slot or null>"}`. `--prompt -` reads the prompt from stdin. `--harness` only checks the role's harness. `--parent` defaults to `VARDE_AGENT_ID` in the caller's environment. A launch refused by the live-instance cap exits with code 2 and the cap message. `list` prints one JSON row per agent, including `liveness` and `parent_id`; `--parent` keeps the children of one agent. Sessions started before `parent_id` existed have none.

For Pi Durable setup and its metered first-run smoke, see
[Pi Durable first run](pi-durable.md).

## Native workspaces

Configure allowed repositories in `runner.toml`:

```toml
[workspaces]
repos = ["/path/to/repository"]
```

Then use the loopback CLI to create, list, and remove task worktrees:

```sh
varde-runner workspace create --repo /path/to/repository task-id [--base <commit>]
varde-runner workspace list [--json]
varde-runner workspace remove [--repo /path/to/repository] [--discard] task-id
```

Create branches from the current checkout's committed `HEAD` unless `--base`
is supplied. Remove checks for active runner sessions, uncommitted changes,
and whether the branch is merged into the caller's current checkout; use
`--discard` to skip the dirty and merged checks. The session check covers
runner-launched sessions only; it does not cover Paseo sessions, terminal
agents, or other processes. If `--repo` is omitted for remove, the id must
identify a worktree in exactly one configured repository.

Workspace commands exit with 0 on success, 1 for usage or an ambiguous
repository id, 2 when a base commit cannot be resolved, 3 when the worktree
already exists, and 4 when a removal is refused by its safety checks. Exit 5
means Git failed during an operation or the post-removal verification failed.

## Install and start the runner

Install from the repository root with `uv tool install ./runner`, or build a
standalone PEX with `uv run --locked python runner/pex/build.py <temp-dir>` and
run `<temp-dir>/varde-runner.pex`. Start `varde-runner serve` from a terminal
once. If macOS asks for folder access, answer the prompt there. It is unverified
whether that grant also lets a later runner process started by launchd access
the same folder. A child can still hang under launchd on a machine whose
configuration names a protected folder, until the startup diagnostic identifies
the cause and the user applies one of its fixes. The foreground smoke checks
runner liveness and PID stability; it verifies this access assumption only when
run against a configuration that touches the folder in question.

A service started without the needed access can leave a child silent at startup.
After the configured startup timeout (30 seconds by default), the runner emits
a diagnostic that says the child produced no output and an OS folder-access
prompt may be pending. It lists the runner executable and interpreter paths and
ways to resolve the issue. A later child event reports that startup recovered.
The timeout does not stop the session.

`varde-runner service doctor` probes the workspace directories known to the
running runner. When no runner is available, it reports that the runner is unavailable and
that the shell result may differ from the service. A clean probe does not rule out other
causes, including configuration or interpreter access.

Service files are optional. `varde-runner service print launchd` and
`varde-runner service print systemd-user` prints the generated definition.
`varde-runner service install --working-dir <data root>` installs the
per-user service for the current platform (`--working-dir` defaults to
`VARDE_WORKING_DIR`, and install refuses without either; `--port` and
`--enable-relay` are optional, and a re-run drops relay unless the flag is
repeated), and `uninstall`, `status`, and
`doctor` manage or inspect it. On Linux, install enables lingering so the user
service can continue after logout; if that fails, an administrator may need to
run `loginctl enable-linger` for the account.

## Address, hooks, and mail wake

With `address`, the runner creates a one-time marker, prepends it to the first prompt, then redeems it after the adapter starts. Redemption binds the adapter session to the slot and stores wake context with the runner agent ID and remote session ID. Only one redeemer can consume the marker. Runner-launched sessions do not need a harness prompt hook to bind the address; avoid a second hook or manual bind that could consume it first. Other hook integrations are independent of this launch handshake.

The event-driven relay is the only automatic mail waker when `varde-runner serve` runs (relay is on by default; `VARDE_RUNNER_RELAY=0` or `off` disables it); it needs no watchdog cron or LLM mailman. The runner, launched session, and `varde msg` must use the same `VARDE_WORKING_DIR` data root. The real Claude CLI mail-wake smoke passed; real mail-wake turns have not been run for Codex, Pi, or OpenCode. See [automatic wake](../../workflow/docs/automatic-wake.md) for the separate plan-watch notification mechanism.

At relay startup, the runner backs up and prunes legacy mailman generations in
`.cache/inbox/relay/state.json`, first copying it to
`state.json.bak-<UTC timestamp>`. It retains the current token and five previous
generations. Set `VARDE_RELAY_PRUNE=0` to disable this migration.

Use `varde msg show <id>` (`--json` for machine-readable output) to see the
receipt state, timestamps, recipient's undelivered age, and last failure
reason. Send an answer with `varde msg send --to <address> --kind <kind> --reply-to <id> "<text>"`.
Receipt states are `queued`, `pushed`, `delivered`, `read`, and `answered`; a
non-main message still undelivered after 10 minutes produces one
`info-failure` notice to main.

### SQLite message store rollback

Before a v4 CLI opens a v3 message database, stop the runner and back up the
database:

```sh
WORKING=/absolute/path/to/working
db="$WORKING/.cache/inbox/messages.sqlite3"
sqlite3 "$db" ".backup '${db}.v3.bak'"
```

A v3 binary rejects a v4 database with `Invalid: message database version 4 is
newer than supported`. There is no down-migration or config switch. To roll
back, stop the runner, remove stale WAL sidecars, and restore the backup:

```sh
rm -f "$db-wal" "$db-shm" && cp "$db.v3.bak" "$db"
```

## Lifecycle

Write calls require a non-empty `client` string in the JSON body. Then call:

```text
POST /api/agents/{agent_id}/interrupt
POST /api/agents/{agent_id}/resume
POST /api/agents/{agent_id}/stop
POST /api/agents/{agent_id}/archive
```

`prompt` sends more text with `{"client":"...","text":"..."}`. `respond` resolves an approval with `{"client":"...","request_id":"...","decision":"..."}`. Adapter capabilities differ; unsupported lifecycle actions return HTTP 501. `stop` ends the session and `archive` makes its lifecycle terminal.

## Harnesses and runner.toml

Native adapter settings and model examples:

| Harness | Model example | Enablement |
| --- | --- | --- |
| `claude-sdk` | `claude-sonnet-5-5` | `[claude_sdk] enabled = true` |
| `claude-cli` | `claude-sonnet-5-5` | `[claude_cli] enabled = true` |
| `codex-app-server` | `gpt-6-luna` | `[codex_app_server] enabled = true` |
| `pi-rpc` | `deepseek/deepseek-v4-flash` | `[pi_rpc] enabled = true` |
| `opencode-http` | `gpt-6-luna` | `[opencode_http] enabled = true` |

Native-cutover c2 owns the Claude defaults change; this documentation change
does not change config defaults:

- After c2, Claude roles use `claude-sdk` by default; the guard role is excluded.
- `claude-cli` stays registered but disabled as a backup.
- Until c2 lands, enable `[claude_sdk]` and select a type with
  `harness = "claude-sdk"` explicitly.

The SDK is expected to use Claude Code's login for the runner's OS account;
headless refresh is unverified. See [Claude SDK setup and the post-flip smoke
checklist](claude-sdk.md).

For native Pi, use a provider-prefixed model such as `deepseek/deepseek-v4-flash`; do not use `opencode-go` (its key was reported expired). The repository's generic type fallback is the same `deepseek/deepseek-v4-flash`. OpenCode's model string above is a config example; its real smoke is untested.

At minimum, configure `version`, the enabled adapter table, a model type, and a role that points to the type. A type has `harness`, `model`, `reasoning_effort`, and `mode`; `fallback` is optional. Pi supports `read-only` mode. Native Codex and OpenCode accept an optional `binary` path; otherwise the real runner searches for `codex` or `opencode` on `PATH`. The smoke driver's generated config has no `binary` option, so its OpenCode run requires `opencode` on `PATH`.

The default config path is `~/.config/varde/runner.toml`; `VARDE_RUNNER_CONFIG_DIR` selects a different directory. This is an example only; it does not edit your file:

```toml
version = 1

[pi_rpc]
enabled = true

[types.native]
harness = "pi-rpc"
model = "deepseek/deepseek-v4-flash"
reasoning_effort = "high"
mode = "read-only"

[roles.orchestrator]
type = "native"
```

Allowed hostnames for a Tailscale or reverse-proxy front end go in the same file as a top-level list, merged with `--allowed-host` and `VARDE_RUNNER_ALLOWED_HOSTS` (comma-separated):

```toml
allowed_hosts = ["myhost.tailnet.ts.net"]
```

## Smoke driver

Run one adapter smoke at a time from the repository root. `--harness`, `--role`, `--model`, and `--out` are required; `--workspace` defaults to a temporary directory and `--prompt` defaults to a one-word reply request. The driver isolates runner config and state while inheriting the user's environment and `HOME` for provider login.

```sh
uv run --project runner python runner/scripts/native_smoke.py \
  --harness pi-rpc --role explorer \
  --model deepseek/deepseek-v4-flash --effort high \
  --out /tmp/pi-smoke.json
```

The driver waits for readiness, launches through `POST /api/agents`, watches the reply, then interrupts, resumes, stops, and archives. `--expect error` instead waits for an adapter error, then stops and archives. Add `--mail-wake` to exercise addressed mail delivery; it sets `VARDE_RUNNER_RELAY=data` for the temporary runner. Real mail-wake verification currently covers Claude CLI only. The driver prepends the checkout virtual environment's `bin` directory to `PATH` and uses the checkout CLI for the mail send.

After merging, reinstall the CLI with `uv tool install --force --from ./app varde`. An older installed `varde` can overwrite runner bindings through its hooks; the binding-preservation rule is in the data layer shipped with the new CLI. Use `uv run --project runner python runner/scripts/native_smoke.py --help` for all flags.

## Smoke defects and status

| Adapter / area | Symptom | Fix and status |
| --- | --- | --- |
| Pi RPC | The initial `deepseek/deepseek-v4-flash` run launched but captured zero events and timed out. Its stderr tail contained only an unrelated “Planner role is unavailable” message and runner logs, not Pi failure evidence. An earlier `opencode-go/deepseek-v4.1-flash` run also had zero events; key expiry was reported by the user but not captured. | `fba118e7` surfaces Pi RPC errors, retains stderr diagnostics, and adds a post-prompt silence deadline. The later DeepSeek smoke passed after that commit, but the causal link and initial root cause are unproven. |
| Mail-wake chain (`claude-cli`) | (1) Address bound in workspace store instead of `VARDE_WORKING_DIR`; (2) smoke sent `info`, which waits for the two-minute digest; (3) turn-level `session_end` unbound the address; (4) native child used workspace path as `VARDE_AGENT_ID`, hook refresh overwrote wake `agent_id`, and `PASEO_*` leaked into child env; (5) replayed string user frames raised `user content must be a list`. | (1) `783b76e6`; (2), (5) `2cf8de3b`; (3) `184708b3`; (4) `bfafc3c7`, `097befb6`, `91d3740c`. All five fixes are in HEAD; Claude CLI real mail-wake PASS is recorded in `smoke-mail-wake-claude-cli-pass.json`. Codex, Pi, and OpenCode mail-wake turns have not been run. |
| OpenCode HTTP | No real turn has been run; the smoke driver needs `opencode` on `PATH`. | Untested; no pass claimed. |

The seven failed mail-wake attempts and the pass note are in `notes/` under the agent-memory plan folder `2026-10-24-native-adapter-real-turn-smoke`.
