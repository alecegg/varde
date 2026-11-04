---
topic: varde-session-notes/snapshot-steps
version: 1
summary: How to snapshot link targets into content_hashes
---

# Snapshot link targets

1. Check every target exists first; one missing target makes
   `scripts/session-notes-snapshot.py` exit 1 for all.
2. Run `python3 scripts/session-notes-snapshot.py -- <target>...`.
3. Copy `snapshots[<target>]` into that link's `content_hashes` as printed,
   and report `skipped_symlinks`.

Snapshot a directory only for a small owned artifact folder, such as one
review folder.
