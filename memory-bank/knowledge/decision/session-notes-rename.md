---
type: decision
title: Name session continuity documents session-notes
description: Records the session-notes rename, migration path, compatibility window, and alias-removal follow-up.
tags:
  - session-notes
  - migration
status: stable
---

# Name session continuity documents session-notes

Use `session-notes/<id>/notes.md` for the live session document. This name
describes its continuously updated context and next steps.

`varde setup migrate-session-notes` moves files from `<working>/handoffs/`
to `<working>/session-notes/` without changing their contents. It renames
`handoff.md` to `notes.md` under the same session ID. Keep `handoff.md` as a
legacy type-config so migrated artifacts remain valid during the compatibility
period.

Keep `context_handoff`, `[session].handoff_at_tokens`, and `--handoff` as
aliases for one release. The new provider, config key, and flag take
precedence. Remove these aliases, the legacy type-config, and dual-directory
reads in a separate follow-up one release after this rename ships.
