# Runner installation and service

From the repository root, install with `uv tool install ./runner`, or build a
standalone PEX with `uv run --locked python runner/pex/build.py <temp-dir>` and
run `<temp-dir>/varde-runner.pex`. Run `varde-runner serve` once from a
terminal. If macOS displays a folder-access prompt, answer it there. A service
has no interactive app to answer a prompt. When a child is silent at startup,
the runner emits a diagnostic after the configured timeout (30 seconds by
default); it names a possible pending OS folder-access prompt, prints the
runner executable and interpreter paths, and gives next steps.

`varde-runner service doctor` probes the workspace directories known to the
running service. Without a running service, it reports that the runner is unavailable and that
the shell result may differ.

Service definitions are optional generated text. Preview them with
`varde-runner service print launchd` or `varde-runner service print
systemd-user`. Install or
remove the per-user service with `varde-runner service install` and
`varde-runner service uninstall`. `install` (and `print`) need the data root:
pass `--working-dir <path>` or set `VARDE_WORKING_DIR`; with neither, they
refuse rather than guess. A leading `~` is expanded; the path must be
absolute and exist. It must match the root `varde msg` and plans use.
`--port <n>` sets the serve port (default 8765). On Linux, install enables lingering and
reports if that fails; an administrator can run `loginctl enable-linger` for
the account if required. Use `varde-runner service status` to inspect it, and
`varde-runner service stop` or `start` to control it without reinstalling.
On macOS, `stop` waits (up to 15 s) until launchd reports the job unloaded,
and `start` retries a failed `bootstrap` once, then fails with the launchctl
error. `status` prints "not loaded" and exits 3 when the job is not loaded.

## Mail relay

The runner handles queued mail with a deterministic relay worker. `varde-runner
serve` starts it by default; set `VARDE_RUNNER_RELAY=0` (or `off`) to disable it.
`install --enable-relay` is now redundant (it writes `VARDE_RUNNER_RELAY=1`
into the unit). To keep relay off in a service, add `VARDE_RUNNER_RELAY=0` to
the unit environment by hand; a re-run of `install` removes it. On Linux, install also removes `VARDE_WORKING_DIR` and
`VARDE_RUNNER_RELAY` lines from `~/.config/varde/runner.env`, because systemd
lets that file override the unit.
On service restart, a runner-owned mailman binding is superseded automatically;
the old worker exits and releases its session binding. A live non-runner mailman
still blocks startup, with its holder shown in `GET /api/relay`. The relay uses
the installed `varde` CLI for message-store operations. In-process access would
remove subprocess and exit-code handling, but `varde-runner` may depend only on
`varde-core`; binding and relay store APIs belong to `varde-workflow`. That
dependency change is not small, so shelling out remains the simpler boundary.
To roll back, `uninstall`, then `install` again without the flag.

## Deploy script

`python3 runner/deploy/deploy.py` deploys this checkout in one run. It reports
ok, warn, or fail for each step with timings:

1. `cli-swap`: installs the CLI into a private release directory under
   `~/.local/share/varde/cli-releases/<stamp>-<commit>/`, smoke tests it
   (`--version`, `plan --help`), then atomically replaces the
   `~/.local/bin/varde` symlink. A failure removes the new release and leaves
   the old link, so `varde` never disappears mid-deploy.
2. `cli-prune`: keeps the newest 3 releases (never fewer than 2, never the
   current link target).
3. `serve-swap`, `serve-prune`: the same atomic swap for the `varde-serve`
   tool built from `serve/`, into
   `~/.local/share/varde/serve-releases/<stamp>-<commit>/`, smoke tested with
   `varde-serve --version`, then repoints `~/.local/bin/varde-serve`. `varde
   serve` runs that executable (the `varde` app cannot depend on it and the PEX
   excludes it); without it `varde serve` prints how to install. A running
   daemon keeps its old code until the next `varde serve mcp` call sees a
   version difference and replaces it. Skip with `--skip-serve`; set
   `--serve-releases` and `--serve-link` to relocate it.
4. `ui-build`: builds the dashboard UI only when sources are newer than it.
5. `relay-wait`, `runner-stop`, `runner-start`, `runner-ready`, `endpoints`:
   restart the runner and check it. Stop and start run
   `uv run --project runner varde-runner service stop|start`, so they need no
   installed runner and no `sudo`. They need the LaunchAgent (macOS) or user
   unit (Linux) from `varde-runner service install`. These steps always run,
   even after a CLI warn or fail.

Skip steps with `--skip-cli`, `--skip-serve`, `--skip-ui`, `--skip-runner`. Tune with `--keep`,
`--port`, `--relay-wait`, `--ready-wait`. To roll back, run
`ln -sfn <previous release>/bin/varde ~/.local/bin/varde`. Do not move a
release directory: its shebangs point inside it.

## Dashboard UI build

The wheel ships the dashboard's compiled static UI, while Git tracks only its
source and `runner/ui/package-lock.json`. Before building a wheel, run
`npm ci --prefix runner/ui` and `npm run build --prefix runner/ui`. CI runs
the same locked build. The Starlette app serves those local files; if the UI
has not been built, `/` reports that clearly.

For an isolated smoke check without loading launchd, run
`uv run --project runner varde-runner serve --port 18765` with
`VARDE_WORKING_DIR` set to a temporary directory (any unused port other than
8765), then `curl http://127.0.0.1:18765/`. Lint an installed plist with
`plutil -lint ~/Library/LaunchAgents/org.varde.runner.plist`.
