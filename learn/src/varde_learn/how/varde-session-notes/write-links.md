---
topic: varde-session-notes/write-links
version: 1
summary: Write notes, part 2 of 3 (step 3), after write-steps - links; then write-save
---

# Write session notes: links

3. **Choose links** that hold what is needed to resume without rediscovery,
   as `{target, kind, integrity}`:

   | `kind` | Target |
   |---|---|
   | `file` | A file path |
   | `plan` | The plan that owns the work; its own log holds the fuller history |
   | `review` | A review folder or findings file |
   | `knowledge` | A note harvested from this work; reference it, never restate it |

   Default to `integrity: none`. Use `integrity: snapshot` with
   `content_hashes` (`snapshot-steps` topic) when the user requests drift
   detection or the notes are long-lived or high-risk. Prefer explicit relevant file links inside
   and outside the repository; for a large target, link the relevant files and
   never imply full-directory coverage. Resolve each target independently of
   the notes' location, store absolute paths, and drop and report missing ones
   before running the snapshot script.
