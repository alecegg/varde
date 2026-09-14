## Phase 0: Refresh specifications first

If the repository maintains generated specification documents (for example under
`memory-bank/knowledge/specs/`), check whether they are current before touching
any user-facing docs:

1. If `varde-code` is available (`references/VARDE-CODE-CLI.md`) and the spec's
   frontmatter carries a `source_commit`/`source_hash`, diff since that
   watermark via `detect_changes` to find which specs actually need
   rereading — skip specs with no hits. Otherwise read each spec document
   and the source files it describes and compare them by hand: does the
   spec still match the current code structure, APIs, and behavior?
2. For any spec that is stale or missing content, regenerate it directly —
   read the relevant source primarily via CLI symbol queries when
   available (or inspect subsystems directly, delegating only when fresh context
   is genuinely useful) and
   rewrite the spec's markdown by hand.

If the repository has no such spec documents, skip this phase and continue to
Phase 1.
