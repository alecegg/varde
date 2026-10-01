import assert from "node:assert/strict";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const testRoot = await mkdtemp(join(tmpdir(), "varde-toz-pi-"));
const logPath = join(testRoot, "calls.jsonl");
const fakeTozPath = join(testRoot, "fake-toz.cjs");
const originalAdapterPath = new URL("../extensions/varde-toz.ts", import.meta.url);

const fakeToz = `#!/usr/bin/env node
const fs = require("node:fs");
const args = process.argv.slice(2);
const mode = process.env.VARDE_TOZ_TEST_MODE || "success";
const log = (record) => fs.appendFileSync(process.env.VARDE_TOZ_TEST_LOG, JSON.stringify(record) + "\\n");

if (args[0] === "event") {
  log({ kind: "event", args });
  process.exit(0);
}

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  const payload = JSON.parse(input);
  log({ kind: "capture-start", payload, mode });
  if (mode === "exit") { process.exit(9); }
  if (mode === "invalid-json") { process.stdout.write("not json"); return; }
  if (mode === "timeout") { setInterval(() => {}, 1_000); return; }
  if (mode === "large-stdout") { process.stdout.write("x".repeat(70_000)); return; }
  if (mode === "large-stderr") { process.stderr.write("x".repeat(70_000)); return; }
  if (mode === "silent" || payload.tool_input?.command?.startsWith("varde-toz ") || payload.tool_input?.command?.startsWith("toz ")) return;
  if (mode === "delayed") {
    setTimeout(() => {
      log({ kind: "capture-end", payload });
      process.stdout.write(JSON.stringify({ hookSpecificOutput: { updatedToolOutput: "preview" } }));
    }, 120);
    return;
  }
  process.stdout.write(JSON.stringify({ hookSpecificOutput: { updatedToolOutput: "preview" } }));
});
`;

await writeFile(fakeTozPath, fakeToz);
await chmod(fakeTozPath, 0o755);
const originalAdapter = await readFile(originalAdapterPath, "utf8");
process.env.VARDE_TOZ_TEST_LOG = logPath;

async function loadAdapter(timeoutMs) {
  const adapterPath = join(testRoot, `varde-toz-${timeoutMs ?? "default"}.ts`);
  let source = originalAdapter.replace('const TOZ = "{{TOZ_BIN}}";', `const TOZ = ${JSON.stringify(fakeTozPath)};`);
  if (timeoutMs) {
    source = source
      .replace("const CAPTURE_TIMEOUT_MS = 20_000;", `const CAPTURE_TIMEOUT_MS = ${timeoutMs};`)
      .replace("timeout: 20_000,", `timeout: ${timeoutMs},`);
  }
  await writeFile(adapterPath, source);
  const { default: registerToz } = await import(`${pathToFileURL(adapterPath).href}?test=${Date.now()}-${timeoutMs ?? "default"}`);
  const handlers = new Map();
  registerToz({ on: (name, handler) => handlers.set(name, handler) });
  const handler = handlers.get("tool_result");
  assert.equal(typeof handler, "function", "adapter registers its Pi tool_result handler");
  return handler;
}

const toolResult = await loadAdapter();
const shortTimeoutToolResult = await loadAdapter(80);

async function resetCalls() {
  await writeFile(logPath, "");
}

async function calls() {
  const text = await readFile(logPath, "utf8").catch(() => "");
  return text.split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

async function waitFor(predicate, message) {
  const deadline = Date.now() + 2_000;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.fail(message);
}

function context() {
  return {
    cwd: testRoot,
    sessionManager: { getSessionId: () => "session-1" },
  };
}

function frozenEvent(overrides = {}) {
  const event = {
    toolName: "bash",
    input: Object.freeze({ command: "printf output" }),
    content: Object.freeze([Object.freeze({ type: "text", text: "x".repeat(2_048) })]),
    isError: false,
    ...overrides,
  };
  return Object.freeze(event);
}

function setMode(mode) { process.env.VARDE_TOZ_TEST_MODE = mode; }

test.after(async () => {
  delete process.env.VARDE_TOZ_TEST_MODE;
  delete process.env.VARDE_TOZ_TEST_LOG;
  await rm(testRoot, { recursive: true, force: true });
});

test("successful nested text is captured without changing any event identity", async () => {
  await resetCalls();
  await setMode("success");
  const content = Object.freeze([
    Object.freeze({ type: "text", text: "nested output ".repeat(200) }),
    Object.freeze({ type: "image", data: "same image" }),
  ]);
  const input = Object.freeze({ command: "long command" });
  const event = Object.freeze({ toolName: "bash", parentToolCallId: "codemode-1", input, content, structuredContent: undefined, isError: false });

  const result = await toolResult(event, context());

  assert.equal(result, undefined);
  const call = (await calls()).find((entry) => entry.kind === "capture-start");
  assert.equal(call.payload.tool_response, "nested output ".repeat(200));
  assert.strictEqual(event.content, content);
  assert.strictEqual(event.input, input);
  assert.strictEqual(event.structuredContent, undefined);
  assert.strictEqual(content[1].type, "image");
});

test("nested bash and powershell prefer a string structured output", async (t) => {
  for (const toolName of ["bash", "powershell"]) {
    await t.test(toolName, async () => {
      await resetCalls();
      await setMode("success");
      const output = `${toolName} complete output `.repeat(150);
      const structuredContent = Object.freeze({ output });
      const event = frozenEvent({
        toolName,
        parentToolCallId: "codemode-1",
        content: Object.freeze([Object.freeze({ type: "text", text: "short preview" })]),
        structuredContent,
      });

      assert.equal(await toolResult(event, context()), undefined);
      const call = (await calls()).find((entry) => entry.kind === "capture-start");
      assert.equal(call.payload.tool_response, output);
      assert.strictEqual(event.structuredContent, structuredContent);
    });
  }
});

test("nested shell results serialize structured content without a string output", async (t) => {
  for (const [toolName, structuredContent] of [
    ["bash", Object.freeze({ output: 42, details: "structured detail ".repeat(120) })],
    ["powershell", Object.freeze({ exitCode: 0, details: "structured detail ".repeat(120) })],
  ]) {
    await t.test(`${toolName} ${"output" in structuredContent ? "non-string output" : "missing output"}`, async () => {
      await resetCalls();
      setMode("success");
      const event = frozenEvent({
        toolName,
        parentToolCallId: "codemode-1",
        structuredContent,
        content: Object.freeze([Object.freeze({ type: "text", text: "small display" })]),
      });

      assert.equal(await toolResult(event, context()), undefined);
      const call = (await calls()).find((entry) => entry.kind === "capture-start");
      assert.equal(call.payload.tool_response, JSON.stringify(structuredContent));
    });
  }
});

test("other nested structured results are serialized as JSON", async () => {
  await resetCalls();
  await setMode("success");
  const structuredContent = Object.freeze({ result: "complete structured value ".repeat(100), count: 7 });
  const event = frozenEvent({
    toolName: "lookup",
    parentToolCallId: "codemode-1",
    structuredContent,
    content: Object.freeze([Object.freeze({ type: "text", text: "small display" })]),
  });

  assert.equal(await toolResult(event, context()), undefined);
  const call = (await calls()).find((entry) => entry.kind === "capture-start");
  assert.equal(call.payload.tool_response, JSON.stringify(structuredContent));
  assert.strictEqual(event.structuredContent, structuredContent);
});

test("direct and final codemode results replace only text and keep nontext blocks", async (t) => {
  for (const eventFields of [{ toolName: "bash" }, { toolName: "codemode" }]) {
    await t.test(eventFields.toolName, async () => {
      await resetCalls();
      await setMode("success");
      const image = Object.freeze({ type: "image", data: "keep me" });
      const content = Object.freeze([Object.freeze({ type: "text", text: "large final output ".repeat(150) }), image]);
      const structuredContent = Object.freeze({ retainOnEvent: "Pi treats replacement as redaction" });
      const event = frozenEvent({ ...eventFields, content, structuredContent });

      const result = await toolResult(event, context());

      assert.deepEqual(Object.keys(result), ["content"]);
      assert.equal(result.content[0].type, "text");
      assert.equal(result.content[0].text, "preview");
      assert.strictEqual(result.content[1], image);
      assert.strictEqual(event.content, content);
      assert.strictEqual(event.structuredContent, structuredContent);
    });
  }
});

test("threshold uses UTF-8 bytes for direct results", async () => {
  await resetCalls();
  await setMode("success");
  const below = frozenEvent({ content: Object.freeze([Object.freeze({ type: "text", text: "é".repeat(1_023) })]) });
  assert.equal(await toolResult(below, context()), undefined);
  assert.equal((await calls()).filter((call) => call.kind === "capture-start").length, 0);

  const exact = frozenEvent({ content: Object.freeze([Object.freeze({ type: "text", text: "é".repeat(1_024) })]) });
  const result = await toolResult(exact, context());
  assert.equal(result.content[0].text, "preview");
  assert.equal((await calls()).filter((call) => call.kind === "capture-start").length, 1);
});

test("small and error results do not spawn capture processes", async () => {
  await resetCalls();
  await setMode("success");
  const small = frozenEvent({ content: Object.freeze([Object.freeze({ type: "text", text: "small" })]) });
  const smallNested = frozenEvent({ parentToolCallId: "codemode-1", content: Object.freeze([Object.freeze({ type: "text", text: "small" })]) });
  const failed = frozenEvent({ isError: true });

  assert.equal(await toolResult(small, context()), undefined);
  assert.equal(await toolResult(smallNested, context()), undefined);
  assert.equal(await toolResult(failed, context()), undefined);
  assert.equal((await calls()).length, 0);
});

test("parallel nested captures return immediately and run concurrently", async () => {
  await resetCalls();
  await setMode("delayed");
  const first = frozenEvent({ parentToolCallId: "codemode-1" });
  const second = frozenEvent({ parentToolCallId: "codemode-1", input: Object.freeze({ command: "second" }) });

  const firstResult = toolResult(first, context());
  const secondResult = toolResult(second, context());

  assert.ok(firstResult instanceof Promise);
  assert.ok(secondResult instanceof Promise);
  const [firstValue, secondValue] = await Promise.all([firstResult, secondResult]);
  assert.equal(firstValue, undefined);
  assert.equal(secondValue, undefined);
  const entries = await calls();
  const lastStart = Math.max(...entries.map((call, index) => call.kind === "capture-start" ? index : -1));
  const firstEnd = entries.findIndex((call) => call.kind === "capture-end");
  assert.ok(lastStart < firstEnd, "both child processes start before either delayed capture finishes");
});

test("a Toz command uses Toz's existing recursion skip and receives no replacement", async () => {
  await resetCalls();
  await setMode("success");
  const event = frozenEvent({ input: Object.freeze({ command: "varde-toz run --script -" }) });

  const result = await toolResult(event, context());

  assert.equal(result, undefined);
  const capture = (await calls()).find((call) => call.kind === "capture-start");
  assert.equal(capture.payload.tool_input.command, "varde-toz run --script -");
});

test("cyclic payload serialization fails open without changing the nested event", async () => {
  await resetCalls();
  const input = {};
  input.self = input;
  Object.freeze(input);
  const event = frozenEvent({ parentToolCallId: "codemode-1", input });

  assert.equal(await toolResult(event, context()), undefined);
  assert.strictEqual(event.input, input);
  assert.equal((await calls()).filter((call) => call.kind === "capture-start").length, 0);
  await waitFor(async () => (await calls()).some((call) => call.kind === "event"), "serialization failure should be reported");
});

test("cyclic nested structured content fails open without spawning capture", async () => {
  await resetCalls();
  const structuredContent = {};
  structuredContent.self = structuredContent;
  Object.freeze(structuredContent);
  const event = frozenEvent({
    toolName: "lookup",
    parentToolCallId: "codemode-1",
    structuredContent,
    content: Object.freeze([Object.freeze({ type: "text", text: "small display" })]),
  });

  assert.equal(await toolResult(event, context()), undefined);
  assert.strictEqual(event.structuredContent, structuredContent);
  assert.equal((await calls()).filter((call) => call.kind === "capture-start").length, 0);
  await waitFor(async () => (await calls()).some((call) => call.kind === "event"), "structured serialization failure should be reported");
});

test("spawn, nonzero exit, timeout, invalid JSON, and oversized output all fail open", async (t) => {
  await t.test("missing executable", async () => {
    await resetCalls();
    await rm(fakeTozPath);
    const event = frozenEvent();
    assert.equal(await toolResult(event, context()), undefined);
    await writeFile(fakeTozPath, fakeToz);
    await chmod(fakeTozPath, 0o755);
  });

  for (const mode of ["exit", "timeout", "invalid-json", "large-stdout", "large-stderr"]) {
    await t.test(mode, async () => {
      await resetCalls();
      setMode(mode);
      const event = frozenEvent();
      const originalContent = event.content;
      const handler = mode === "timeout" ? shortTimeoutToolResult : toolResult;
      const result = await handler(event, context());
      assert.equal(result, undefined);
      assert.strictEqual(event.content, originalContent);
      await waitFor(async () => (await calls()).some((call) => call.kind === "event"), `${mode} should record its failure`);
      const failure = (await calls()).find((call) => call.kind === "event");
      const expectedReason = mode === "timeout" ? "timeout" : mode.startsWith("large-") ? "output-limit" : mode === "invalid-json" ? "invalid-response" : "exit";
      assert.ok(failure.args.includes(expectedReason), `${mode} should report ${expectedReason}: ${failure.args.join(" ")}`);
    });
  }
  setMode("success");
});

test("harness extension and embedded Pi asset remain byte-identical", async () => {
  const extension = await readFile(originalAdapterPath);
  const embedded = await readFile(new URL("../../../crates/toz/assets/pi/toz.ts", import.meta.url));
  assert.equal(extension.toString("utf8"), embedded.toString("utf8"));
});
