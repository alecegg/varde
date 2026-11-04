---
name: varde-toz
description: "Use this skill when a tool result shows a capture handle, when command output is too large to read directly, or when several commands can be handled in one turn: query captured output by handle, or run batched commands and capture analysis in a QuickJS script."
recommends: [varde-learn]
---

# varde-toz

## Choose execution

- Use native code mode where the harness has it and hooks capture nested results (Pi, Codex with `code_mode`). Otherwise use `varde run run`.
- Retain results before filtering. Print a small summary with status, preview, and any capture handle.
- No handle means nothing was stored: small, read-only, or bounded output stays inline.
- Before a rerun, recover missing details with `varde run query` or `run --handle`. `varde run query --list` recovers a lost handle.

## Run a batch script

- Run several commands in one `varde run run --script -` call. Query one handle per call.
- Start every command with `varde run`, with no shell loop or `cd` first: hooks skip output only for commands that start with `varde run`. Flags: `varde run run --help`, `varde run query --help`.
- Scripts stop after 5000 ms by default. Pass `--timeout-ms` for long runs such as test suites.
- A `[redacted:...]` marker or `redacted N value(s)/pattern(s)` notice means a secret was masked, not that output was cut.
- A noisy capture alone does not trigger diagnosis or authorize a filter change.
- When `run` fails to start or a handle is missing, report the command, handle, and result.
- On a store access error, retry with harness escalation first. If access is still denied or the user declines, report the failing command, store path, and setting, and ask before setting a fallback directory.
