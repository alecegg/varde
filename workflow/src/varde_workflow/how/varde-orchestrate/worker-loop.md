---
topic: varde-orchestrate/worker-loop
version: 1
summary: Builder and reviewer slot item loop, mail kinds, and worker handoff file
---

# Worker loop

Builder slot:

- Take the top unblocked item in its prepared worktree and run `varde plan gate`.
- Send `varde msg send --from <plan>-builder --to <plan> --kind info "ready <task>" --notes <absolute report path>`, then take the next item without waiting. If none is unblocked, notify `<plan>` and wait.
- For `fix:yes`, work in the plan worktree on the findings the orchestrator names.

Reviewer slot:

- Review the plan-level item the orchestrator enqueues, then take the next item.
- Send `varde msg send --from <plan>-reviewer --to <plan> --kind info "pass <item>" --notes <absolute report path>` or use `findings <item>`.
- Only the orchestrator sends `merge-ready` when the whole plan is ready.

Handoff file: overwrite `<plan-dir>/notes/<role>-handoff.md` (`builder` or `reviewer`) with:

- role and slot;
- current item and worktree path;
- queue position and completed commits (reviewer: completed review item IDs and commit SHAs);
- pending mail and required checks;
- decisions not in the plan or task, and gotchas;
- next step;
- open questions.

Then send `varde msg send --from <plan>-<role> --to <plan> --kind info "handoff <role>" --notes <absolute handoff path>`.
