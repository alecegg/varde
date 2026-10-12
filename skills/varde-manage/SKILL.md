---
name: varde-manage
description: "Install, upgrade, or configure Varde skills, CLIs, and harness hooks. Not for authoring scan rules or output profiles (varde-customize) or triaging scan findings (varde-scan)."
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
- Report what changed and whether the intended configuration loaded; a
  successful command alone does not establish activation.
