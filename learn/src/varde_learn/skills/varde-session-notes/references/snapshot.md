# Session notes snapshot integrity

- Snapshot a directory only for a small owned artifact folder, such as one
  review folder.
- Every target exists before snapshotting; one missing target makes
  `scripts/session-notes-snapshot.py` exit 1 for all.
- The link's `content_hashes` holds `snapshots[<target>]` from
  `python3 scripts/session-notes-snapshot.py -- <target>...` as printed, and
  `skipped_symlinks` is reported.
