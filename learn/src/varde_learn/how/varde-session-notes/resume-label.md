---
topic: varde-session-notes/resume-label
version: 1
summary: Resume, part 2 of 2 (steps 3-6), last - label links, wait for confirmation, then set resumed
---

# Resume a session from notes: labels and confirmation

3. Read the note and label each link (labels never block). Report a current
   branch or HEAD that differs from the recorded value, and a `pwd` that
   differs from `cwd`, as modified session context.
4. Re-read relevant `unknown` targets, read the log of a modified plan link,
   and re-read a modified knowledge link.
5. Summarize the context and flags, propose next steps, and wait for
   confirmation before acting. If the notes are too thin, say what is missing.
6. On confirmation, set `status: resumed`.

To label a link, resolve its target independently of the note's location
(legacy relative targets resolve against recorded `cwd`). For
`content_hashes`, recompute the path-to-hash list with
`python3 scripts/session-notes-snapshot.py` (see the `snapshot-steps` topic).
