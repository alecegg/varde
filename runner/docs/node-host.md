# Runner Node host

The generic host runs an ESM engine in a supervised Node process. The runner
requires Node 22.19 or newer. It checks the executable's version before use;
the host also checks its own runtime and reports a clear startup error.

The standalone `[node_host]` settings parser accepts:

```toml
[node_host]
node = "node"
restart_max = 3
restart_window_s = 300
call_timeout_s = 60
```

These are defaults when the table or a key is absent. A plugin may set an
engine-specific module path. Without one, the runner resolves
`runner/node-host/engines/<engine>/index.mjs` relative to the runner package;
relative configured paths use that same root. The engine plugin owns the
`NodeHost` lifecycle and closes it during plugin shutdown.
Host state changes are recorded at INFO level in the runner log as
`node_host_state` entries.

The host and engines are separate npm packages with separate lockfiles. They
have no dependencies unless an engine adds them. Install the selected engine
only when enabling it:

```sh
npm ci --ignore-scripts --prefix <engine-dir>
```

Do not install all engine packages as part of runner deployment. For a
systemd user service, make Node available on the service `PATH` or set
`node_host.node` to its absolute executable path. The same applies to
LaunchAgents that do not load the shell's Node version-manager setup.

Run the Linux lifecycle check with:

```sh
bash runner/scripts/node-host-linux-check.sh
```

It requires Podman and a running Podman machine on macOS. It pulls `node:22`,
copies the checkout into the temporary container, installs uv and Python 3.14,
then runs the Python and Node host tests. The script fails if Podman is missing
or the container checks fail.
