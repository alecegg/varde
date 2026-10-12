<!-- kind: reference -->
# `varde` workflow commands

Write plans, tasks, session notes, knowledge notes, and handoffs with Write/Edit.

## Fallback rule

- When `varde` is missing: stop every operation, reads included, and ask the
  user to run `varde setup sync`. Never build or install the binary during
  another workflow.
- Sandbox denial (including a worker preflight probe): retry once with
  escalated access, command unchanged; if it still fails, return the evidence.
- `ok: false` with a validation code is a result, not an outage; fix the cause
  instead of routing around it.
- If `concept search`, `concept map`, or a plan or task status read still
  fails, use Read/Grep and name the lost capability once. Every other command
  stops and reports the failure.
- Never replace approval with prose, hand-written evidence, or status edits.
