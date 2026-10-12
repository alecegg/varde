---
type: reference
title: varde setup sync
description: Current setup sync command, target layout, options, and migration report.
---

# `varde setup sync`

Use `varde setup sync` to install or refresh the embedded skills and agents,
select harnesses, and migrate supported legacy Varde configuration. It resolves
saved targets or accepts explicit canonical targets.

## Target layout

Keep one canonical copy of skills and agents, for example
`~/.agents/skills` and `~/.agents/agents` or directories in a private Git repo.
Sync links those canonical files into each selected harness's skills and agent
directories by default.
Use `--link-mode copy` when harness files should be copies instead. The supported
harness ids are `claude`, `codex`, `opencode`, and `pi`.

For example:

```sh
varde setup sync --skills-dir ~/.agents/skills --agents-dir ~/.agents/agents
```

## Options

| Flag | Purpose |
|---|---|
| `--skills-dir <DIR>` | Canonical directory for installed skills. |
| `--agents-dir <DIR>` | Canonical directory for installed agents. |
| `--link-mode <MODE>` | Save and use `symlink` (default) or `copy` mode. |
| `--harnesses <IDS>` | Select comma-separated harness ids or `none`; by default, use detected harnesses. |
| `--instructions-target <FILE>` | Install the shared instruction block at this file; repeat for multiple targets. |
| `--dry-run` | Print the resolved setup and planned actions without saving settings. |
| `--json` | Print the migration report in a machine-output envelope. |

Run `varde setup sync --help` for the installed CLI's current syntax.

## Migration report

Sync reports installation targets and harness selection, then lists migration
actions. Depending on the files present, actions can move the legacy code store
from `~/.config/varde-code` into the `code` subdirectory of the resolved Varde
config directory. It moves a legacy Toz store (`tool-output-zone` or
`varde-toz` under `XDG_CONFIG_HOME`, or `~/.config` when unset) into that
directory's `toz` subdirectory. The report can also include migration markers,
pinning the resolved Toz store as the default, recognized Varde-owned legacy
binary removals from the Cargo install root, and stopping/re-registering code
watchers around a store move. Harness entries and the shared instruction block
are handled when selected.

Reports separate completed moves, skipped items, and items that could not be
rewritten. A dry run places planned actions in the `would` list and prefixes
their reasons with `prediction:`. Skips and failures include their reason and,
when available, a recovery command.
