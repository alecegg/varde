# Research Task

For a task with `kind: "research"`. Its output is a durable external reference doc or decision record, not code or tests — the task's `creates` field names the markdown file it must produce.

## Process

1. **Investigate directly by default.** Delegate a bounded research question
   only when fresh context or long-running external research materially helps.
2. **Investigate against primary sources** — official docs, source code, specs, first-party APIs — not a secondary write-up of them. Follow every claim back to the source that owns it. This is what distinguishes a research task from a codebase-research subagent (see `references/DECOMPOSITION.md`): the sources here are external to this repo.
3. **Write the findings to the file named in `creates`**, citing each claim's source (a URL, a spec section, a file path and line in the source project). If the task calls for a decision rather than a survey, end the doc with an explicit recommendation, not just a list of facts.
4. **Match the repo's existing convention** for where such notes live — check `memory-bank/knowledge/reference/` or a similar existing location before inventing a new one.

## Completion

There is no failing test and no verification command in the usual sense. A research task is done when the output file exists, every claim in it is cited, and it satisfies the task's `#### Verification` checks — check each against the written file directly. Signal completion by patching the task section and appending a Progress log entry, per `EXECUTION.md`'s Completion section.

## When a research task turns out to need judgment, not just facts

If the investigation surfaces a decision rather than a pure fact-finding result (e.g. "which of these three libraries should we adopt"), say so explicitly in the output file and give a recommendation — don't leave the task's verification unresolved by handing back an unopinionated list of options.
