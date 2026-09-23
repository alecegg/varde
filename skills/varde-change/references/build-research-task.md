# Research Task

For a task with `kind: "research"`. Its output is a lasting external reference doc or decision record, not code or tests — the task's `creates` field names the markdown file it must produce.

## Process

1. **Investigate directly by default.** Delegate a bounded research question
   only when fresh context or long-running external research materially helps.
2. **Use primary sources.** Read official docs, source code, specs, or
   first-party APIs, not secondary write-ups. Trace every claim to its source.
   A research task uses sources outside this repository. Codebase research uses
   `references/build-decomposition.md` instead.
3. **Write the findings to the file named in `creates`**, citing each claim's source (a URL, a spec section, a file path and line in the source project). If the task calls for a decision rather than a survey, end the doc with an explicit recommendation, not just a list of facts.
4. **Match the repo's existing convention** for where such notes live — check `<knowledge>/reference/` or a similar existing location before inventing a new one.

## Completion

A research task has no failing test or normal test command. It is done when the
output file exists, every claim is cited, and each `#### Verification` check
passes against that file. Mark completion by updating the task and appending a
Progress entry, following `references/build-execution.md`'s Completion section.

## When a research task turns out to need judgment, not just facts

If the investigation reveals a decision rather than facts, say so in the output
file and give a recommendation. Do not leave an unopinionated list of options.
