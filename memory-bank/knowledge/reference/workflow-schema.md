---
type: reference
status: stable
---

# Workflow schema

`varde-workflow` bundles workflow schema version `1`.
Core types are `plan` and `task`.

Projects add types through this committed path:

```text
memory-bank/knowledge/workflow/schema.yml
```

The file uses this shape:

```yaml
schema_version: 1
artifact_types:
  proposal:
    initial_state: draft
    states: [approved, draft]
    completion_states: [approved]
    transitions:
      draft: [approved]
      approved: []
```

Added types cannot replace core artifact types.
Every referenced state must appear within `states`.

Plan dependencies use sibling plan directory names.
Graph resolution follows `depends_on` recursively.
Missing, incomplete, and cyclic dependencies become blockers.

Readiness reports dependency availability in `planning_ready` and
review-gated availability in `implementation_ready`; `review` contains the
evidence check. A missing approval does not hide work from planning, but it
does prevent implementation. Blocked artifacts may still enter the `blocked`
state. Other transitions require resolved dependency readiness and any
required review checkpoint.

Accepted transitions use recoverable staged writes.
Rejected transitions never modify artifact source bytes.

## Isolated task ownership

An isolated executor returns source commits and checks; its approval-checkout
parent owns tracked and external task transitions after source integration.
An explicit scoped worktree binding authorizes start/resume only. It does not
change the owning plan's repository identity or authorize worker-side parent
state mutations. Spike completion requires restored exploratory source and
recorded question/approach/answer plus verification, without a source commit.
