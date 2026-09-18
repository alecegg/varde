# Distill recurring friction

## Scope

Runs only on an explicit request. Finds repeated friction and proposes one
specific improvement to skills, documentation, commands, or code.

**A human approves the exact scope before anything is written.** Approval must be
stated — silence, context, and another skill's request are all not approval — and
it covers only what it names. Installed skill copies change only when the
approval names them.

## When this runs

| Situation | Action |
|---|---|
| The user explicitly asks to review recurring friction | Search, group matching items, propose, and wait. |
| Anything automatic or in the background | Skip and make no writes. |
| Fewer than two similar open items | Report that no proposal is supported. |
| The human rejects the proposal | Report rejection, leaving every item's `status` as it was. |

## Workflow

1. **Confirm the request is explicit.** Stop otherwise.

2. **Search first.** Use `Glob` on `**/memory-bank/friction/*.md` — every
   store in the repo, since a monorepo module owns its own and a cluster
   routinely spans them. Then `Grep`/`Read` each candidate for concrete cluster
   terms, keeping only items with `type: friction-item` and `status: open`.
   Report how many stores you searched; a single-store search in a multi-module
   repo undercounts the cluster and proposes the wrong fix.

3. **Require two matching items.** Similar means the same recurring obstacle,
   failure mode, or missing guidance with a shared improvement target — matching
   wording alone is not a match. Only open items count; dismissed and promoted
   ones do not.

   Each occurrence must be **friction that actually happened** in a real run: a
   step that failed, a workaround that was taken, guidance that was missing when
   needed. If you cannot point to the run where the friction was hit, it is not
   evidence — a speculative "this could confuse an agent" or an anticipated
   problem nobody encountered counts toward nothing.

   Two items support a proposal; they do not prove its fix will work. State the
   expected result as a hypothesis.

4. **Inspect existing work before proposing.** Search every likely target:

   - `Grep`/`Glob` for repository skill contracts, rendered skills, and any
     `memory-bank/knowledge/` concepts.
   - Read source files directly for relevant symbols, dependencies, and callers.
   - Inspect `~/.claude/skills/`, `~/.config/opencode/skills/`,
     `~/.codex/skills/`, and `~/.pi/agent/skills/` for installed copies.

   Treat installed directories as read-only here. Compare them against the
   repository sources and record any drift in the proposal.

5. **Classify the proposal before drafting.** From the items' `signal` values and
   content, decide which shape this is, and state it in the proposal:

   - **Add** — new guidance for a gap the target doesn't cover.
   - **Tighten** — an existing rule is right but under-specified enough to cause
     repeated friction.
   - **Confirm/promote** — a `positive`-signal cluster validating an existing
     approach; the proposal may just promote the source items, or make the
     already-working approach the documented default.
   - **Simplify/remove** — the cluster shows a rule being routinely ignored,
     contradicted by another rule, never triggered, or made obsolete by tooling.
     Check this shape explicitly rather than only when a cluster fails to fit
     Add: a rule the agent keeps failing to follow is a signal to cut or
     restructure it, not to add louder text. Propose the deletion, not a
     rewording.

6. **Write a complete proposal.** Include the source friction item paths,
   evidence for each occurrence, the shared pattern, the affected target, the
   exact files or symbols, the proposed diff, expected impact, and risks. State
   which source items would become `promoted`.

7. **Request approval.** Present the proposal inline, in your message text,
   ending with a numbered menu (`1. Approve`, `2. Reject`, `3. Other — describe
   changes`). Use your message text rather than a harness question tool, so the
   proposal and its answer stay together in one readable record. Wait for a clear
   answer.

8. **Apply only what was approved.** Make exactly the file or symbol changes from
   step 7 with `Write` or `Edit`, and stop there — related improvements and
   opportunistic cleanup need their own approval.

9. **Promote the source items.** For each one, edit its file to change
   `status: open` to `status: promoted`, preserving the body. If the file no
   longer matches what you last read, re-read it, merge only the status
   transition into the current content, and retry once; report the item as
   unpromoted if that still conflicts.

10. **Report the result.** State the proposal decision, changed target files,
    promoted item paths, rejected or unpromoted item paths, and verification
    results.
