# Persisted plans and review-scope updates

Load before initializing a persisted plan or updating a contract/scope.
Initialize one aggregate subject for the plan:

```sh
varde-workflow review init --plan <plan.md> --repository <repo-root> --scope <path> --json
```

Pass subject id, repository, and resolved memory paths to the reviewer, who
loads `references/review-gate-record.md` and records its own verdict. The
subject reads the live plan. An unchanged approved plan covers its declared
tasks. Tasks inherit the parent subject and approval; pass them the id and
memory paths rather than initializing per-task approvals.

For bounded work, use OCC `review contract` or `review expand` to update the
contract or add scope. `review expand` accepts repository `--scope` and explicit
external-file `--artifact` additions. Use the inspected version and obtain a
fresh independent verdict after material changes. Scope expansion preserves
the original baseline and captures newly included files; it never authorizes
changes outside the expanded scope retrospectively.

Run the start/resume checkpoint before dispatching approved tasks.
`readiness.data.planning_ready` reflects dependencies;
`readiness.data.implementation_ready` also includes review gates. Review
blockers allow planning and work selection, but never implementation.

Verified tasks may become `done` while the required aggregate final review is
pending. Finish all plan source, docs, spec, changelog, and verification changes
before that review. The plan cannot complete until current final evidence and
the complete checkpoint pass; run the check before `conclude`.
