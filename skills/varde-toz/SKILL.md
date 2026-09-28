---
name: varde-toz
description: "Query captured tool output or run batched commands and capture analysis in a QuickJS script. Use when a tool result shows a toz handle, when output is too large to read directly, or when several commands can be handled in one turn. Not for installing Varde or authoring output profiles."
---

# varde-toz

Use `query` to retrieve captured output and `run` to batch commands or analyze captures. Harness hooks provide handles for large tool results.

## Query captures

```sh
varde-toz query --handle <H> "error" "failed"  # search one capture
varde-toz query "connection refused"            # search this project
varde-toz query --handle <H> --chunk 7           # read one chunk
varde-toz query --handle <H> --lines 120:160     # read a line range
varde-toz query --list                           # recent captures
varde-toz query --raw <raw-H> --stream stdout    # exact bytes, when retained
```

`--global`, `--source`, and `--all` narrow or expand searches. Normal query output is normalized and redacted. Exact raw bytes require an explicit raw request during capture and `[raw] enabled = true`; a raw handle expires.

A preview may come from a matching output profile: a TOC or head preview, or a script's summary. Read a profile script's extracted records with `varde-toz query --handle <H> --records <kind>`.

## Run a batch script

```sh
varde-toz run --script - <<'JS'
const result = vardeToz.exec({argv: ['/bin/ls', '-la']});
print(result.exitCode, JSON.stringify(result.capture));
JS
```

Use `--code '<js>'` for a one-liner. The parent stores complete searchable output from each `vardeToz.exec()` call, including short output, unless a never-capture rule excludes it. The script receives bounded previews and capture handles. Its printed result returns as a handle when allowed. `vardeToz.exec()` accepts `argv` or `shell` plus optional `cwd`, `env`, and `timeoutMs`.

For analysis, pass `--handle <H>` to `run` and use `vardeToz.eachLine(fn)`, `vardeToz.text()`, and `vardeToz.handle`. Prefer `eachLine` for large captures. `print(...)` and `console.log(...)` produce the result. Commands and capture reads can be mixed in one script. `--stream stderr` selects the other stream; `--partial` permits a still-running capture. `--timeout-ms` and `--memory-mb` adjust script limits.

Without `[sandbox]`, `run` inherits the launching shell's permissions. A harness sandbox still covers its worker and child commands; escalation passes on broader access. `vardeToz.exec()` can launch arbitrary commands. A `[sandbox]` section stays active unless `enabled = false`; `enabled = true` adds Seatbelt on macOS or Bubblewrap on Linux. Its policy defaults to workspace read/write and no network. If the backend cannot start, `run` fails.

If macOS reports `sandbox_apply: Operation not permitted`, retry with host sandbox escalation when available.

With toz's OS sandbox on, use `run` for commands within its grants. Otherwise use the harness tool; its hook can save only output the harness delivers.

For ordinary harness tool calls, use the harness normally, then pass any returned toz handle to `query` or `run --handle`. `varde-toz doctor` checks the installation.

Some harnesses only show a handle hint for structured results. Query that handle. toz's own output is never re-captured.

If a handle is missing, retrieval fails, or output appears truncated, run `varde-toz doctor --json` and report the command, handle, expected result, and actual result. Share tool output only when needed to reproduce the issue.

For session-level output inefficiency, invoke the installed `varde-learn`
skill when diagnosis is requested. Supply relevant capture handles and retrieval
limits; diagnosis owns session analysis and eligible friction capture. A noisy
capture alone does not trigger diagnosis or authorize a filter change.

For installation, configuration, or profile authoring, invoke the installed
`varde-manage` skill. If unavailable, report that setup guidance is missing;
continue capture retrieval with the commands above.
