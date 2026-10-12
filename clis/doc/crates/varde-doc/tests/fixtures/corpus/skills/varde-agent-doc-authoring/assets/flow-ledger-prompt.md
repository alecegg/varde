# Flow ledger auditor brief

Fill the `{{...}}` placeholders, then send this to one auditor subagent.

---

You are auditing the workflow decisions of one agent procedure. Read-only: edit no source. Write only `{{output}}`.

Source root: `{{root}}` at revision `{{revision}}`
Entry files (root-relative): {{entries}}
Route: {{route}}

Follow the flow from a request that enters at an entry file through every documented conditional variant, retry, interruption, error exit, and delegated agent procedure. Resolve each procedural call recursively until a tool boundary or an already inventoried procedure. Inspect runtime-generated instructions at their source.

## What counts

A decision is a workflow change: next action, dispatch target, repeat, pause, conditional persist (a write to a store the workflow reads later), or error exit. Do not count code-domain checklist outcomes, warnings, report wording, recommendation-only verdicts, computed names or paths, example code, or general prohibitions with no execution choice. Passive reference selection never counts: dispatch content, model or tier choice, evidence reads, style or template loading, config selection, advisory context, and lookups after which the flow continues unchanged. Count categories or personas only when selecting one changes dispatch or actions. CLI internals are atomic; count only documented response routing.

- `units`: a binary conditional or retry/iteration decision is 1. A mutually exclusive k-way choice is k-1. An explicit else belongs to its if. Merge outcomes that lead to the same action before applying k-1, even when written as separate bullets, and Boolean clauses that choose the same action are one decision. Independent optional actions are separate binary decisions; never fold them into one k-way choice.
- A criterion, tie-breaker, or override that picks among an existing choice's alternatives is part of that choice, not a new decision.
- An early-exit guard ("if X, stop" or "skip to step N") is one decision and adds no depth to the steps after it.
- A retry or review loop's condition is one decision. Later-round re-verdicts, re-running an already counted procedure, and bookkeeping that follows the path taken are not new decisions.
- Per-item iteration that changes the workflow (verify each requirement, process each finding) is one retry/iteration decision; decisions inside it are one level deeper.
- Routing of the user's answer after a pause counts when the answers lead to different next actions.
- `depth`: the number of enclosing counted conditions or loops, including the else branch of an if, measured from the top of each procedure. Inline sections inherit the depth where they sit. A called or delegated procedure restarts at 0, and so does a section reached from two or more sites, which is counted once. File and heading depth add nothing. An if inside a task iteration is 1; a retry loop in that iteration is 1, and a decision inside the retry is 2.
- Count each reusable procedure once, however many tasks, retries, or call sites reach it. A decision restated elsewhere, including one copied into two alternative procedures, is one entry; put the other citations in `duplicate_sources`.
- Count every reachable decision, including inline prose, agent-only and delegated procedures (prompt templates, agent definitions), and documented harness or platform variants that change actions. Optional alternatives all belong to the graph.

## Output

One JSON object, with every path relative to the source root and exact line bounds:

- `repository`, `revision`, `route` (description), `entries`.
- `routes`: map of route name to the list of `phase` values it includes. Required keys: `default` (the common path) and `whole` (every phase).
- `files`: every inspected instruction source: `path`, `classification` (procedure, reference, template, agent, or code-generated-instructions), `reason`.
- `decisions`: `id`, `phase`, `source`, `line_start`, `line_end`, `condition`, `alternatives` (concrete; two for a binary decision), `units` (alternatives - 1), `depth`, `hash`. Optional: `reason`, `duplicate_sources`. Leave `hash` as `""`; the coordinator fills it from source.
- `calls`: `caller`, `line`, `target`, `reason` for each procedural call.
- `exclusions`: `source`, `line_start`, `line_end`, `reason` for reachable text deliberately not counted.
- `unresolved_calls`: calls you could not follow. Mark a call to a tool or service outside the source with `"kind": "external-boundary"`. Anything else unresolved is a failure to close the flow; keep following it.
- `control_ambiguities`: each place two sources disagree on a control choice: `id`, `sources` (`source`, `line_start`, `line_end`), `note`.
- `coverage_notes`: what you checked and what you could not.

Never compute a score; put no numeric totals in the file. Do not call the closure exhaustive while any local call is unresolved.

## Before you report

Check that every `units` equals alternatives - 1, every cited range exists, and every procedural call is in `files`, `calls`, or `exclusions`. Reply with the output path, the count of decisions, and any unresolved calls or ambiguities.
