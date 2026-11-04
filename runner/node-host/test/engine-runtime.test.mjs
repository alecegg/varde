import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createInterface } from "node:readline";
import { afterEach, test } from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { defineEngine } from "../engine-api.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const hostScript = path.join(root, "host.mjs");
const fakeEngine = path.join(root, "engines/fake/index.mjs");
const hosts = new Set();

async function startHost(enginePath = fakeEngine) {
  const child = spawn("node", [hostScript, enginePath], {
    stdio: ["pipe", "pipe", "pipe"],
  });
  hosts.add(child);
  const stdout = createInterface({ input: child.stdout });
  const stderr = [];
  createInterface({ input: child.stderr }).on("line", (line) => stderr.push(line));
  const frames = [];
  const waiters = [];
  stdout.on("line", (line) => {
    let frame;
    try {
      frame = JSON.parse(line);
    } catch (error) {
      waiters.shift()?.reject(error);
      return;
    }
    const waiter = waiters.shift();
    if (waiter) waiter.resolve(frame);
    else frames.push(frame);
  });

  const nextFrame = (predicate = () => true, timeoutMs = 5000) => {
    const index = frames.findIndex(predicate);
    if (index >= 0) return Promise.resolve(frames.splice(index, 1)[0]);
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        const index = waiters.indexOf(waiter);
        if (index >= 0) waiters.splice(index, 1);
        reject(new Error("timed out waiting for host frame"));
      }, timeoutMs);
      const waiter = {
        resolve(frame) {
          clearTimeout(timeout);
          if (predicate(frame)) resolve(frame);
          else nextFrame(predicate, timeoutMs).then(resolve, reject);
        },
        reject(error) {
          clearTimeout(timeout);
          reject(error);
        },
      };
      waiters.push(waiter);
    });
  };

  const ready = await nextFrame((frame) => frame.type === "ready");
  return { child, stderr, nextFrame, ready };
}

afterEach(async () => {
  await Promise.all(
    [...hosts].map(async (child) => {
      if (child.exitCode !== null || child.signalCode !== null) return;
      child.stdin.end();
      let timeout;
      await Promise.race([
        once(child, "exit"),
        new Promise((resolve) => {
          timeout = setTimeout(resolve, 3000);
          timeout.unref();
        }),
      ]);
      clearTimeout(timeout);
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    }),
  );
  hosts.clear();
});

function request(child, id, method, params = {}) {
  child.stdin.write(`${JSON.stringify({ id, method, params })}\n`);
}

test("engine API validates the documented default export shape", () => {
  const engine = {
    name: "test",
    init: async () => {},
    handle: async () => ({}),
    shutdown: async () => {},
  };
  assert.equal(defineEngine(engine), engine);
  assert.throws(() => defineEngine({ name: "incomplete" }), /needs name, init, handle, shutdown/);
});

test("ready is first; echo replies match request ids", async () => {
  const host = await startHost();
  assert.deepEqual(host.ready, {
    type: "ready",
    protocol: 1,
    engine: "fake",
    node: process.versions.node,
  });

  request(host.child, 10, "echo", { nested: [1, "é"] });
  request(host.child, 11, "echo", { flag: true });
  assert.deepEqual(await host.nextFrame((frame) => frame.id === 10), {
    id: 10,
    result: { nested: [1, "é"] },
  });
  assert.deepEqual(await host.nextFrame((frame) => frame.id === 11), {
    id: 11,
    result: { flag: true },
  });
});

test("event burst has increasing sequence numbers", async () => {
  const host = await startHost();
  request(host.child, 1, "burst", { count: 32, session: "session-a" });
  const events = [];
  for (let index = 0; index < 32; index += 1) {
    events.push(await host.nextFrame((frame) => frame.event === "tick"));
  }
  assert.deepEqual(events.map((event) => event.seq), Array.from({ length: 32 }, (_, i) => i + 1));
  assert.ok(events.every((event) => event.session === "session-a"));
  assert.deepEqual(await host.nextFrame((frame) => frame.id === 1), {
    id: 1,
    result: { emitted: 32 },
  });
});

test("slow call does not block a later echo reply", async () => {
  const host = await startHost();
  request(host.child, 1, "slow", { ms: 120 });
  request(host.child, 2, "echo", { responsive: true });
  assert.deepEqual(await host.nextFrame((frame) => frame.id === 2), {
    id: 2,
    result: { responsive: true },
  });
  assert.deepEqual(await host.nextFrame((frame) => frame.id === 1), {
    id: 1,
    result: { waited_ms: 120 },
  });
});

test("engine stdout is redirected and a hanging call leaves host responsive", async () => {
  const host = await startHost();
  request(host.child, 1, "stdout-noise");
  assert.deepEqual(await host.nextFrame((frame) => frame.id === 1), {
    id: 1,
    result: { clean: true },
  });
  request(host.child, 2, "hang");
  request(host.child, 3, "echo", { responsive: true });
  assert.deepEqual(await host.nextFrame((frame) => frame.id === 3), {
    id: 3,
    result: { responsive: true },
  });
  assert.ok(host.stderr.some((line) => line.includes("fake engine stdout must be redirected")));
});

test("child tracking methods emit host-owned notifications", async () => {
  const host = await startHost();
  request(host.child, 1, "track-child");
  const tracked = await host.nextFrame((frame) => frame.event === "child_tracked");
  try {
    const created = await host.nextFrame((frame) => frame.id === 1);
    assert.equal(tracked.session, null);
    assert.deepEqual(tracked.data, created.result);

    request(host.child, 2, "untrack-child", { pgid: created.result.pgid });
    const untracked = await host.nextFrame((frame) => frame.event === "child_untracked");
    assert.equal(untracked.session, null);
    assert.deepEqual(untracked.data, created.result);
    assert.deepEqual(await host.nextFrame((frame) => frame.id === 2), { id: 2, result: {} });
  } finally {
    try {
      process.kill(-tracked.data.pgid, "SIGKILL");
    } catch {
      // The child already exited.
    }
  }
});

test("crash-on-request terminates the host process", async () => {
  const host = await startHost();
  request(host.child, 1, "crash-on-request");
  const [code, signal] = await once(host.child, "exit");
  assert.equal(code, 17);
  assert.equal(signal, null);
});
