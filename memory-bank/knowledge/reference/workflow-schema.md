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

Readiness returns blockers and available transitions.
Blocked artifacts may still enter the `blocked` state.
Other transitions require resolved dependency readiness.

Accepted transitions use recoverable staged writes.
Rejected transitions never modify artifact source bytes.
