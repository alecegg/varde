<!-- kind: reference -->
# Optional `varde-workflow` CLI

`varde-workflow` validates workflow state and provides concept search and
maps. Use Write/Edit to write plans, tasks, handoffs, and notes. Review
commands and gated transitions require the CLI.

## Fallback rule

The fallback below applies only to reads and planning/bookkeeping. It never
applies to review evidence commands or gated implementation/completion
operations; if unavailable, stop those operations and report the missing
capability. Never replace approval with prose, hand-written evidence, or status
edits.

- Sandbox denial: retry once with escalated access, command unchanged.
- If that fails or the CLI errors, use Read/Grep and Write/Edit; name the lost
  capability once.
- `ok: false` with a validation code is a result, not an outage; fix the cause
  instead of routing around it.
- Never build or install the binary during another workflow.
