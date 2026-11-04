import { appendFile } from "node:fs/promises";
import { join } from "node:path";
import * as approvals from "../approvals.mjs";

const [directory, effectsPath] = process.argv.slice(2);
process.env.VARDE_PI_DURABLE_STORAGE_DIR = directory;
await approvals.init({ ctx: {
  emit(event, session, data) {
    process.stdout.write(`${JSON.stringify({ event, session, data })}\n`);
  },
  log() {},
} });
try {
  const result = await approvals.gateAndEffect({
    key: "conversation-1:call-1",
    tool: "bash",
    summary: "Run a harmless test effect",
    input: { command: "test" },
  }, async () => {
    await appendFile(effectsPath, "effect\n");
    return "effect result";
  });
  process.stdout.write(`${JSON.stringify({ result })}\n`);
} finally {
  await approvals.close();
}
