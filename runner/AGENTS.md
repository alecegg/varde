# Runner

- The runner owns provider adapters and the local dashboard.
- Keep provider SDKs behind `RunnerPlugin`; the Paseo SDK is pinned in `sidecar/package.json`.
- Never create Paseo projects from this module; agent creation must target an existing workspace ID.
- Resolve adapters by harness through the plugin registry; keep harness-specific branches inside adapter and registry construction modules.
- Route every message through `Supervisor.send` so concurrent senders share its per-session lock.

## Dashboard UI

- No horizontally scrolling chip or tab rows on mobile; wrap, or use a
  control that fits.

## Claude

`claude-sdk` is the default. Enable the `claude-cli` backup only on the user's instruction with `[claude_cli] enabled = true`.

- Codex uses Paseo unless `[codex_app_server] enabled = true` selects the native harness.
- Set `binary` only when the official `codex` executable is not on `PATH`.
- Native mode supports these sandbox modes:

  - `read-only`.
  - `workspace-write`.
  - `auto`.
  - `full-access`.

- The version and protocol probe reports errors at the first session start.

## Pi RPC

- Set `[pi_rpc] enabled = true` to register the off-by-default harness.
- Set `[opencode_http] enabled = true` to register the off-by-default native OpenCode server harness; `binary` may override the `opencode` executable.
- It runs the official `pi --mode rpc` CLI with the user's login.
- Configure only `read-only` roles and fallbacks; the adapter limits built-in
  tools to read-only operations and disables MCP tools.
- Extension UI dialogs are cancelled.
