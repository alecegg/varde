import assert from "node:assert/strict";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const root = await mkdtemp(join(tmpdir(), "varde-hooks-"));
const logPath = join(root, "calls.jsonl");
const fakePath = join(root, "fake-varde.cjs");

// Stands in for `varde`: session-start prints a note, post-tool-use answers per
// VARDE_TEST_MODE, event just logs.
await writeFile(fakePath, `#!/usr/bin/env node
const fs = require("node:fs");
const args = process.argv.slice(2);
const log = (record) => fs.appendFileSync(process.env.VARDE_TEST_LOG, JSON.stringify(record) + "\\n");
if (args[0] === "event") { log({ kind: "event", args }); process.exit(0); }
if (args[0] === "hook" && args[1] === "session-start") {
  let input = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => { input += chunk; });
  process.stdin.on("end", () => {
    log({ kind: "session-start", args, payload: input ? JSON.parse(input) : {} });
    process.stdout.write("SESSION-CONTEXT");
  });
  return;
}
if (args[0] === "hook" && args[1] === "user-prompt-submit") {
  let input = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => { input += chunk; });
  process.stdin.on("end", () => {
    log({ kind: "user-prompt-submit", args, payload: input ? JSON.parse(input) : {} });
  });
  return;
}
let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  const mode = process.env.VARDE_TEST_MODE || "success";
  log({ kind: "post-tool-use", args, session: process.env.VARDE_TOZ_SESSION, payload: JSON.parse(input) });
  if (mode === "exit") process.exit(9);
  if (mode === "silent") return;
  if (mode === "nudge") {
    process.stdout.write(JSON.stringify({ additionalContext: "SESSION-NOTES-NUDGE" }));
    return;
  }
  process.stdout.write(JSON.stringify({ hookSpecificOutput: { updatedToolOutput: "preview" } }));
});
`);
await chmod(fakePath, 0o755);
process.env.VARDE_TEST_LOG = logPath;

async function load(name) {
  const source = await readFile(new URL(`../${name}.ts`, import.meta.url), "utf8");
  assert.ok(source.includes('const VARDE = "{{VARDE_BIN}}";'), `${name} has the binary placeholder`);
  assert.ok(!/toz[- ]note/i.test(source.replace(/TOZ_SESSION/g, "")), `${name} never mentions the toz note`);
  const file = join(root, `${name}.ts`);
  await writeFile(file, source.replace('"{{VARDE_BIN}}"', JSON.stringify(fakePath)));
  const module = await import(`${pathToFileURL(file).href}?t=${Date.now()}`);
  return module.default ?? module.VardePlugin;
}

const reset = () => writeFile(logPath, "");
async function calls(kind) {
  const text = await readFile(logPath, "utf8").catch(() => "");
  return text.split("\n").filter(Boolean).map((line) => JSON.parse(line)).filter((c) => c.kind === kind);
}
// Background reports land asynchronously; poll instead of sleeping a fixed time.
async function waitForCalls(kind, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const found = await calls(kind);
    if (found.length > 0 || Date.now() >= deadline) return found;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}
const setMode = (mode) => { process.env.VARDE_TEST_MODE = mode; };
const big = "x".repeat(2_048);

test.after(async () => {
  delete process.env.VARDE_TEST_MODE;
  delete process.env.VARDE_TEST_LOG;
  await rm(root, { recursive: true, force: true });
});

// ---- pi ----

async function pi() {
  const register = await load("pi");
  const handlers = new Map();
  register({ on: (name, handler) => handlers.set(name, handler) });
  return handlers;
}

function piContext(overrides = {}) {
  return {
    cwd: root,
    sessionManager: {
      getSessionId: () => "s1",
      getSessionFile: () => "/sessions/s1.jsonl",
      getHeader: () => ({}),
      ...overrides,
    },
    getContextUsage: () => ({ tokens: 500 }),
    model: { id: "pi-model", contextWindow: 1000 },
  };
}

test("pi appends session context once to top-level sessions only", async () => {
  await reset();
  const handlers = await pi();
  const start = handlers.get("before_agent_start");
  const result = start({ systemPrompt: "base" }, piContext());
  assert.equal(result.systemPrompt, "base\n\nSESSION-CONTEXT");
  assert.equal(start({ systemPrompt: "base\n\nSESSION-CONTEXT" }, piContext()), undefined);
  assert.equal(start({ systemPrompt: "base" }, piContext({ getSessionFile: () => undefined })), undefined);
  assert.equal(start({ systemPrompt: "base" }, piContext({ getHeader: () => ({ parentSession: "p" }) })), undefined);
  const [call] = await calls("session-start");
  assert.deepEqual(call.args, ["hook", "session-start", "--harness", "pi"]);
  assert.deepEqual(call.payload, { session_id: "s1" });
  const [inbox] = await calls("user-prompt-submit");
  assert.deepEqual(inbox.args, ["hook", "user-prompt-submit", "--harness", "pi"]);
  assert.deepEqual(inbox.payload, { session_id: "s1" });
  assert.equal((await calls("session-start")).length, 1, "one lookup per plugin instance");
  const resumed = start({ systemPrompt: "base" }, piContext({ getSessionId: () => "s2" }));
  assert.equal(resumed.systemPrompt, "base\n\nSESSION-CONTEXT");
  const starts = await calls("session-start");
  assert.equal(starts.length, 2, "new sessions get their own SessionStart context");
  assert.deepEqual(starts[1].payload, { session_id: "s2" });
});

test("pi captures large results through hook post-tool-use and swaps the preview", async () => {
  await reset();
  setMode("success");
  const toolResult = (await pi()).get("tool_result");
  const event = { toolName: "bash", input: { command: "ls" }, content: [{ type: "text", text: big }], isError: false };
  const result = await toolResult(event, piContext());
  assert.deepEqual(result, { content: [{ type: "text", text: "preview" }] });
  const [call] = await calls("post-tool-use");
  assert.deepEqual(call.args, ["hook", "post-tool-use", "--harness", "pi"]);
  assert.equal(call.payload.harness, "pi");
  assert.equal(call.payload.tool_response, big);
  assert.deepEqual(call.payload.context_usage, {
    usage: { input: 500, output: 0, cacheRead: 0, cacheWrite: 0 },
    model: { id: "pi-model", contextWindow: 1000 },
  });
  assert.equal(call.session, "pi-s1");
});

test("pi forwards a small-result nudge without dropping the original result", async () => {
  await reset();
  setMode("nudge");
  const toolResult = (await pi()).get("tool_result");
  const small = { toolName: "bash", input: {}, content: [{ type: "text", text: "tiny" }], isError: false };
  assert.deepEqual(await toolResult(small, piContext()), {
    content: [{ type: "text", text: "tiny\n\nSESSION-NOTES-NUDGE" }],
  });
  const [call] = await calls("post-tool-use");
  assert.equal("tool_response" in call.payload, false);
  assert.equal(call.payload.session_id, "s1");
  assert.equal(call.payload.context_usage.usage.input, 500);
});

test("pi child sessions send no context usage", async () => {
  await reset();
  setMode("nudge");
  const toolResult = (await pi()).get("tool_result");
  const small = { toolName: "bash", input: {}, content: [{ type: "text", text: "tiny" }], isError: false };
  await toolResult(small, piContext({ getHeader: () => ({ parentSession: "/sessions/parent.jsonl" }) }));
  await toolResult(small, piContext({ getSessionFile: () => undefined }));
  const sent = await calls("post-tool-use");
  assert.equal(sent.length, 2);
  for (const call of sent) {
    assert.equal("context_usage" in call.payload, false);
    assert.equal("session_file" in call.payload, false);
  }
});

test("pi nested large results keep their captured payload without replacing the script value", async () => {
  await reset();
  setMode("success");
  const toolResult = (await pi()).get("tool_result");
  const nested = {
    toolName: "bash", input: {}, parentToolCallId: "parent",
    structuredContent: { output: big }, content: [{ type: "text", text: "short" }], isError: false,
  };
  assert.equal(await toolResult(nested, piContext()), undefined);
  const [call] = await calls("post-tool-use");
  assert.equal(call.payload.tool_response, big);
});

test("pi leaves small and failed results alone and reports failures", async () => {
  await reset();
  const toolResult = (await pi()).get("tool_result");
  setMode("silent");
  const small = { toolName: "bash", input: {}, content: [{ type: "text", text: "tiny" }], isError: false };
  assert.equal(await toolResult(small, piContext()), undefined);
  const [smallCall] = await calls("post-tool-use");
  assert.ok(smallCall, "small results still check for session-notes nudges");
  assert.equal("tool_response" in smallCall.payload, false);
  setMode("exit");
  const large = { toolName: "bash", input: {}, content: [{ type: "text", text: big }], isError: false };
  assert.equal(await toolResult(large, piContext()), undefined);
  const [event] = await waitForCalls("event");
  assert.ok(event, "the failure is reported through varde event");
  assert.deepEqual(event.args.slice(0, 3), ["event", "--harness", "pi"]);
  assert.ok(event.args.includes("exit"));
});

// ---- opencode ----

async function opencode2(messageRows = [{
  type: "assistant", time: { created: Date.now(), completed: Date.now() },
  model: { id: "oc-model" },
  tokens: { input: 400, output: 20, reasoning: 3, cache: { read: 50, write: 2 } },
}]) {
  const plugin = await load("opencode");
  const hooks = new Map();
  const sessions = { parent: {}, child: { parentID: "parent" } };
  await plugin.setup({
    location: { directory: root },
    session: {
      get: async ({ sessionID }) => sessions[sessionID] ?? {},
      messages: async () => ({ data: { data: messageRows } }),
      hook: async (name, handler) => hooks.set(`session.${name}`, handler),
    },
    client: { session: { messages: async () => ({ data: { data: messageRows } }) } },
    shell: { hook: async (name, handler) => hooks.set(`shell.${name}`, handler) },
    tool: { hook: async (name, handler) => hooks.set(`tool.${name}`, handler) },
  });
  return hooks;
}

test("opencode 2.x injects context for main sessions, skips child sessions, sets the capture session", async () => {
  await reset();
  const hooks = await opencode2();
  const main = { sessionID: "parent", system: [] };
  await hooks.get("session.context")(main);
  assert.deepEqual(main.system, [{ type: "text", text: "SESSION-CONTEXT" }]);
  const child = { sessionID: "child", system: [] };
  await hooks.get("session.context")(child);
  assert.deepEqual(child.system, []);
  const otherSession = { sessionID: "other", system: [] };
  await hooks.get("session.context")(otherSession);
  assert.deepEqual(otherSession.system, [{ type: "text", text: "SESSION-CONTEXT" }]);
  const [sessionStart] = await calls("session-start");
  assert.deepEqual(sessionStart.args, ["hook", "session-start", "--harness", "opencode"]);
  assert.deepEqual(sessionStart.payload, { session_id: "parent" });
  const starts = await calls("session-start");
  assert.deepEqual(starts[1].payload, { session_id: "other" });
  const shell = { env: {} };
  await hooks.get("shell.create.before")(shell);
  assert.equal(shell.env.VARDE_TOZ_SESSION, "opencode");
});

test("opencode 2.x captures large completed results", async () => {
  await reset();
  setMode("success");
  const capture = (await opencode2()).get("tool.execute.after");
  const event = {
    status: "completed", sessionID: "s1", tool: "bash", input: { command: "ls" },
    result: { output: big, content: [{ type: "text", text: big }, { type: "file", uri: "u", mime: "m" }] },
  };
  await capture(event);
  assert.equal(event.result.output, "preview");
  assert.deepEqual(event.result.content[0], { type: "text", text: "preview" });
  assert.equal(event.result.content[1].type, "file");
  const [call] = await calls("post-tool-use");
  assert.deepEqual(call.args, ["hook", "post-tool-use", "--harness", "opencode"]);
  assert.equal(call.session, "opencode-s1");
  assert.equal(call.payload.tool_response, big);
  assert.deepEqual(call.payload.context_usage, {
    usage: { input: 400, output: 20, reasoning: 3, cacheRead: 50, cacheWrite: 2 },
    model: { id: "oc-model" },
  });
});

test("opencode 2.x forwards a small-result nudge without replacing tool content", async () => {
  await reset();
  setMode("nudge");
  const capture = (await opencode2()).get("tool.execute.after");
  const event = {
    status: "completed", sessionID: "s1", tool: "bash", input: {},
    result: { output: "tiny", content: [{ type: "text", text: "tiny" }, { type: "file", uri: "u", mime: "m" }] },
  };
  await capture(event);
  assert.equal(event.result.output, "tiny\n\nSESSION-NOTES-NUDGE");
  assert.equal(event.result.content[0].text, "tiny\n\nSESSION-NOTES-NUDGE");
  assert.equal(event.result.content[1].type, "file");
  const [call] = await calls("post-tool-use");
  assert.equal("tool_response" in call.payload, false);
  assert.deepEqual(call.payload.context_usage.model, { id: "oc-model" });
});

test("opencode 2.x skips stale usage while still checking a small result for a nudge", async () => {
  await reset();
  setMode("nudge");
  const stale = [{
    type: "assistant", time: { created: Date.now() - 10 * 60_000 }, model: { id: "oc-model" },
    tokens: { input: 400, output: 20, reasoning: 3, cache: { read: 50, write: 2 } },
  }];
  const capture = (await opencode2(stale)).get("tool.execute.after");
  const event = { status: "completed", sessionID: "s1", tool: "bash", input: {}, result: { output: "tiny" } };
  await capture(event);
  assert.equal(event.result.output, "tiny\n\nSESSION-NOTES-NUDGE");
  const [call] = await calls("post-tool-use");
  assert.equal("context_usage" in call.payload, false);
});

test("opencode 1.x injects context and captures through the hook map", async () => {
  await reset();
  setMode("success");
  const factory = await load("opencode-v1"); // 1.x exports a single named factory
  const client = { session: {
    get: async ({ path }) => ({ data: path.id === "child" ? { parentID: "parent" } : {} }),
    messages: async () => ({ data: [{ info: {
      role: "assistant", time: { created: Date.now(), completed: Date.now() }, modelID: "oc-v1-model",
      tokens: { input: 300, output: 10, reasoning: 2, cache: { read: 30, write: 1 } },
    }, parts: [] }] }),
  } };
  const hooks = await factory({ client, directory: root });
  const main = { system: [] };
  await hooks["experimental.chat.system.transform"]({ sessionID: "parent" }, main);
  assert.deepEqual(main.system, ["SESSION-CONTEXT"]);
  const child = { system: [] };
  await hooks["experimental.chat.system.transform"]({ sessionID: "child" }, child);
  assert.deepEqual(child.system, []);
  const [sessionStart] = await calls("session-start");
  assert.deepEqual(sessionStart.args, ["hook", "session-start", "--harness", "opencode"]);
  assert.deepEqual(sessionStart.payload, { session_id: "parent" });
  const output = { output: big };
  await hooks["tool.execute.after"]({ sessionID: "s1", tool: "bash", args: {} }, output);
  assert.equal(output.output, "preview");
  const [call] = await calls("post-tool-use");
  assert.deepEqual(call.args, ["hook", "post-tool-use", "--harness", "opencode"]);
  assert.deepEqual(call.payload.context_usage, {
    usage: { input: 300, output: 10, reasoning: 2, cacheRead: 30, cacheWrite: 1 },
    model: { id: "oc-v1-model" },
  });
});

test("opencode 1.x forwards a small-result nudge without replacing tool content", async () => {
  await reset();
  setMode("nudge");
  const factory = await load("opencode-v1");
  const client = { session: { messages: async () => ({ data: [{ info: {
    role: "assistant", time: { created: Date.now() }, modelID: "oc-v1-model",
    tokens: { input: 300, output: 10, reasoning: 2, cache: { read: 30, write: 1 } },
  }, parts: [] }] }) } };
  const hooks = await factory({ client, directory: root });
  const output = { output: "tiny" };
  await hooks["tool.execute.after"]({ sessionID: "s1", tool: "bash", args: {} }, output);
  assert.equal(output.output, "tiny\n\nSESSION-NOTES-NUDGE");
  const [call] = await calls("post-tool-use");
  assert.equal("tool_response" in call.payload, false);
  assert.deepEqual(call.payload.context_usage.model, { id: "oc-v1-model" });
});
