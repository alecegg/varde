---
type: decision
description: The varde-learn friction store is a CLI-owned SQLite database under the varde config directory, following toz's store patterns.
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-25T00:00:00Z }
---

## What
Store friction items and adoptions in SQLite (`rusqlite` 0.40 `bundled`) at `~/.config/varde/learn/learn.db`, overridable by `[default].learn` in the global `~/.config/varde/config.toml` (set with `varde-workflow paths set --learn`), written only through `varde-learn`.

## Why
The store is global with concurrent writers, needs in-place status transitions and cross-project recurrence queries, and `~/.config` is writable in the usual agent sandbox.

## Constraints
- Copy (do not import) toz-core's patterns: WAL plus busy timeout, `meta.schema_version` forward migrations, a `VARDE_LEARN_STORE` override (no silent fallback), and refusal to place the store inside a git repo.
- Provide markdown `list`/`show`/`export`; without the CLI, skills report friction in their final message and write nothing.
- Keep the store out of cloud-synced folders and uncommitted; no separate config file.

## Related
- /decision/varde-learn-module.md
