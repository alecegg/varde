---
name: varde-toz
description: "Query captured tool output or run batched commands and capture analysis in a QuickJS script. Use when a tool result shows a toz handle, when output is too large to read directly, or when several commands can be handled in one turn. Not for installing Varde or authoring output profiles."
---

# varde-toz

## Choose execution

1. Prefer native code mode or Programmatic Tool Calling when it can call the
   required tools and needed results remain recoverable after the script ends.
2. Retain results before filtering; print a small summary with status, preview,
   and any capture handle. Hooks capture only harness-supplied bytes;
   thresholds and never-capture rules still apply.
3. For clipped native results, analyze a verified complete persisted file or
   use `run` for a complete capture. Use `capture: true` when small command
   output also needs retention.
4. Recover missing details with `query` or `run --handle` before rerunning a
   command. Find unprinted handles with `query --list`.


## Query captures

```sh
varde-toz query --handle <H> "error" "failed"  # search one capture
varde-toz query "connection refused"            # search this project
varde-toz query --handle <H> --chunk 7           # read one chunk
varde-toz query --handle <H> --lines 120:160     # read a line range
varde-toz query --list                           # recent captures
varde-toz query --raw <raw-H> --stream stdout    # exact bytes, when retained
```

Widen searches with `--global` (every project) or `--all` (superseded
captures); filter with `--source`. Output is normalized and redacted; `--raw`
needs a raw-retained handle, and raw handles expire. A preview may come from a matching output profile (TOC, head, or
script summary); read a profile script's extracted records with
`--records <kind>`.

## Run a batch script

```sh
varde-toz run --script - <<'JS'
const result = vardeToz.exec({argv: ['/bin/ls', '-la']});
print(result.exitCode, result.capture.preview || result.stdout);
JS
```

- `--code '<js>'` runs a one-liner; `--timeout-ms` and `--memory-mb` adjust
  script limits.
- `vardeToz.exec({argv | shell, cwd?, env?, timeoutMs?, capture?, raw?})`
  runs the command.
- Combined output up to the capture threshold (max 64 KiB) is complete in
  `stdout`/`stderr` with `capture.state: "inline"`; larger output returns
  `capture.preview` and `capture.handle`. `capture: true` forces a capture;
  `raw: true` also retains raw bytes.
  Never-capture rules override both.
- Small results from `print(...)` or `console.log(...)` appear directly;
  overflow returns the normal preview and handle.
- To analyze a capture, pass `--handle <H>` and use `vardeToz.eachLine(fn)`
  (preferred for large captures), `vardeToz.text()`, or `vardeToz.handle`;
  commands and capture reads can mix in one script. `--stream stderr` selects
  the other stream; `--partial` permits a still-running capture.

If `run` fails to start, a handle is missing, or the store is denied, read
`references/troubleshooting.md`.

Session-level output inefficiency diagnosis: use `varde-learn`. A noisy capture
alone does not trigger diagnosis or authorize a filter change.

## Gotchas

- Capture hooks skip output only when the command starts with `varde-toz`. Run
  one `query` per call or batch reads inside `run`, not in a shell loop or
  after `cd`.
