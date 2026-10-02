<!-- kind: reference -->
# `varde-workflow` CLI

Varde skills require `varde-workflow`. It validates workflow state and provides
concept search and maps. Use Write/Edit to write plans, tasks, handoffs, and
notes.

## Fallback rule

- Not on `PATH`: stop every operation, reads included, and ask the user to
  run `varde sync`. Never build or install the binary during another
  workflow.
- Sandbox denial: retry once with escalated access, command unchanged.
- `ok: false` with a validation code is a result, not an outage; fix the cause
  instead of routing around it.
- If `concept search`, `concept map`, or a plan or task status read still
  fails, use Read/Grep and name the lost capability once. Every other
  command, including `review inspect`, stops and reports the failure.
- Never replace approval with prose, hand-written evidence, or status edits.
