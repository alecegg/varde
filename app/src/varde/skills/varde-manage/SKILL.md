---
name: varde-manage
description: "Use this skill when the user wants to install, upgrade, or configure Varde skills, CLIs, and harness hooks, including sync targets and presets, store and memory paths, the runner switch, and capture privacy settings."
---

# Manage Varde setup

User-level changes such as `varde setup paths set`, `varde setup sync`, and
harness hook installation need no review gate.

## Install and configure

Read `references/setup.md` for install, upgrade, path, preset, hook, and capture
settings.

## Gotchas

- `varde-manage` is a harness skill, not a shell executable.
- Inspect existing configuration and loaded provenance before replacing an
  entry. Preserve unrelated settings; prefer a scoped override to a new tool.
