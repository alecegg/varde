import { setTimeout as pause } from "node:timers/promises";
import * as bridge from "../events.mjs";

const [directory, mode] = process.argv.slice(2);
process.env.VARDE_PI_DURABLE_STORAGE_DIR = directory;
const count = mode === "partial" ? 125 : 300;
const entries = Array.from({ length: count }, (_, index) => ({
  id: index + 1,
  kind: "pi.user",
  model: [{ role: "user", content: `message ${index + 1}` }],
}));
const wantedEvents = mode === "partial" ? 249 : 423;
let emitted = 0;
await bridge.init({ ctx: {
  emit() {
    emitted += 1;
    if (emitted === wantedEvents) process.stdout.write(`${mode === "partial" ? "ready" : "finished"}\n`);
  },
  log(_level, message) { process.stderr.write(`${message}\n`); },
} });
bridge.registerConversation("conversation-1", {
  async entries(query, limit, cursor) {
    const matching = entries.filter((entry) => entry.id >= query.minEntryId);
    const offset = cursor?.offset ?? 0;
    const items = matching.slice(offset, offset + limit);
    return { items, ...(offset + items.length < matching.length ? { next: { offset: offset + items.length } } : {}) };
  },
});
await bridge.methods["events.subscribe"]({ session: "conversation-1", after_cursor: mode === "partial" ? 1 : 177 });
if (mode === "partial") await new Promise(() => {});
await pause(10);
await bridge.close();
