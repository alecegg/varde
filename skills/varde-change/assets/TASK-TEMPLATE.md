<!-- kind: reference -->
````
---
type: task
status: todo          # todo | in_progress | blocked | done
depends_on: []        # task ids that must be `done` first
owns: []              # directory/, glob, or file
# posture: debug | refactor   # optional
---

<title>

<!-- optional task-specific context the builder can't cheaply re-derive -->

#### Acceptance criteria

- assert: <command or structural check> → <expected output>   # preferred
- retrieve: <file(s) or grep to read for context> → targeted context for judgment

#### Progress

<!-- plan owner only: one line per event (attempt, finding,
     verification, retry); end with `- evidence: <what ran, what it showed>` -->
````
