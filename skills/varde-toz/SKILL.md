---
name: varde-toz
description: "Query captured tool output or run batched commands and capture analysis in a QuickJS script. Use when a tool result shows a toz handle, when output is too large to read directly, or when several commands can be handled in one turn. Not for installing Varde or authoring output profiles."
---

# varde-toz

Pass any handle to `query` or `run --handle`; output is skipped by capture hooks
only when the command starts with `varde-toz`. Run one `query` per call or batch
reads inside `run`, not in a shell loop or after `cd`.

## Query captures

```sh
varde-toz query --handle <H> "error" "failed"  # search one capture
varde-toz query "connection refused"            # search this project
varde-toz query --handle <H> --chunk 7           # read one chunk
varde-toz query --handle <H> --lines 120:160     # read a line range
varde-toz query --list                           # recent captures
varde-toz query --raw <raw-H> --stream stdout    # exact bytes, when retained
```

Scope searches with `--global`, `--source`, or `--all`. Output is
normalized and redacted; `--raw` needs a raw-retained handle, and raw handles
expire. A preview may come from a matching output profile (TOC, head, or
script summary); read a profile script's extracted records with
`--records <kind>`.

## Run a batch script

```sh
varde-toz run --script - <<'JS'
const result = vardeToz.exec({argv: ['/bin/ls', '-la']});
print(result.exitCode, result.capture.handle || result.stdout);
JS
```

- `--code '<js>'` runs a one-liner; `--timeout-ms` and `--memory-mb` adjust
  script limits.
- `vardeToz.exec({argv | shell, cwd?, env?, timeoutMs?, capture?, raw?})`
  runs the command.
- Combined output up to the capture threshold (max 64 KiB) is complete in
  `stdout`/`stderr` with `capture.state: "inline"`; larger output gets a
  handle. `capture: true` forces a handle; `raw: true` also retains raw bytes.
  Never-capture rules override both.
- `print(...)` and `console.log(...)` produce the script's result, which is
  captured separately and may get its own handle.
- To analyze a capture, pass `--handle <H>` and use `vardeToz.eachLine(fn)`
  (preferred for large captures), `vardeToz.text()`, or `vardeToz.handle`;
  commands and capture reads can mix in one script. `--stream stderr` selects
  the other stream; `--partial` permits a still-running capture.

If `run` fails to start, a handle is missing, or the store is denied, read
`references/troubleshooting.md`.

## Related skills

- Session-level output inefficiency: when diagnosis is requested, invoke the
  installed `varde-learn` skill with relevant handles and retrieval limits. A
  noisy capture alone does not trigger diagnosis or authorize a filter change.
