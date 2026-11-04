# Usage window file

Live rating requires `--window-file` and `VARDE_CALIBRATE_ALLOW_LIVE=1`. There
is no default window path. The runner checks the supplied file against its
caller-provided current clock before it starts a client.

Create a TOML file with timezone-aware ISO 8601 timestamps, a positive hourly
call cap, and a non-empty stop rule:

```toml
start = "2026-10-19T09:00:00Z"
end = "2026-10-19T10:00:00Z"
cap_per_hour = 20
stop_rule = "stop_on_first_limit_message"
```

The planned calls for one invocation may not exceed `cap_per_hour`. The
`stop_rule` is recorded in the run manifest; clients must stop immediately if
they report a usage or rate limit.

The live data-sent statement and run manifest record pair identifiers and
SHA-256 hashes for code, task text, lens text, and idiom notes. They do not copy
the raw snippets into the manifest. The payload itself still contains the
listed snippets and rubric text and is sent to the selected provider.

The subprocess receives a scrubbed environment with `PATH` set only to the
client executable's directory, plus `CODEX_HOME` when configured and `LC_ALL`.
This can prevent a client wrapper from finding helper executables installed in
other directories; use a standalone client binary or place required helpers
beside it.
