---
topic: varde-toz/choose-execution
version: 1
summary: Pick native code mode or varde run run per harness; handle clipped results
---

- Pi, or Codex with `code_mode` enabled: use native code mode. Hooks capture nested tool results.
- No code mode (Claude Code, or Codex without `code_mode`): use `varde run run`.
- Any other code mode, including opencode `execute` and Programmatic Tool Calling: probe it once with a noisy command. Continue only if the nested result shows a capture handle. Otherwise use `varde run run`.
- Hooks capture only harness-supplied bytes. Thresholds and never-capture rules still apply.
- No handle means nothing was stored.
- Hooks never recapture `query` output.
- By default, hooks keep these inline up to 64 KiB:
  - file reads
  - read-only commands
  - commands whose last pipeline stage bounds output (`head`, `tail`, `grep`, `sed -n`, `git log -n`)
- For clipped native results, analyze a verified complete persisted file, or use `run` for a complete capture. Use `capture: true` to retain small command output.
- Find unprinted handles with `varde run query --list`.
