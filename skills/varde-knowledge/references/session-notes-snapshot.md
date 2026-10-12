# Session notes snapshot integrity

- Snapshot a directory only for a small owned artifact folder, such as one
  review folder.
- Check every target exists first; one missing target makes
  `scripts/session-notes-snapshot.py` exit 1 for all.
- Run `python3 scripts/session-notes-snapshot.py -- <target>...`, copy
  `snapshots[<target>]` into that link's `content_hashes` as printed, and
  report `skipped_symlinks`.
