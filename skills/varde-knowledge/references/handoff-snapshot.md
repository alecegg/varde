# Handoff snapshot integrity

- Snapshot a directory only for a small owned artifact folder, such as one
  review folder.
- Check every target exists first; one missing target makes
  `scripts/handoff-snapshot.py` exit 1 for all.
- Run `python3 scripts/handoff-snapshot.py -- <target>...`, copy
  `snapshots[<target>]` into that link's `content_hashes` as printed, and
  report `skipped_symlinks`.
