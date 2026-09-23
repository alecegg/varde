---
type: reference
title: varde init
---

# `varde init`

`varde init` is the repository's only root wiring entry point. It is not a
root build or test command. It installs skills and agents.

It detects supported harness configurations, or accepts explicit harness ids.
The supported ids are `claude`, `codex`, and `opencode`.

Run `./varde init --dry-run` to preview installer output. Run
`./varde init --yes` to wire detected harnesses without a prompt. Run
`./varde init --agents codex` to wire one harness.

The command does not modify harness startup configuration. Installed skill
descriptions remain authoritative for routing. Re-running installation preserves
unrelated files and protected local edits.

Without a terminal, `varde init` makes no changes. It prints the explicit
non-interactive command instead.
