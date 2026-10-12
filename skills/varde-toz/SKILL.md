---
name: varde-toz
description: "Query captured tool output or run batched commands and capture analysis in a QuickJS script. Use when a tool result shows a capture handle, when output is too large to read directly, or when several commands can be handled in one turn. Not for installing or configuring Varde (varde-manage) or authoring output profiles (varde-customize)."
recommends: [varde-learn]
---

# varde-toz

## Choose execution

1. Choose the route by harness:
   - Pi, or Codex with `code_mode` enabled: native code mode; hooks capture
     nested tool results.
   - No code mode (Claude Code, or Codex without `code_mode`): `varde run run`
     (below).
   - Any other code mode, including opencode `execute` and Programmatic Tool
     Calling: probe it once with a noisy command; continue only if the nested
     result shows a capture handle, otherwise use `varde run run`.
2. Retain results before filtering; print a small summary with status, preview,
   and any capture handle. Hooks capture only harness-supplied bytes;
   thresholds and never-capture rules still apply. No handle means nothing was
   stored: by default, read-only commands stay inline up to 16 KiB, and a
   command whose last pipeline stage bounds output (`head`, `tail`, `grep`,
   `sed -n`, `git log -n`) stays inline up to 64 KiB.
3. For clipped native results, analyze a verified complete persisted file or
   use `run` for a complete capture. Use `capture: true` when small command
   output also needs retention.
4. Recover missing details with `query` or `run --handle` before rerunning a
   command. Find unprinted handles with `query --list`.


## Query captures

`varde run query --handle <H> "error" "failed"`  # also `--chunk N`, `--lines A:B`, `--list`

Use `varde run query --help` for flags and query details.

## Run a batch script

`varde run run --script - <<'JS' ... vardeToz.exec({argv:[...]}) ... JS`

Use `varde run run --help` for flags, API, and capture behavior.

If `run` fails to start, a handle is missing, or the store is denied, read
`references/troubleshooting.md`.

Session-level output inefficiency diagnosis: load `varde-learn`: use your skill
tool, or read `../varde-learn/SKILL.md`. A noisy capture alone does not
trigger diagnosis or authorize a filter change.

## Gotchas

- A `[redacted:...]` marker or `redacted N value(s)/pattern(s): LABEL` notice
  means the hook masked a secret; the output was not cut.
- Capture hooks skip output only when the command starts with `varde run`. Run
  one `query` per call or batch reads inside `run`, not in a shell loop or
  after `cd`.
