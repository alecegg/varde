# Debug Posture

## Debug mode

Run in exactly one mode. Name it to the user in plain words:

| Mode | Use for | Run |
|---|---|---|
| `diagnose` | diagnosis-only requests | reproduce, test hypotheses, then report `debug_evidence` |
| `fix` | a requested bug fix or regression repair | also add the regression test and the fix |

In `diagnose`, production source is read-only: no fix, regression test, or
commit, and instrumentation stays outside production source.

## Evidence contract

Report `debug_evidence` in chat and, when a task file exists, append it under
`#### Progress` in this order:

- `reproduction`: the deterministic command and observed symptom, or bounded
  trace/source evidence with its origin, version or time, and reproduction
  limit.
- `hypotheses`, `experiments`, `cause`, `verification`.

Required fields:

- **`fix`:** `reproduction`, `hypotheses`, and `experiments` before any
  production edit; a completed fix adds `cause` and `verification`.
- **`diagnose`:** may leave `cause` uncertain; state the evidence limit.
- **Missing field:** stop before mutation and report it; a passing smoke check
  is no substitute.

## When progress stops

Standalone: no numeric budget. If blocked, or if another fix attempt would
repeat a failed approach, state what evidence, approach, or access must change
before trying again. Report it with `debug_evidence`.

## Finish

`diagnose` needs no review; `fix` gets the independent review.

Before declaring done, remove all `[DEBUG-...]` instrumentation and throwaway
prototypes; when committing, state the proven hypothesis in the commit message.

A standalone `fix` commits verified paths before the independent review in
`references/review-gates.md`; merge only when asked.
