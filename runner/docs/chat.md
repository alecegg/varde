# Runner chat and instance threads

`/chat` is the manager thread. Each agent also has a private `instance:<agent_id>`
thread, opened from its plan task or from the Orchestrator and planner roster
groups. Instance threads stay readable after an agent is archived and do not
show an unread dot. Builder and reviewer instances are hidden from the home
page and main roster; a worker without a resolved plan appears under
**Unassigned** on `/agents`.

Messages belong to one thread. A `reply_to` id links a message to an earlier
user or bot message in that same thread; it does not change the recipient.
Handoff events show only the validated `Summary:` line and a link to the
handoff file. The handoff body remains in that file.

## Taking over an instance

Use **Take over** in an instance thread to hold its conversation. While held,
messages from other senders queue; messages sent by the user in that thread
still reach the instance. The holder renews its lease every 20 seconds. If the
runner receives no heartbeat for 90 seconds, the lease expires. **Release**
delivers queued messages oldest first, one per idle status. Only one browser
can hold an instance at a time; another takeover request receives `409`.
Queued messages remain persisted across runner restarts.

## Handoff files

Write handoffs with the nine sections in this order: `Summary:`, `Goal:`,
`Context:`, `State:`, `Next:`, `Open:`, `Reading list:`, `Pointers:`, and
`Do not redo:`. The validator enforces section order and the limits of 700
words and 5,000 characters overall, plus each section's item and length limits.
Validate before handing work to a replacement:

```sh
varde plan handoff-check path/to/HANDOFF.md
```

The command reports errors and warnings; a missing path in `Reading list:` is
a warning. Memory pointers are optional, and an untagged candidate defaults to
the project scope.
