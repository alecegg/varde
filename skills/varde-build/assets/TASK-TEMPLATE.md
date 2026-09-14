````
---
type: task
parent: <plan-id>
status: draft
verified: pending
depends_on: ["<dep-id>"]
modifies: []
creates: []
---

<title>

<!-- Optional context/design-notes the executor needs and can't cheaply
     re-derive — task-specific only, never restated shared standards. -->

#### Out of scope

- <item>

#### Verification

- assert: <verification command or structural check> → <expected output>
- retrieve: <file(s) or grep to read for context> → targeted context for judgment

#### Progress

<!-- Owned by this task's worker only. One line per meaningful event:
     start + execution attempt, investigation result, verification result,
     retry reason, completion summary. Never write plan.md here. -->
````

There is no `#### Acceptance criteria` section. Acceptance criteria are
**plan-level** (`plan.md`'s `## Acceptance criteria`), the contract of "done" for
the whole change; build verifies them once at the end of the run. A task's own
correctness gate is its `#### Verification` block — the `assert:`/`retrieve:`
checks that prove this slice works. Decomposition authors these task files from
the plan's spec + AC; see `references/DECOMPOSITION.md`.
