import { usageEvent } from "./usage.mjs";

export function entryEvents(entry, models) {
  const events = [
    { type: "entry_appended", entryId: entry.id, kind: entry.kind },
  ];
  for (const [messageIndex, message] of (entry.model ?? []).entries()) {
    events.push({
      type: message.role === "toolResult" ? "tool_result" : "message",
      entryId: entry.id,
      messageIndex,
      role: message.role,
      content: message.content,
      toolCallId: message.toolCallId,
    });
    const usage = usageEvent(message, models);
    if (usage) events.push({ ...usage, entryId: entry.id, messageIndex });
  }
  if (entry.kind === "pi.compaction") events.push(...compactionEvents(entry));
  return events;
}

export function compactionEvents(entry) {
  return [{
    type: "activity",
    activity: "compaction",
    entryId: entry.id,
    reason: entry.data?.reason,
  }];
}
