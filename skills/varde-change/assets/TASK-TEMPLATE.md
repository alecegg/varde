<!-- kind: reference -->
````
---
type: task
status: todo
depends_on: []
modifies: []
creates: []
renames: []
verification_resources: []
# requires_signoff: true  # plan-author opt-in; absent means false
# kind: research|spike   # optional: research is a cited doc; spike owns no paths, per references/plan-decomposition.md
---

<title>

<!-- optional task-specific context the executor can't cheaply re-derive -->

#### Test approach

profile: <tdd|regression|characterization|smoke|not-applicable>
rationale: <one-line reason for choosing this profile>

#### Out of scope

- <item>

#### Verification

- assert: <verification command or structural check> → <expected output>
- retrieve: <file(s) or grep to read for context> → targeted context for judgment

#### Progress

<!-- task owner only (parent after integration for isolated workers): one line per event (attempt, finding,
     verification, retry); end with `- evidence: <what ran, what it showed>` -->
````
