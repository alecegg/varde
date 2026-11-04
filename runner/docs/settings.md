# Runner settings

Open **Settings** in the runner dashboard to review harness status and edit the
supported runner options. The page does not ask for API keys, tokens, or other
credentials.

## Editable options

The dashboard exposes registered harness `enabled` flags, the allowlisted
numeric `limits.max_live_instances` and `runner.idle_process_timeout_s` values,
and `runner.require_user_pairing`.
Pairing enforcement defaults off; enable it to require the paired browser cookie
and CSRF header for user-only writes. The setting takes effect after a restart.
The equivalent TOML is:

```toml
[runner]
require_user_pairing = true
idle_process_timeout_s = 600
```

The dashboard does not expose arbitrary TOML or secret-looking keys. Harness
values are checked against the current role configuration; a harness used by a
role must be changed in **Roles** first. Numeric limits show their accepted
bounds and invalid values are rejected inline before a save request.

The runner reads `runner.toml` from `$VARDE_RUNNER_CONFIG_DIR/runner.toml`, or
`~/.config/varde/runner.toml` by default. A successful edit writes the validated
configuration atomically, keeps the five newest timestamped `.bak` backups, and
appends changed allowlisted keys and values to
`$VARDE_RUNNER_STATE_DIR/config-changes.jsonl` (default
`~/.local/share/varde-runner/config-changes.jsonl`).

## Applying changes

Harness enabled flags, `runner.require_user_pairing`, and
`runner.idle_process_timeout_s` are reported as requiring a runner restart.
Numeric limits apply immediately and do not require one. The idle process
timeout defaults to 600 seconds; set it to `0` to disable reaping. When
a change needs a restart and the dashboard is running under the installed
`launchd` or `systemd` service,
**Restart runner** requests a managed restart. Otherwise the page explains that
dashboard restart is unavailable; use `varde-runner service start` to start the
installed service. The first-run checklist links to settings for missing harness
login, service, data-root, or default-role setup steps.

## Status checks

Settings status shows the runner version, data root, service state, and enabled
harness status. For a harness with a registered safe status command, the runner
invokes that command with a three-second timeout and maps recognized output to
a status. Raw command output is not shown, and the runner does not open credential
files directly for this check. A missing command, unsupported probe, or unrecognized response is shown
as unavailable rather than treated as a successful login.
