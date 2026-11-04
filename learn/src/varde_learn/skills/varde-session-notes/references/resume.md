# Resume a session from notes

- Candidates are open `type: session-notes` notes in
  `<working>/session-notes/*/notes.md` and unmigrated legacy `type: handoff`
  records in `<working>/handoffs/*/handoff.md`. With none, say so.
- Resume one candidate. With more than one, ask which as an inline numbered
  menu with a recommendation.
- Every link is labelled. Labels never block.
- Missing target: `missing`.
- `integrity: none`: `unknown`; re-read it before acting.
- `content_hashes`: recompute the complete path-to-hash list with
  `python3 scripts/session-notes-snapshot.py` per `references/snapshot.md`,
  wherever the note is stored.
  - Changed list: `modified`; identical list: `unchanged`.
  - Different hash kind (`git-blob`/`sha256`): `unknown`.
- These links are `unknown`:
  - legacy links with neither `integrity` nor `content_hashes`;
  - a missing or unresolvable baseline;
  - another repository or an external target;
  - a directory link without `content_hashes`;
  - a failed comparison.
- Targets resolve independently of the note's location (legacy relative
  targets resolve against recorded `cwd`).
- A current branch or HEAD that differs from the recorded value, and a `pwd`
  that differs from `cwd`, are reported as modified session context.
- Relevant `unknown` targets and modified knowledge links are re-read; the log
  of a modified plan link is read.
- The context and flags are summarized and next steps proposed; nothing is
  acted on before confirmation. Notes too thin to resume say what is missing.
- On confirmation, `status: resumed` is set.
