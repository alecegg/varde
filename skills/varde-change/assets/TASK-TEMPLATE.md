````
---
type: task
parent: <plan-id>
status: todo
depends_on: ["<dep-id>"]
modifies: []
creates: []
# Parallel manifests require explicit ownership and resources:
# modifies: []
# creates: []
# renames: []
# verification_resources: []
# Use impact:<repo-relative-path> for each confirmed consumer.
---

<title>

<!-- Optional context/design-notes the executor needs and can't cheaply
     re-derive — task-specific only, never restated shared standards. -->

#### Test approach

profile: <tdd|regression|characterization|smoke|not-applicable>
rationale: <one-line reason for choosing this profile>
# Optional strict TDD selection fields:
# strict_tdd: <required|waived|not-required|exception>
# profile_source: <user|repository|decomposition|exception>
# exception: <required only for strict_tdd=exception>

#### Impact evidence

query: <dependents or blast_radius query, including target file or symbol>
evidence: <short summary of affected consumers and relevant tests>
confirmation: <focused source paths read after the query>

Use `verification_resources` for the exact canonical impact identifiers from
the evidence. If `varde-code` is unavailable, name the manually inspected
consumers and tests instead. Keep identifiers opaque after `impact:`.

#### Out of scope

- <item>

#### Verification

- assert: <verification command or structural check> → <expected output>
- retrieve: <file(s) or grep to read for context> → targeted context for judgment

#### Progress

<!-- Owned by this task's worker only. One line per meaningful event:
     start + execution attempt, investigation result, verification result,
     retry reason, completion summary. End with one concise marker:
     `- evidence: profile=<profile>; checks=<profile checks>; result=pass;
     note=<short result>`. Never write plan.md here. -->
````

There is no `#### Acceptance criteria` section. Acceptance criteria are
**plan-level** (`plan.md`'s `## Acceptance criteria`), the definition of done for
the whole change; build verifies them once at the end of the run. A task's own
correctness check is its `#### Verification` block — the `assert:`/`retrieve:`
checks that prove this slice works. Decomposition authors these task files from
the plan's spec + AC; see `references/build-decomposition.md`.
