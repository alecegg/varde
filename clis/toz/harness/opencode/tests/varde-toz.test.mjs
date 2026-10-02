import assert from "node:assert/strict";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const root = await mkdtemp(join(tmpdir(), "toz-opencode-recovery-"));
const stored = join(root, "captures.jsonl");
const binary = join(root, "capture.cjs");
await writeFile(binary, `#!/usr/bin/env node
const fs=require('node:fs'); let input='';
process.stdin.setEncoding('utf8');
process.stdin.on('data',chunk=>input+=chunk);
process.stdin.on('end',()=>{
 const payload=JSON.parse(input);
 fs.appendFileSync(${JSON.stringify(stored)},JSON.stringify(payload)+'\\n');
 console.log(JSON.stringify({hookSpecificOutput:{updatedToolOutput:'preview handle saved'}}));
});
`);
await chmod(binary, 0o755);
const source = await readFile(new URL("../../../crates/toz/assets/opencode/toz.ts", import.meta.url), "utf8");
const adapter = join(root, "adapter.ts");
await writeFile(adapter, source.replace('const TOZ = "{{TOZ_BIN}}";', `const TOZ = ${JSON.stringify(binary)};`));
const { default: plugin } = await import(pathToFileURL(adapter).href);
const hooks = new Map();
await plugin.setup({
  location: { directory: root },
  session: { hook: async () => {} },
  shell: { hook: async () => {} },
  tool: { hook: async (name, handler) => hooks.set(name, handler) },
});
const capture = hooks.get("execute.after");
assert.equal(typeof capture, "function");

test.after(async () => { await rm(root, { recursive: true, force: true }); });

test("retain a nested MCP result before an execute summary omits it", async () => {
  await writeFile(stored, "");
  const middle = "ROW 11000 value=MIDDLE-RECOVERY";
  const full = "BEGIN\n" + "filler\n".repeat(160000) + middle + "\n" + "tail\n".repeat(160000) + "END\n";
  const file = { type: "file", uri: "file:///fixture", mime: "text/plain" };
  const child = {
    status: "completed", sessionID: "session-1", tool: "recovery_probe_emit", input: {},
    result: { content: [{ type: "text", text: full }, file] },
  };
  await capture(child);
  assert.equal(child.result.content[0].text, "preview handle saved");
  assert.strictEqual(child.result.content[1], file);
  const final = { status: "completed", sessionID: "session-1", tool: "execute", input: { code: "return 'done'" }, result: { output: "done" } };
  await capture(final);
  const entries = (await readFile(stored, "utf8")).trim().split("\n").map(JSON.parse);
  assert.equal(entries.length, 1, "small final summary does not replace the retained child result");
  assert.equal(entries[0].tool_response, full);
  assert.equal(entries[0].tool_name, "recovery_probe_emit");
  assert.equal(entries[0].session_id, "session-1");
  assert.ok(entries[0].tool_response.includes(middle), "omitted detail remains available without executing the tool again");
});

test("retain large final execute output and leave unfinished results alone", async () => {
  await writeFile(stored, "");
  const full = "aggregate detail\n".repeat(1000);
  const event = { status: "running", sessionID: "session-2", tool: "execute", input: { code: "return result" }, result: { output: full } };
  await capture(event);
  assert.equal(await readFile(stored, "utf8"), "");
  event.status = "completed";
  await capture(event);
  assert.equal(event.result.output, "preview handle saved");
  const retained = JSON.parse((await readFile(stored, "utf8")).trim());
  assert.equal(retained.tool_response, full);
  assert.equal(retained.tool_input.code, "return result");
});
