# Persisted plans and review-scope updates

## 1. Initialize one aggregate subject

Run `python3 <skill-dir>/scripts/risk-tier.py <scope-path>...` over the plan's
full scope first, from the repository root, and keep its JSON output; missing or
unreadable evidence defaults to high tier.

`review check` treats a plan as high tier, whatever `data.subject.tier` says, if
`## Open Questions` holds a `-` or `*` bullet, the frontmatter has a non-empty
`shared_contracts` list, or the plan body has no `assert:` marker.

```sh
varde-workflow review init --plan <plan.md> --repository <repo-root> --scope <path> --tier-evidence <risk-tier.json> --json
```

Tasks inherit the parent subject and approval; pass them the id and memory
paths instead of initializing per-task approvals.

## 2. Dispatch approved tasks

Run the start/resume checkpoint before dispatching approved tasks. The
readiness fields gate different work:

- `readiness.data.planning_ready`: dependencies only; review blockers still
  allow planning and work selection.
- `readiness.data.implementation_ready`: adds review gates; must pass before
  implementation. Low tier (`data.subject.tier`) with none of the §1 plan
  triggers needs no pre-edit record to pass this gate.

## 3. Conclude the plan

Run `conclude`; it requires current final evidence and a passing complete
checkpoint.

## Bounded work

- Replace the contract with `review contract`, or add `--scope`/`--artifact`
  coverage with `review expand` (`--tier-evidence` optional; omitted evidence
  reverts a low-tier subject to high); run either at the inspected version.
- Expansion snapshots only the added scope and never retroactively authorizes
  changes outside it, but it always recomputes the subject's baseline id: a
  pre-edit approval taken before an expand goes stale and needs a refresh.
