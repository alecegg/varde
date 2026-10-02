# Resume a handoff

## Steps

1. List `status: open` handoffs under `<working>/handoffs/*/handoff.md`,
   reading frontmatter only, newest first, preferring a matching `cwd`, then
   `branch`, then `keywords`. If none, say so and suggest `varde-change` plans in flight.
2. With one candidate, resume it. With more than one, ask which to resume as
   an inline numbered menu with a recommendation.
3. Read it and label each link per **Label links**. Report a current branch or
   HEAD that differs from the recorded value, and a `pwd` that differs from
   `cwd`, as modified handoff context.
4. Re-read relevant `unknown` targets, read the log of a modified plan link,
   and re-read a modified knowledge link.
5. Summarize the context and flags, propose next steps, and wait for
   confirmation before acting. If the handoff is too thin, say what is missing.
6. On confirmation, set `status: resumed`.

## Label links

Resolve each link target independently of the handoff's location (legacy
relative targets resolve against recorded `cwd`), then label it; labels never
block:

- Missing target: `missing`.
- `integrity: none`: `unknown`; re-read it before acting.
- `content_hashes`: recompute the complete path-to-hash list with
  `python3 scripts/handoff-snapshot.py` per
  `references/handoff-snapshot.md`, wherever the handoff is stored. A changed
  list is `modified`; an identical one is `unchanged`; a hash kind
  (`git-blob`/`sha256`) differing from the recorded one is `unknown`.
- A link with neither `integrity` nor `content_hashes` (legacy), a missing or
  unresolvable baseline, another repository, an external target, a directory
  link without `content_hashes` (legacy), or a failed comparison: `unknown`.
