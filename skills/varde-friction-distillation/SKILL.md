---
name: varde-friction-distillation
description: >
  TRIGGER: Manually distill at least two similar open friction items into a
  human-approved improvement proposal.
  SKIP: Skip without explicit invocation, without two similar open items, or
  when the observation is not concrete recurring friction.
  Example phrases: "distill friction" or "review recurring friction".
---

## Scope

The `varde-friction-distillation` skill defines this manual review flow.

This skill distills captured friction into proposed improvements. It is
manual-only. It requires an explicit user or agent invocation.

Use LLM judgment to cluster open items by shared failure mode and target.
Do not treat keyword overlap or search ranking as similarity proof.

It may propose changes to skills, documentation, commands, or code. It must
never apply a proposal automatically — not on automatic/background
invocation (see Entry point dispatch), and not ahead of explicit human
approval for the exact proposal and scope. This is absolute:

- Never infer approval from silence or context.
- Never overwrite installed skill copies without approved scope.

## Entry point dispatch

| Invocation | Action |
|---|---|
| Explicit manual invocation | Search, cluster, propose, and await approval. |
| Automatic or background invocation | Skip and make no writes. |
| Fewer than two similar open items | Report no promotion eligibility. |
| Human rejects the proposal | Report rejection and leave all items unmodified. |

## Workflow

1. **Confirm manual invocation.** Stop if the invocation is not explicit.
   Do not treat another skill's request as approval to change anything.

2. **Search the friction directory first.** Use `Glob` on
   `memory-bank/friction/*.md`, then `Grep`/`Read` each candidate for
   concrete cluster terms, keeping only items with `type: friction-item` and
   `status: open`. Do not enumerate or mutate friction files before this
   search.

3. **Require the promotion threshold.** Find at least two similar open
   occurrences before proposing promotion. Similar means the same recurring
   obstacle, failure mode, or missing guidance with a shared improvement
   target. One item is never sufficient. Dismissed and promoted items do not
   count as open occurrences.

   Each occurrence must be **observed friction that actually happened** in a
   real run — a step that failed, a workaround that was taken, guidance that
   was missing when needed. A speculative "this could confuse an agent," an
   anticipated problem no one hit, or a bare suggestion is not an occurrence
   and does not count toward the threshold. If you cannot point to the run
   where each item's friction was hit, it is not evidence.

   Two occurrences license a proposal; they do not prove the fix works. Do not
   claim a change will eliminate the friction from two data points — state the
   pattern and the expected impact as a hypothesis the next runs will test, not
   a settled causal rule. One success or one failure is never a universal law.

4. **Search existing implementation before proposing.** Search all likely
   targets before drafting a proposal:

   - Use `Grep`/`Glob` for repository skill contracts, rendered skills, and
     any `memory-bank/knowledge/` concepts.
   - Read supported source files directly to inspect relevant symbols,
     dependencies, and callers.
   - Inspect `~/.claude/skills/`, `~/.config/opencode/skills/`,
     `~/.codex/skills/`, and `~/.pi/agent/skills/` for installed copies.

   Treat installed directories as read-only during analysis. Compare them
   with repository sources. Record any installed drift in the proposal.

5. **Classify the proposal shape before drafting.** Decide, from the
   cluster's `signal` values and content, whether this is:
   - **Add** — new guidance for a gap the target doesn't cover yet.
   - **Tighten** — an existing rule is right but under-specified or
     ambiguous enough to cause repeated friction.
   - **Confirm/promote** — a `positive`-signal cluster validating an
     existing rule or approach as-is; the proposal may be a no-op edit
     (just promoting the source items) or a small addition that makes the
     already-working approach the documented default.
   - **Simplify/remove** — the cluster shows a rule being routinely
     ignored, contradicted by another rule, never actually triggered, or
     made obsolete by tooling. Check this shape explicitly, not just when a
     cluster fails to fit Add — a rule the agent keeps failing to follow is
     a signal to cut or restructure it, not to add louder text reinforcing
     it. Propose the deletion or restructuring, not a rewording.
   State the shape in the proposal.

6. **Draft a complete proposal.** Include the source friction item file
   paths, evidence for each occurrence, the shared pattern, the affected
   target, the exact files or symbols, the proposed diff, expected impact,
   and risks. State which source items would become `promoted`. A threshold
   match only grants proposal eligibility. It does not authorize any edit.

7. **Request explicit human approval.** Present the proposal inline, in your
   message text, ending with a numbered menu (e.g. `1. Approve`, `2. Reject`,
   `3. Other — describe changes`) — never a harness's native
   question-prompt tool (e.g. Claude Code's `AskUserQuestion`), since that
   renders outside the continuous transcript and the proposal/answer pair
   won't stay together in one readable record. Wait for a clear approval or
   rejection. Approval must cover the exact proposed scope. Do not apply
   related improvements that were not approved.

8. **Handle rejection without mutation.** On rejection, make no target
   edits. Leave every source friction item unchanged, including its
   `status`.

9. **Apply only the approved proposal.** Apply only the approved file or
   symbol changes (the exact scope from step 7) with normal `Write` or `Edit`
   operations. Do not modify installed copies unless the approval names those
   copies. Do not make opportunistic cleanup edits.

10. **Promote source items after the approved change.** For each source item:

   1. `Read` the item file.
   2. Apply a targeted `Edit` to the item file. Preserve the body and change
      only `status: open` to `status: promoted`.
   3. Re-read with `Read` and verify `status: promoted`.

   If a concurrent edit is discovered (the file content no longer matches
   what was last read), re-read the current item, merge only the status
   transition into that current content, and retry the edit. If the retry
   still conflicts, stop that item and report it as unpromoted.

11. **Report the result.** State the proposal decision, changed target files,
    promoted item file paths, rejected or unpromoted item file paths, and
    verification results. Never claim promotion without a confirming `Read`
    result.
