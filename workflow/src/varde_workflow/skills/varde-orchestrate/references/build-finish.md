# Finish a built plan

After all tasks finish, the plan worktree ends with:

- a plan review;
- resolved findings;
- a complete end-state checklist.

## Implementation review

- The plan HEAD has passed a task gate, and `base` (where the plan branch started) is recorded.
- One agent review covers `<base>..HEAD` in architecture mode, judging:
  - code;
  - architecture;
  - conformance to the plan and tasks.
- In pipeline mode this review is the queued `<plan>-plan-review` item; no second review is dispatched.
- It writes `<plan-dir>/review.md` with conformance in a `## Conformance` section. Validate: the file exists in the required format and carries a verdict.
- Skill or agent-document changes also get the matching authoring review.

## Resolve findings

Findings are fixed through the review fix workflow. The user decides grouped intended-behaviour changes.

## End-state checklist

- [ ] Every acceptance criterion passes: run each `assert:` and inspect each `retrieve:`.
- [ ] Module changelogs updated for user-visible changes.
- [ ] `varde plan conclude <plan-dir>` succeeds for the merged HEAD; blockers it reports are resolved.
- [ ] Concluded plan material is distilled into knowledge before it is removed.
- [ ] Reported:
  - branch and base;
  - checks;
  - remaining concerns.
- [ ] The merge request went out as a `merge-ready` message and each user question as `needs-user`.
- [ ] Merged only after the relayed `APPROVED`, never on `HOLD` or `ASK-MORE`; sync and conclude wait for it. The orchestrator never writes the user's approval. Validate: `varde plan approve-merge <plan>` reports approval.
- [ ] The merged plan worktree is cleaned up.
- [ ] After its agents are archived, the Paseo workspace is archived (an orchestrator step).
- [ ] Push or PR only after the user's choice is relayed.
- [ ] CLI reinstalled when the plan changed it.
- [ ] Worker and reviewer `friction:` lines are recorded.
