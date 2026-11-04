# Sandbox permissions

## Baseline example tests (`varde_code.quality_score.baseline_tests`)

The baseline score runs a problem's behaviour tests against a candidate solution in a subprocess (`python3`, `node`, or `dotnet`).

- Reads: the solution directory and the test file, copied into a fresh temp directory. Writes: that temp directory and a temp `HOME` inside it, both removed afterwards. `dotnet` needs a writable `HOME` and, outside the Claude Code sandbox, `dangerouslyDisableSandbox`; so does `node` where the sandbox blocks its runtime.
- Environment: scrubbed to `PATH`, `DOTNET_ROOT`, `LANG` and a temp `HOME`. No credentials or other variables reach the child.
- Limits: 60 s timeout with a process-group kill (also kills subprocesses the tests start); output keeps only its last 64 KB.
- Residual: network is not blocked. A test or solution can still make network calls, read files the user account can read, and write outside the temp directory where the surrounding sandbox allows it. Run candidate code only inside the harness sandbox.

## Baseline page (`varde code quality baseline ui`)

The command serves a local page and JSON API (`varde_code.quality_score.cli.baseline_server`).

- Network: binds `127.0.0.1` only (`--port 0` picks a free port), so a sandbox needs loopback listen (`allowLocalBinding`) and loopback HTTP. Requests need an allowlisted `Host`, a same-origin `Origin` and the per-run token on POST. Opening a browser fails inside a sandbox; use `--no-open` and open the printed URL yourself.
- Reads: the packaged baseline data (`quality_score/baseline_data`) and `cal-1.toml`.
- Writes: the user config directory (`$VARDE_CONFIG_DIR`, else `$XDG_CONFIG_HOME/varde`, else `~/.config/varde`) under `quality/`: `overlay-<language>.toml` and `overlay-<language>.samples/` (saved user code). Nothing else is written; the user's saved code is not secret-scanned (local only).
- Behaviour tests of edited code run through the runner above, with the same limits and residual.

## Run the app

The CLI reads these paths:

| Path | Use |
| --- | --- |
| Repository files | Map, plan, and code indexing. |
| Git refs | `varde plan merged` and plan watch read branches and ancestry in the selected repository. |
| `~/.config/varde/config.toml` (or `$VARDE_CONFIG_DIR`) | CLI configuration. |
| `~/.cache/uv`, `~/.local/share/uv` | uv cache and Python runtime. |
| `~/.agents`, `~/.claude`, `~/.codex` | Skill and agent files for setup sync and doctor. Codex hook doctor also reads `~/.codex` through `codex app-server` to check hook trust status; the sandbox must allow executing `codex`. |

Its writable locations are:

| Path | Use |
| --- | --- |
| `$VARDE_CONFIG_DIR` (default `~/.config/varde`) | Toz cache, daemon database and lock, code index databases and locks, watcher lock files, `config.toml` (runner switch). |
| `$VARDE_RUNNER_STATE_DIR` (default `~/.local/share/varde-runner`) | Native runner adapter session state. |
| `<runner config dir>/identities/` (default `~/.config/varde/identities/`) | Editable runner identity profile TOML files. The runner needs read and write access to save profiles. |
| `$VARDE_RUNNER_CONFIG_DIR/runner.toml` (default `~/.config/varde/runner.toml`) | Dashboard settings read and atomically write the allowlisted runner config. Existing files are copied to timestamped `.bak` files beside `runner.toml`; the runner retains the five newest backups. |
| `$VARDE_RUNNER_STATE_DIR/config-changes.jsonl` (default `~/.local/share/varde-runner/config-changes.jsonl`) | Dashboard settings write an append-only audit of changed allowlisted keys and their old/new values. The state directory must be writable. |
| Harness executables and runner service markers | Settings status may execute a registered harness's noninteractive login-status command (3-second timeout), and read the runner's launchd/systemd service marker and install-file metadata. The runner does not open credential files directly for this check or expose raw probe output. |
| `$VARDE_TREE_SITTER_CACHE_DIR` | Tree-sitter grammar cache. The default under `~/Library/Caches` was not writable in the measured sandbox. |
| `<data>/varde/projects/` (`$XDG_DATA_HOME/varde/projects`, default `~/.local/share/varde/projects`) | Default `working` and `knowledge` directories for projects with no configured or env-set paths, one `<name>-<16 hex>` directory per repository path. Not created in the repository. Grant read and write access, or set `VARDE_WORKING_DIR` and `VARDE_KNOWLEDGE_DIR` to granted paths. |
| `<data>/varde/memory` (`$XDG_DATA_HOME/varde/memory`, default `~/.local/share/varde/memory`; override with `VARDE_MEMORY_DIR` or `[default] memory` in `config.toml`) | Scoped memory entries (`varde learn memory ...`): one Markdown file per entry under `global/`, `agent/`, `skill/` and `project/` directories. Also holds migrated knowledge entries (under `project/<key>/`) and migration records in `.migrations/` (`memory migrate --knowledge <bundle> --apply` writes them; the bundle is only read, and the dry run writes nothing). Project-independent; not created in the repository. Grant read and write access, or set `VARDE_MEMORY_DIR` to a granted path. |
| `<data>/varde/memory-shared/` (`$XDG_DATA_HOME/varde/memory-shared`) | Checkout of the shared memory repo (`[memory] shared` in `config.toml`), made by `varde learn memory pull` and `promote`. Needs read and write access, the git operations `git clone`, `fetch`, `branch`, `commit` and `worktree`, and network access to the configured remote host (`pull` only; `promote` never pushes). Not created in the repository. |
| `<data>/varde/memory-index/` (same `$XDG_DATA_HOME`, else `~/.local/share` tree as the memory root, via `local_share_dir()`, on every platform) | Derived SQLite FTS5 search index over memory entries and knowledge bundles (`<hash>.sqlite`, rebuilt from the files at any time, temp file then atomic rename). Written only by `varde learn memory search` (`knowledge search --text` keeps the old scorer on an unmigrated bundle); the SessionStart and SubagentStart hooks scan the entry files and never open or write it. Needs read and write access; when the directory is not writable the command prints a notice and uses an in-memory index. Never inside a memory root, a knowledge bundle or the repository. |
| `<data>/varde/memory/loop/` | Self-improvement loop records (`varde learn skills extract|reset|accept|reject|report`): one JSON record and one `.diff` per proposal, plus `report/<date>.md`. Not a memory scope and never promoted. `accept` also writes the files named in an accepted diff: skill and agent sources, `step_tools/` scripts and registries, and `agents/capabilities.json` (then runs `app/scripts/generate.py` from the checkout). An accepted extraction also writes the launcher `<data>/varde/step-tool` (`$XDG_DATA_HOME` or `~/.local/share`) that pointers run; it resolves the installed `varde` interpreter at run time. Grant read and write access to the memory root and, for `accept`, to the skill and agent source tree and the launcher file. `accept` refuses without an `approved` decision row in the report page's comments log. |
| `<working>/plans/<plan>/plan.md` | `varde plan approve-merge` and `varde plan merge` copy the user's recorded approval time into `merge_approved_at` (display only; the approval record is the runner's). |
| `<working>/plans/<plan>/plan.md` | `varde plan answer` atomically removes an answered Open Questions bullet and records the decision. |
| `<working>/.cache/plan-status-last.txt` | Last plan status. |
| `<working>/.cache/plan-now/` | Plan progress lines. |
| `<working>/.cache/plan-watch-*.json` | Plan watch event cache. |
| `<working>/.cache/plan-pulse-*.json` | Read-only pulse fingerprints. |
| Data store directories and `.cache/data/` | Advisory lock files (including `plans/<plan>/.plan.lock`, `.cache/inbox/.events.lock`, `.cache/inbox/slots/.lock`, and `.cache/inbox/relay/.lock`) and same-directory atomic-write temp files beside data stores; runtime and derived data caches. |
| `$VARDE_RUNNER_STATE_DIR/user-credential.json`, `pairing-code` (mode 0600) | Runner-only. `user-credential.json` holds the cookie-signing secret and the pairing-code digest for the optional `runner.require_user_pairing` gate; `pairing-code` holds the unpaired one-time code until it is used. Pairing enforcement defaults off. Deny read and write on the directory to every agent sandbox; an unsandboxed same-user agent can read both and pair itself. When enforcement is enabled, the runner never logs the code: on a terminal it prints it, as a service it prints how to get it (`varde-runner pairing-code`, run by the user). Delete `user-credential.json` and restart to pair again. The pairing cookie is `Secure` when the request is HTTPS or arrives with `X-Forwarded-Proto: https` (Tailscale Serve). |
| `$VARDE_RUNNER_STATE_DIR/merge-approver-main` (mode 0600) | Runner-created secret for `varde plan approve-as-main`. The main process reads it per command with the sandbox disabled (permission-gated; no standing grant), then sends it only in the local runner request header. Orchestrator and worker sandboxes deny access to the runner state directory. A same-OS-user process outside the sandbox can read this file, as it can read `user-credential.json`. The runner never logs the secret. |
| `<working>/.cache/dashboard/merge-approvals.sqlite3` | Merge approval records written by the user route and the authenticated main-agent route (append-only; triggers refuse update and delete). |
| `<working>/.cache/dashboard/chat.sqlite3` | Runner chat threads, messages, takeover leases, queued sends, and the manager-bot gateway audit log and run state (`bot_audit*`, `bot_state`; append-only triggers refuse update and delete); SQLite WAL sidecars are created beside the database, so the runner needs read and write access to the directory. |

The runner config API edits shared `types.*` model and ordered fallback values,
`roles.*` type mappings and guard enablement, and the `policy.*` lists. The
guided Claude SDK action previews a TOML diff before applying it. These changes
use the same `runner.toml` backup and config-change audit locations listed
above. Harness, type, role, and policy changes report a restart hint; the
dashboard does not restart the runner automatically. `allowed_hosts` remains
read-only.

Set `VARDE_CONFIG_DIR` or `XDG_CONFIG_HOME` to choose the config location.
Set `VARDE_TREE_SITTER_CACHE_DIR` to a writable, prefetched grammar cache.
`UV_CACHE_DIR` can point to the shared uv cache. `VARDE_ADDRESS` selects the
message address.

Map, plan, message, doctor, and toz capture commands needed no network in the
measured run. `varde run fetch <url>` needs access to the requested host.
Grammar downloads from `github.com` failed in the measured sandbox with a TLS
certificate error even though the host was allowed; seed the cache instead. uv
installs need `pypi.org` and `files.pythonhosted.org`. The registry host for a
first pyright run (`registry.npmjs.org`) was not measured; pyright ran from its
cached copy without network.

The toz daemon binds a Unix domain socket. Permit Unix socket binding for it.
The code watcher runs in the foreground and uses lock files; it needs no
network. `setup watch --ensure` installs launchd supervision and cannot run in
the measured sandbox. Unix-socket requirements of other commands are
unverified.

`varde map packs build` and `varde map packs status` read git state (HEAD,
`git ls-files`, `git diff`) and write only under `<repo>/docs/repo-map/`;
`build` also refreshes or creates the main-checkout index under
`$VARDE_CONFIG_DIR/code/repos/`. `build --all` and `build --stale` write the
same scope (README and module packs under `docs/repo-map/`). The first build
downloads tree-sitter grammars from `github.com`, which fails in the sandbox
(see above); run it unsandboxed or with a prefetched cache. `varde setup` at the
top of a git main checkout also edits `AGENTS.md` (pointer block) and runs the
first `build --all` (when `docs/repo-map/README.md` is absent), so it needs write
access to the checkout and the grammar download; `--no-packs` skips both.
`just repo-map-refresh` runs `build --stale` on the main checkout and commits `docs/repo-map/` by path (`git add` and `git commit` in the
main checkout); it skips in linked worktrees.

## Runner switch

`[runner] enabled` in `~/.config/varde/config.toml` (env `VARDE_RUNNER_ENABLED`)
gates hooks and the merge approval check; behavior is in the varde-manage setup
reference. `varde runner off|on` write the key; all three subcommands call
`varde-runner service`.

No new permission is needed:

- hooks already read `~/.config/varde/config.toml`;
- writing it uses the existing `$VARDE_CONFIG_DIR` write grant, and
  `varde runner` uses the existing `varde-runner service` mechanism;
- the prune fallback runs read-only `git rev-parse`.

## Native runner workspaces

The runner's native workspace API creates task worktrees under
`<repo>/.varde/worktrees/<id>`. The runner service needs read and write access
to that directory and the repository's common `.git` directory: it invokes
`git worktree add/remove` and updates the worktree branch. Workers launched in
these linked worktrees also need write access to the common `.git` directory
for commits and refs. Before removal, the runner invokes
`varde setup watch --stop --remove-index`. This deletes code-index data and
watcher service and registry files under `$VARDE_CONFIG_DIR` (default
`~/.config/varde`), and may run `launchctl` or `systemctl --user` to stop the
watcher. The CLI may resolve through `~/.local/bin/varde` to an installed
executable under `~/.local/share/varde/cli-releases`, so the runner may need
read access to that location.

Sandboxed clients that call the workspace API need loopback HTTP access to the
runner. They do not need access to `~/.paseo/worktrees` for native workspaces;
the existing Paseo grant remains for Paseo-managed workers until that
integration is removed.

## Pi Durable real-provider smoke

`runner/scripts/pi-durable-smoke-env.sh` reads the DeepSeek `api_key` from
`~/.pi/agent/auth.json`, or from `PI_DURABLE_AUTH_FILE` when set. It passes the
value only in the isolated runner's environment and suppresses runner output.

The invoking shell needs:

- Read access to the auth file.
- Write access to the system temporary directory.
- Write access to the runner's uv environment and cache when they need setup.
- Loopback HTTP access to the scratch runner.

The runner needs network access to the configured provider API.

## SQLite message inbox

The message database is `<working>/.cache/inbox/messages.sqlite3`. SQLite WAL
also creates `messages.sqlite3-wal` and `messages.sqlite3-shm` beside it. Every
consumer, including readers, needs read and write access to the `.cache/inbox`
directory: WAL connections may create or update the sidecars. A read-only inbox
cannot open the store. Keep the existing directory grant and Codex
`writable_roots` entry; SQLite adds no new permission path. Backend selection
may create `store-mode.lock`; mirror synchronization and mode transitions use
`mirror.lock` in this directory.

| Consumer | Sandbox that must allow the inbox directory |
| --- | --- |
| Prompt hook | The hook runs inside its host harness; that harness must grant the resolved `<working>/.cache/inbox`. |
| `varde msg` CLI | The invoking shell or harness sandbox must grant the same directory for reads and writes. |
| Runner and relay subprocess | The runner LaunchAgent has no filesystem sandbox in the measured setup; its `varde` relay subprocess uses the same inbox. If separately sandboxed, grant the directory to both. |
| Paseo workers | Grant the project working inbox to the task worker; Paseo workers also need read/write access to `~/.paseo/worktrees`. |
| Codex | Keep `workspace-write` and the existing absolute `.cache/inbox` path in `writable_roots`. |
| Pi | Its session or RPC worker sandbox must grant the resolved project inbox for any message CLI, hook, or adapter calls it runs. |
| OpenCode | Its session or HTTP worker sandbox must grant the resolved project inbox for any message CLI, hook, or adapter calls it runs. |

## SQLite plan state store

The plan state database is `<working>/.cache/data/queue.sqlite3`. Sandboxed
agents and the runner that operate on plans need read and write access to the
whole `<working>/.cache/data/` directory. SQLite can create `queue.sqlite3-wal`
and `queue.sqlite3-shm` beside the database. The same directory also holds
`queue.lock`, the `queue.version` schema marker, and backups under `backups/`.
The shared/exclusive mode barrier is `<working>/.queue.mode.lock` at the
working root, so agents and the runner also need write access to `<working>/`.
Granting only the database file or `.cache/data/` directory is insufficient.
Plan frontmatter exports also need write access to the relevant plan
directories and their `.plan.lock` files.

Durable slot commands (`varde plan slot ...`) use the same database,
`.cache/data/` directory, and `.queue.mode.lock` barrier, so the grants above
cover them. The `handoff` action also writes `checkpoint.json` and
`checkpoint.md` under `<working>/plans/<plan>/notes/checkpoints/<slot>/`, inside
the plan directory grant already required for plan state writes; no separate
slot path exists.

The mode lock is shared by queue, plan and task state readers/writers. Migration,
rollback and restore take its exclusive barrier; the lock file's parent must
remain writable while those operations run. See [Plan state store](plan-store.md)
for the runbook and exact command behavior.

Use the effective working directory for the active project. Do not grant only
`messages.sqlite3`: SQLite must be able to write the database directory and
both sidecars.

## Role queues

The role queue CLI reads `<working>/.cache/data/resources.json` to decide
whether a new item can start. The runner writes that file every 15 seconds;
sandboxed agents need read access to it. Missing or more than 60 seconds old
snapshots block new starts. The CLI and the runner endpoint read their start
limits from `[queue_budget]` in `$VARDE_RUNNER_CONFIG_DIR/runner.toml` (default
`~/.config/varde/runner.toml`), which the `~/.config` read grant below already
covers; `config.toml` is not read for them. Agents that pull, renew, finish,
release, and enqueue role-queue items, or
inspect them with `status` and `metrics`, also need read and write access to
`<working>/.cache/data/queue.sqlite3` and its containing `.cache/data/`
directory. SQLite writes WAL sidecars and queue metadata in that directory.
The existing SQLite plan state store grant above covers these paths.

The following Claude Code fragment shows the measured filesystem grants.
The `allowAllUnixSockets` line is unverified: it follows the Claude Code
settings reference (the alternative is an `allowUnixSockets` path list), and
settings load only at session start, so it was not tested. `allowLocalBinding` permits loopback TCP;
it did not permit Unix socket binding.

```json
{
  "sandbox": {
    "filesystem": {
      "allowRead": [
        "~/source", "~/.agents", "~/.claude", "~/.codex", "~/.cache/uv",
        "~/Library/Developer", "~/.config", "~/.cargo", "~/.rustup",
        "~/Documents", "~/not_cloud/Personal-Notes", "~/.local/share/uv", "~/.paseo/worktrees",
        ".git", "$TMPDIR"
      ],
      "allowWrite": [
        "~/source", "~/.agents", "~/.claude", "~/.codex", "~/.cache/uv",
        "~/Library/Developer", "~/.config", "~/.cargo", "~/.rustup",
        "~/Documents", "~/not_cloud/Personal-Notes", "~/.paseo/worktrees", ".git", "$TMPDIR",
        "/private/tmp/.dotnet"
      ],
      "denyRead": ["~/"]
    },
    "network": {
      "allowLocalBinding": true,
      "allowAllUnixSockets": true,
      "allowedDomains": [
        "chatgpt.com", "github.com", "api.github.com", "objects.githubusercontent.com",
        "raw.githubusercontent.com", "codeload.github.com", "*.nuget.org"
      ]
    }
  }
}
```

Agents running in Paseo task worktrees also need read and write access to `~/.paseo/worktrees`.

This Codex TOML fragment records the measured workspace-write mode and
additional writable roots. It does not establish that Codex permits Unix
socket binding; that behavior is unverified.

```toml
sandbox_mode = "workspace-write"

[sandbox_workspace_write]
network_access = true
writable_roots = [
  "/Users/<you>/.config/varde/toz",
  "/Users/<you>/.config/varde/learn",
  "/Users/<you>/.local/share/varde/projects/<name>-<hash>/working/.cache/inbox"
]
```

TOML treats `~` as a literal character, and Codex writable roots need absolute
paths, so use placeholders such as `/Users/<you>/...` and replace them with
your absolute paths.

Toz commands write captures under the toz root. Every `varde` invocation that
reaches the CLI entrypoint attempts to append a call row to
`cli_calls.jsonl` under the learn root. Hook invocations also need learn-root
write access when a worktree tool install is denied or pending inbox mail
blocks a stop; a read-only sandbox makes these optional records fail silently.
`varde learn` commands also write under the learn root. `varde msg address bind`
plus Paseo mailman relay commands write under `<working>/.cache/inbox`. When
the relay runs (the `serve` default; `VARDE_RUNNER_RELAY=0` disables it),
the runner's `varde` subprocesses use the same inbox path and need the same
write access.
`<working>` is the project's resolved working directory (see
`varde setup paths`), per project cwd. Unconfigured projects use
`<data>/varde/projects/<name>-<hash>/working`.

The learn root also holds the machine-managed store described in
[learn-store.md](learn-store.md). Grant write access to the whole directory:

- `learn.sqlite3` and its `-wal` and `-shm` sidecars.
- `learn.sqlite3.friction-backup`, `learn.sqlite3.ledger-backup` and
  `learn.sqlite3.calls-backup` (online backups from `varde learn store migrate`).
- `store-mode.json` (per-domain switch) and `store-mode.lock` (shared by
  writers, exclusive during a flip).
- A flip appends `learn.sqlite3*`, `store-mode.json` and `store-mode.lock` to an
  existing `.gitignore` in the learn root (it never creates one), so that file
  must be writable when it exists.
- `cli_calls.dropped.log` (one line per call that could not be recorded) and,
  after calls `retire`, `cli_calls.skipped.jsonl`.

A read-only learn root makes call recording fail silently and makes
`varde learn store migrate` fail.

The dashboard runs `varde learn sessions sweep --json`. Checked
`render_launchd` in `runner/src/varde_runner/service/__init__.py`: its LaunchAgent sets environment variables
and a working directory, but no filesystem sandbox, so the CLI inherits the
service user's access. The sweep reads repos from
`~/.config/varde/learn/sweep.toml` (parsed by learn itself;
default: Git repos directly under `~/source`), Codex sessions from `$CODEX_HOME` (default `~/.codex`), Claude
sessions from `$CLAUDE_CONFIG_DIR/projects` (default `~/.claude/projects`),
OpenCode's data root, optional Paseo sessions under `$PASEO_HOME`, Varde config,
and the learn ledger/friction store. It writes the learn store, runner state to
`<working>/.cache/learn/runner-sweep.json`, notification messages to
`<working>/.cache/inbox`, and their notes under
`<working>/.cache/learn/notifications/`. A host sandbox must permit those
reads and writes. `VARDE_LEARN_SWEEP_TIME` sets the daily UTC time in `HH:MM`
format; it defaults to `03:00`.

OpenCode configuration and Varde's synced skills, agents, and plugin use
`${XDG_CONFIG_HOME:-~/.config}/opencode`; permit that config root when running
setup with a custom `XDG_CONFIG_HOME`.

`varde learn run` reads session data from the roots in
`~/.config/varde/learn/sources.toml` and invokes the `claude` executable for
model analysis unless `--no-model` is set. Default roots are `$CODEX_HOME`
(`~/.codex`), `$CLAUDE_CONFIG_DIR/projects` (`~/.claude/projects`), the
OpenCode data directory (`$XDG_DATA_HOME/opencode` or
`~/.local/share/opencode`, or the parent of `OPENCODE_DB`), and
`$PI_CODING_AGENT_SESSION_DIR` (`~/.pi/agent/sessions`). Sandbox runs need
read access to each configured session root and execute access to `claude` on
`PATH`. Model-enabled runs append review state to `reviewed.jsonl`; all
non-dry-run modes write `reviews/<date>.md` under the learn store, normally
`~/.config/varde/learn`, so that store needs write access.
The scheduled review job runs at 04:00 UTC, is disabled by default, and uses a
100,000-token default run budget.

`varde msg soak --write --json` writes reports to `<working>/metrics/mail-soak/`,
runner state and failure notes to `<working>/.cache/mail-soak/`, and failure
notices to `<working>/.cache/inbox/`; `VARDE_MAIL_SOAK_TIME` sets the daily UTC
`HH:MM` run time (default `03:15`).

The C# golden-corpus tests `test_repository_items_pass_spec_behaviour_and_hygiene`
and `test_restricted_items_pass_spec_behaviour_and_hygiene`, the sample test
`test_sample_csharp_behaviors`, and the C# mutation behavior test
`test_csharp_operator_output_runs_through_behaviour_runner` run .NET. The
opt-in live Roslyn test `test_csharp_exporter_skips_non_call_expressions` also
restores and builds the runner. These tests need `/private/tmp/.dotnet` writable,
the macOS temp directory variant of `/tmp/.dotnet`, for first-use setup under
`/tmp/.dotnet/shm` and `*.nuget.org` for NuGet restore.

## Run the tests

### Sandbox-bound test conclusions

Run suites under `core/scripts/test-env.sh` (as `just test` and `just test-baseline` do). Bare `pytest` in the sandbox fails the app and code tests (pypi.org denied, grammar cache unwritable). `just test-baseline` covers the module pytest suites and fails on any failure; `just test` is the full gate.

- **Runner IPC send test.** `runner/tests/test_send_path.py::test_ipc_socket_send_returns_documented_outcome`
  binds a Unix socket, which the sandbox denies (`PermissionError` at `bind()`),
  so it uses the `require_unix_socket` fixture and skips with a stated reason.
  Main runs it unsandboxed before a runner deploy, from the repository root:
  `uv run pytest runner/tests/test_send_path.py::test_ipc_socket_send_returns_documented_outcome -q`.
  Rejected: `sandbox.network.allowAllUnixSockets: true`. The socket name is
  random, so no single path can be allowed, and the grant would open every Unix
  socket to all sandboxed commands for one test.
- **Tree-sitter grammars.** Seed `VARDE_TREE_SITTER_CACHE_DIR` from
  `<main checkout>/.varde/tree-sitter-cache` or `VARDE_TREE_SITTER_SEED_DIR`
  instead of downloading (GitHub TLS failed in the sandbox even when allowed).
- **`toz/tests/test_hook_startup.py`.** Needs `pypi.org` and
  `files.pythonhosted.org` only on a cold uv cache.
- **`test_bind_refusal_exposes_last_store_reason`.** Filesystem only; needs no
  allowance.

The measured `just test-all` run passed in the Claude sandbox after using
`core/scripts/test-env.sh`. It puts test state in the gitignored
`.scratch/test-home` under the worktree:

| Path or variable | Use |
| --- | --- |
| `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `VARDE_CONFIG_DIR` | Test user and config state under `.scratch/test-home`. |
| `VARDE_TREE_SITTER_CACHE_DIR` | Grammar cache under scratch, seeded from a prefetched cache. |
| `UV_CACHE_DIR` | Shared `~/.cache/uv`; keep this outside scratch. |
| `UV_OFFLINE=1` | Prevent uv from accessing the network during tests. |
| `TMPDIR` | Keep the sandbox-provided temporary directory. |

The tree-sitter grammar cache must be seeded because downloading grammars from
GitHub failed in the sandbox. Seed it from the prefetched
`<main checkout>/.varde/tree-sitter-cache` or set `VARDE_TREE_SITTER_SEED_DIR`.
The one-time grammar prefetch requires network access. Do not put `TMPDIR`
under the repo: Git writes `.git/config` and `.git/hooks` there, which the
sandbox denied. Deep worktree paths can also make Unix socket paths exceed the
104-byte limit.

Unix socket bind was denied, even with `sandbox.network.allowLocalBinding`
enabled. Five toz daemon tests skip with a stated reason when socket binding is
unavailable. The message delivery test skips only when it cannot create a
`multiprocessing.Semaphore(1)`. The remaining measured tests passed without
network access. No other test permission exception was needed.

The index build extracts files in a `ProcessPoolExecutor` (up to 8 workers, only
for 64 or more files). Under the Claude sandbox the pool cannot be created
(`sem_open` is denied, a `PermissionError`), so the build prints
`index build: process pool unavailable` to stderr and extracts serially. The
output is identical; the build is about 3 to 4 times slower. No permission
change is needed. Run unsandboxed to measure parallel timings.

The `varde-runner` Paseo adapter starts a Node sidecar and connects to it over a
Unix domain socket. Its client then connects to the Paseo daemon over loopback
WebSocket (default `127.0.0.1:6767`). Permit Unix socket creation and loopback
connections for runner adapter checks. Integration tests must set `PASEO_HOME`
to a temporary directory and use a loopback port; they must target an existing
workspace ID and never create a Paseo project.

The optional `claude-cli` adapter launches the installed official `claude`
executable directly. Its runtime needs permission to spawn that executable,
read and write Claude's configuration and session directories under
`~/.claude`, and reach Anthropic over the network. The CLI itself performs that
network access using the user's existing Claude Code login. The adapter
removes `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and
`CLAUDE_CODE_OAUTH_TOKEN`; `ANTHROPIC_BASE_URL` and Bedrock or Vertex routing
variables pass through unchanged. Startup orphan cleanup calls `ps` to verify
the saved process ID, start time, and command, then signals its process group.

The restricted bot profile (role `manager-bot`, `claude-cli` only) needs no new
permission. It launches the same `claude` executable with `--restricted`,
`--safe-mode`, `--strict-mcp-config` and a generated `--settings` file written
next to the session's spec in the adapter state directory (mode 0600,
`<session>.bot-settings.json`). Its child environment is an allowlist (`PATH`,
`HOME`, `USER`, `LOGNAME`, `LANG`, `LC_ALL`, `TERM`, `TMPDIR`, `XDG_*`) plus the
bot token, so the user's own Claude login stays reachable and no other
variable is inherited. The single real-harness smoke for this profile runs only
on the user's say-so, with the same network and login access as any
`claude-cli` session.

The optional `codex-app-server` adapter launches the installed official `codex`
executable directly. Its runtime needs permission to spawn that executable,
read and write Codex configuration and session state under `~/.codex`, and
write adapter process state under
`~/.local/share/varde-runner/codex-app-server`. The adapter never reads
`~/.codex/auth.json`; Codex reads its own login. The child inherits the current
environment, including any provider variables, and uses it to reach OpenAI
over the network. Version and protocol errors are reported when the first
session starts. The adapter probes
`codex --version` and `codex app-server generate-json-schema`, writing the
schema into a temporary `varde-codex-schema-*` directory. Startup orphan
cleanup calls `ps` to verify the saved process ID, start time, and command,
then signals its process group.

The optional `pi-rpc` adapter launches the installed official `pi` executable
in RPC mode. It needs permission to spawn `pi`, read Pi's own configuration
and read and write its session directory (or the configured
`PI_CODING_AGENT_DIR` and `PI_CODING_AGENT_SESSION_DIR`), and reach the model
provider over the network using Pi's existing login. Varde does not inspect Pi
credentials.
Adapter process identity is stored under
`~/.local/share/varde-runner/pi-rpc`; startup cleanup calls `/bin/ps` to
verify and stop an orphan process group. Pi tests and orphan recovery need
permission to run `/bin/ps`.

The optional `opencode-http` adapter launches the installed official
`opencode serve` executable bound to `127.0.0.1` on a free loopback port. It
needs process spawn permission, loopback HTTP access, and read/write access to
`~/.local/share/varde-runner/opencode-http` for runner-owned process state. The
server inherits the user's configured XDG directories, so it uses the user's
existing OpenCode login and data. Varde does not read credential files, copy
credentials, or add provider credentials to the environment; only a random
per-run `OPENCODE_PASSWORD` protects the loopback server. The user-level XDG
data, config, state, and cache directories must be available to the server.

The dashboard's native-agent launch API starts the enabled `claude` or `codex`
CLI directly. Permit the runner to spawn the selected executable and read the
Varde runner config (`~/.config/varde/runner.toml`, or under
`$VARDE_RUNNER_CONFIG_DIR`). The API uses loopback HTTP routes under
`/api/agents`. Launch accepts an existing workspace directory and creates no
worktree or workspace. The workspace may be any existing directory supplied by
the user, which the spawned CLI reads and writes. Runner session records are
stored under
`<working>/.cache/dashboard/sessions`; adapter process state is stored under
`~/.local/share/varde-runner/claude-cli` or
`~/.local/share/varde-runner/codex-app-server`.

### Paseo sidecar dependencies

Before running Paseo adapter checks, install the sidecar's pinned Node
dependencies from the repository root with
`npm ci --ignore-scripts --prefix runner/sidecar`.
The dashboard UI also installs its pinned dependencies with
`npm ci --ignore-scripts --prefix runner/ui`, then builds its self-hosted static
bundle with `npm run build --prefix runner/ui`. These commands require access to
`registry.npmjs.org`; neither application fetches assets from a CDN at runtime.
Both `node_modules/` directories and generated build output are ignored by Git.
`just test` and `just test-baseline` install these three projects before pytest.
They use `npm ci --offline --ignore-scripts`, skip installs only when a lockfile
hash matches the installed marker, and always build the UI. The npm cache must
contain the locked packages; otherwise npm reports the missing package and the
test entry point fails with an install error. The npm cache must be pre-warmed
before running the offline install. To prepare a worktree manually:

```sh
npm ci --ignore-scripts --prefix runner/ui
npm run build --prefix runner/ui
npm ci --ignore-scripts --prefix runner/sidecar
uv run playwright install chromium
uv run pytest runner/tests -q
```

Browser-test prerequisites are checked lazily when the shared browser fixture
starts, after pytest has applied `-k` selection. Non-browser tests can run
without a built UI or Chromium. A browser test fails immediately with the
missing setup step if the UI build is absent or Chromium cannot launch. The
sidecar dependency check runs when the live Paseo adapter test is explicitly
enabled.

### Runner Node host

When an engine plugin enables the Node host, the runner executes the configured
`node_host.node` binary (default `node`) with `runner/node-host/host.mjs` and an
engine module path. Permit execution of Node 22.19 or newer and read access to
the host and enabled engine files. A service unit must have Node on its `PATH`
or use an absolute `node_host.node` path. The runner does not install Node
packages automatically. Enabling an engine with `npm ci --ignore-scripts
--prefix <engine dir>` writes that engine's `node_modules`; if it declares
dependencies, npm needs registry access during that install. The host needs no
network access at runtime.

`runner/scripts/node-host-linux-check.sh` runs the host tests in a `node:22`
container. It needs permission to execute Podman and connect to the active
Podman service or machine, pull the Node image, and download uv, Python 3.14,
and Python test dependencies. The script mounts the checkout read-only and
runs package installs and tests in an ephemeral copy inside the container.

## Browser tests
`runner/tests/test_mailbox_ui.py` and `runner/tests/test_ui_catalog.py` launch Chromium; no new sandbox permission is needed.

The dashboard chat mobile check is registered as `npm run test:chat-mobile --prefix runner/ui`. It starts Vite on loopback and launches Playwright Chromium
from `PLAYWRIGHT_BROWSERS_PATH` (default: `~/Library/Caches/ms-playwright`). It
uses Chromium iPhone emulation and a synthetic `visualViewport` shrink to check
keyboard layout; this does not verify iOS Safari. Grant read access to the
configured browser directory when the sandbox cannot read Chromium resources.

The runner UI's WebKit iPhone viewport smoke test and the dual Python/Node
browser setup are documented in [WebKit testing](../runner/docs/webkit-testing.md).

The runner's browser tests (`runner/tests/test_web_browser.py`,
`test_roles_web.py`, `test_config.py::test_editor_browser_viewports`,
`test_newitem_browser.py`, `test_mailbox_ui.py`, `test_ui_catalog.py`) start uvicorn on loopback and drive headless
Chromium (Playwright `chromium_headless_shell`) at 390x844 and 1440x900. They
use `--single-process --no-zygote --disable-gpu` to avoid Chromium's Mach port
rendezvous registration. The tests reuse one page per module because closing a
page or context in single-process mode kills the browser; only the browser is
closed at module teardown. The page navigates to each test's fresh server and
clears local and session storage before test actions.

The browser binary and resources must be readable. If a sandboxed launch error
mentions an unreadable browser cache, allow `filesystem.allowRead` for the
configured `PLAYWRIGHT_BROWSERS_PATH` (or `~/Library/Caches/ms-playwright` on
macOS); reinstalling Chromium does not grant filesystem access. With the
single-process launch, browser tests need neither `allowMachLookup` nor
`allowAllUnixSockets`. A sandboxed browser launch failure is a test failure,
not a skip. AF_UNIX tests for the supervisor and Paseo sidecar still skip with a
reason when socket creation is denied.

| Need | Settings entry | Status |
| --- | --- | --- |
| Read the browser binary and its resources | `sandbox.filesystem.allowRead`: `"~/Library/Caches/ms-playwright"` | Required; applied 2026-10-19, fixes `icudtl.dat not found` |
| Profile and crash dirs | `$TMPDIR` (already writable) | Already granted |
| Loopback port bind for uvicorn and Chromium | `sandbox.network.allowLocalBinding`: `true` | Already granted |
| Unix sockets (supervisor and Paseo sidecar tests) | `sandbox.network.allowAllUnixSockets`: `true` | Browser tests do not need it; AF_UNIX tests skip when denied |

The `varde-review-ui` `scripts/shot.sh` capture runs sandboxed under the existing `ms-playwright` `allowRead` grant. It uses `--single-process --no-zygote`; without those flags, Chromium aborts with `bootstrap_check_in ... Permission denied (1100)`. UX review preflight, route walking, tile capture, and loading capture launch Chromium and WebKit; run them outside the Claude sandbox when Chromium fails with that Mach port error.

```json
{
  "sandbox": {
    "filesystem": { "allowRead": ["~/Library/Caches/ms-playwright"] },
    "network": {
      "allowLocalBinding": true
    }
  }
}
```

Alternative with no read grant: set `PLAYWRIGHT_BROWSERS_PATH` to a directory
under `~/source` and run `playwright install chromium-headless-shell` there;
the download needs `cdn.playwright.dev` and `storage.googleapis.com` in
`sandbox.network.allowedDomains` once.

Settings load only at session start. After applying them, rerun
`uv run pytest runner/tests -q` and add any further denial below.

## Persistent runner dashboard (macOS)

The optional `org.varde.runner` user LaunchAgent starts the dashboard at login
and restarts it after a crash. It runs from this checkout with `uv`, reads the
Varde working directory passed at install time, and writes logs under
`~/Library/Logs/Varde/`. It always binds to `127.0.0.1`; keep that loopback
binding when exposing the dashboard through a tunnel. The default port is
8765. Set another port with `--port` when installing. `install` also needs
`--working-dir` (or `VARDE_WORKING_DIR`) and takes `--enable-relay`.

Manage it with `varde-runner service install`, `start`, `stop`, and
`uninstall`. `install` writes `~/Library/LaunchAgents/org.varde.runner.plist`
and loads it. To expose it with Tailscale, run exactly:

```sh
tailscale serve --https=10000 http://127.0.0.1:8765
```

Extra allowed hostnames go in `allowed_hosts` in `runner.toml`; the Tailscale
Serve entry above needs the Tailscale hostname listed there.

The runner must continue binding to loopback. Do not bind it to a network
interface; Tailscale Serve is the HTTPS entry point.

Runner status returns `unknown` when a registered plugin has no login probe.
The current plugins do not run client status commands from this page, so no
additional process or credential-file permission is needed.

## Serve daemon (`varde serve`)

`varde serve` runs the `varde-serve` executable. One detached daemon per user
(`start_new_session`, no terminal, output discarded) serves the local API, the
event stream and the MCP backend. The `varde serve mcp` shim is a stdio process
that starts the daemon on its first tool call and reaches it over loopback.

- **Listen and connect:** the daemon binds `127.0.0.1` on a random port
  (`[serve] port` fixes it) and the shim, `varde serve stop`/`status` and tests
  connect to it. Claude Code sandboxes allow this with `allowLocalBinding`
  (loopback only). No outbound requests are made.
- **`$VARDE_CONFIG_DIR/serve/` (read and write, mode 0700):** `daemon.json`
  (pid and port), `daemon.lock`, `daemon.log` (the bind, one line per start),
  `token` (human scope) and `mcp-token` (agent scope), both mode 0600. The
  daemon creates both tokens at first start. The shim reads `mcp-token` and
  `daemon.json` only; it never opens `token`.
- **Agent sandboxes:** deny read on `serve/token` (human scope); the shim works
  with that denial. The shim also opens `daemon.lock` for writing, so it needs
  write on that file. Before trusting a daemon it runs `ps -o command= -p <pid>`
  to check the pid is a `varde-serve` process; if `ps` is not allowed the check
  is skipped (the pid must still be signalable). Loopback calls ignore
  `HTTP_PROXY`/`ALL_PROXY`. A sandboxed agent that can read `token` can
  answer decisions and change config; an unsandboxed same-user process can read
  both tokens, as with the runner's `user-credential.json`. `varde serve status`
  prints the token file path, never the value.
- **Working data:** the daemon reads and writes the project's working dir (plans,
  docs, `*.comments.jsonl`, the message inbox) and the friction store, and
  edits `$VARDE_CONFIG_DIR/config.toml` for allowlisted keys.
- **Writes are off by default.** Agent writes (comments, replies, mail, friction)
  and human writes (decision answers, config set; queue reorder answers 501 `reorder_not_wired` until decided) need
  `[serve] allow_edit = true`. The `mcp-token` is refused on every human-only
  route; `/shutdown` needs the human token.
- **Non-loopback bind:** only `[serve] bind = "<ip>"` allows it (for example a
  Tailscale address; needs listen permission on that interface, which
  `allowLocalBinding` does not cover). The token is then required on every
  non-public route, `[serve] hosts` lists extra accepted `Host` values, and the
  daemon writes the bind to `serve/daemon.log` once per start (and to stderr). IPv6 binds are supported. Never bind `0.0.0.0` by default.
- **Login limit:** `/auth/session` allows 5 bad tokens per minute per client address. Local clients share `127.0.0.1`, so a local process can still lock out the browser login for a minute.
- **Idle exit:** the daemon exits after `[serve] idle_s` (default 1800) with no
  request and no open event stream.
- **Tests:** `serve/tests` spawn real daemon subprocesses on loopback ports and
  send them `SIGKILL`/`SIGTERM`; they need loopback bind and connect and the
  temp dir only. `app/tests/test_serve_routes.py` runs `varde serve mcp`.

## Doc page server (`varde learn docs serve`)

`varde learn docs serve <doc>` binds a stdlib HTTP server to `127.0.0.1` on a random
port (or `--port`). `--host <ip>` accepts only `127.0.0.1` or an IPv4 address in
the Tailscale range `100.64.0.0/10` that is assigned to this machine (a failed
`bind()` with `EADDRNOTAVAIL` is reported as an error); `0.0.0.0`, LAN, public
and IPv6 addresses are refused before binding. A Tailscale bind needs listen
permission on that interface address (for Claude Code sandboxes,
`allowLocalBinding` covers loopback only, so run it outside the sandbox) and the
tailnet peer needs no other setup; no outbound requests are made. It needs loopback TCP
bind and connect permission and write access to the doc's directory (it
appends `<doc>.comments.jsonl` beside the doc). It makes no outbound requests
and needs no runner. Every route checks `Host` against `<bound ip>:<port>`, `127.0.0.1:<port>` or
`localhost:<port>` (MagicDNS names get 403; open the printed IP URL); `POST /comments` also needs the per-run token and a
matching `Origin`. The token is embedded in `GET /`, so any same-user local
process that can connect to the loopback port can read it. `GET /events`
rejects requests whose `Sec-Fetch-Site` is cross-site, so other origins cannot
read the stream. Its tests (`learn/tests/docs/test_pages_server.py`) bind
loopback ports and run `uv build --offline` for the wheel-contents check.

`learn/tests/docs/test_pages_browser.py` (slow tier) serves a temp plan on loopback and
drives headless Chromium (`--single-process --no-zygote --disable-gpu`) at
390x844. It needs the same `~/Library/Caches/ms-playwright` read grant as the
runner browser tests (see "Browser tests"); a missing browser fails the
test instead of skipping it. No other permission is needed.

### Remote access over Tailscale (`--host <tailscale-ip>`)

Decisions (user, 2026-10-31): Q1 token handshake (option 1); Q2 remote edit off
unless `--allow-edit` (option 2). Tailnet trust alone was rejected: the write
token is embedded in `GET /`, so any tailnet peer (including shared-in nodes)
could read it. On a non-loopback bind, `serve` prints
`http://<ip>:<port>/?k=<access key>` once. The first `GET /?k=<key>` (constant-
time compare) sets `varde_access_<port>=<key>; HttpOnly; SameSite=Strict; Path=/`
(no `Secure`: http over WireGuard) and answers `303` to `/`, so the key leaves
the address bar and history; a wrong key gets 403. The cookie gates `GET /`,
`/events`, `/block` and every POST (comments too, because agents
read them through `varde learn docs watch`, so an unauthenticated peer would be an
injection channel); `/static/*` stays open. The embedded write token is thus
only served to cookie holders. Edit and suggestion accept (`POST /edit`, `/accept`)
return 403 off loopback unless `--allow-edit` is passed. Loopback binds keep
today's behavior (no cookie, edit on). Tests bind loopback with a simulated
non-loopback policy and never bind a Tailscale address. The access key and
cookie are plain http between tailnet nodes; anyone who can read the printed
URL or the cookie on the user's machine can use them.

### Page assembly: answers, includes and source sidecars

Page CSP is `script-src 'self'` with no inline script and no `style=`; agent
output never runs as code, and no `custom` iframe or `/sandbox/*` route exists.
Only the host runtime (`static/*.js`) talks to the answer bridge: an input
component (choice, form, ranking, slider, decision, comment) posts one `answer`
row to `POST /comments`, with the same token and `Origin` checks as comments;
the server validates the value against the component's own props and answers
400 otherwise. Answers are appended to the page's own `<doc>.comments.jsonl`,
never to an included source, and are recorded and delivered by
`varde learn docs watch`, never executed.

Include source roots: an `include` fence may read only regular `.md` files that
resolve (`Path.resolve(strict=True)`) under the directory of the page holding
it, or under `<working>/plans/` from `varde setup paths --json`. Dotfiles and
secret-like names are refused, symlinks that leave the roots are refused, and
the source is opened with `O_NOFOLLOW`. This needs read access to those two
trees and nothing else.

Source-sidecar write scope: a comment on included text carries `part` (the
include statement's id). The server maps it through the page's own parsed
`include` statements to the source path and appends to that source's
`<source>.comments.jsonl`, so the write scope grows from the page's directory
to the sidecars of its included sources (including `<working>/plans/`). The
source and sidecar paths are resolved again at write time, must stay inside the
include roots, and the sidecar is opened with `O_NOFOLLOW`. An unknown `part`,
a traversal or absolute path, and a `part` on any row kind other than
`comment` answer 400 and write nothing. A read-only source directory fails the
comment with an error and never falls back to the page sidecar.

Live updates refresh only the blocks whose content hash changed.

## Deploy script

`runner/deploy/deploy.py` writes under `~/.local/share/varde/cli-releases/` and
`~/.local/bin/varde`, installs `varde-serve` the same way under
`~/.local/share/varde/serve-releases/` and `~/.local/bin/varde-serve`
(`--skip-serve` skips it; the PEX excludes `varde-serve`), runs `uv tool install` with `UV_TOOL_DIR` and
`UV_TOOL_BIN_DIR` set to the release directory, and runs
`uv run --project runner varde-runner service stop|start` to stop and start
the LaunchAgent. Run it from `/Users/alec/source/varde`: a
hook blocks `uv tool install` from linked worktrees. Inside the sandbox,
`uv` needs network or `--offline`, and the release and link paths need write
access. The sandbox write allowlist includes `~/.local/share/varde` and
`~/.local/bin`, so the deploy runs inside the sandbox. Run it unsandboxed only
if a path is still denied.

## Call-resolution quality audit

The dev-split call-resolution audit reads the shared repository cache at
`~/.cache/qsca-repos` and writes exported edges to its configured edge-cache
directory. It also writes records, metrics, and failures to the audit output
directory. Run it with an isolated `HOME`, `XDG_CONFIG_HOME`,
`XDG_DATA_HOME`, `XDG_CACHE_HOME`, and `VARDE_CONFIG_DIR`; seed
`VARDE_TREE_SITTER_CACHE_DIR` from the checkout's prefetched tree-sitter cache.
The repo cache needs read access, and the isolated home, seeded grammar cache,
edge cache, and audit output need write access. Keep `UV_CACHE_DIR` on the
shared uv cache so the runner can use the installed Python environment.

### C# dev corpus build

`code/bench/call-resolution/groundtruth/java-csharp/build_csharp_dev.py` reads the
pinned local clones under `~/source/reference-repos` (Newtonsoft.Json, Polly,
serilog; read-only, no fetch). It runs the Roslyn exporter with `dotnet`
(`/opt/homebrew/bin/dotnet`) and needs `/private/tmp/.dotnet` writable, a
writable `--env-root` for builds and the NuGet package cache, and
`*.nuget.org` for package restore. It writes only the dev files under
`code/bench/call-resolution/data/dev/java-csharp/`.

## Runner folder prompts

Run `varde-runner serve` once from a terminal and answer any operating-system
folder-access prompt. On macOS, it is unverified whether that grant also lets a
later launchd process access the folder. A child can still hang under launchd
when its configuration names a protected folder, until the startup diagnostic
identifies the cause and the user applies one of its fixes. The foreground
smoke checks liveness and PID stability; it verifies the access assumption only
when run against a configuration that touches the folder in question. If a
child produces no startup output, the runner's timeout diagnostic describes
this possibility and prints the runner executable and interpreter paths.
`varde-runner service doctor` checks known workspace directories through the
running runner. When the runner is unavailable, it reports that the shell result
may differ from the service.
