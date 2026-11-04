import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { it } from "node:test";

const here = fileURLToPath(new URL(".", import.meta.url));
const hostScript = fileURLToPath(new URL("../../../host.mjs", import.meta.url));
const engine = fileURLToPath(new URL("../index.mjs", import.meta.url));

it("runs a turn through the real node host with the fake SDK", async () => {
  const child = spawn(process.execPath, [hostScript, engine], {
    env: { ...process.env, VARDE_CLAUDE_SDK_MODULE: `${here}fake-sdk.mjs` },
    stdio: ["pipe", "pipe", "ignore"],
  });
  const frames = [];
  const waiters = [];
  createInterface({ input: child.stdout }).on("line", (line) => {
    frames.push(JSON.parse(line));
    for (const waiter of waiters.splice(0)) waiter();
  });
  const until = async (predicate) => {
    const deadline = Date.now() + 5000;
    while (!frames.some(predicate)) {
      assert.ok(Date.now() < deadline, `timeout; frames: ${JSON.stringify(frames)}`);
      await new Promise((resolve) => {
        waiters.push(resolve);
        setTimeout(resolve, 50);
      });
    }
  };
  try {
    await until((frame) => frame.type === "ready");
    assert.equal(frames[0].engine, "claude-sdk");
    const request = { id: 1, method: "session.start", params: { cwd: "/tmp", model: "m", mode: "auto", prompt: "hi" } };
    child.stdin.write(`${JSON.stringify(request)}\n`);
    await until((frame) => frame.event === "usage");
    const reply = frames.find((frame) => frame.id === 1);
    assert.equal(reply.result.resumed, false);
    const seqs = frames.filter((frame) => frame.event).map((frame) => frame.seq);
    assert.deepEqual(seqs, [...seqs].sort((a, b) => a - b));
    const engineEvents = frames.filter((frame) => frame.event && !frame.event.startsWith("child_"));
    assert.ok(engineEvents.every((frame) => frame.session === reply.result.session));
    assert.ok(frames.some((frame) => frame.event === "child_tracked"));
  } finally {
    child.stdin.end();
    await new Promise((resolve) => child.once("exit", resolve));
  }
});
