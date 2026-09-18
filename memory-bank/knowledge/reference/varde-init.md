---
type: reference
title: varde init
---

# `varde init`

`varde init` is the repository's only root wiring entry point. It is not a
root build or test command.

It detects supported harness configurations, or accepts explicit harness ids.
The supported ids are `claude`, `codex`, and `opencode`.

Run `./varde init --dry-run` to preview installer output. Run
`./varde init --yes` to wire detected harnesses without a prompt. Run
`./varde init --agents codex` to wire one harness.

The script writes no harness instructions itself. It delegates skills and
agent installation to each module's installer. Re-running it preserves files
that varde does not own.

Without a terminal, `varde init` makes no changes. It prints the explicit
non-interactive command instead.
