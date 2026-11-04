import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { openEventLog } from "../event-log.mjs";
import { entryEvents } from "../compaction.mjs";
import * as bridge from "../events.mjs";

const WORKER = fileURLToPath(new URL("./event-log-worker.mjs", import.meta.url));

function waitForLine(child, expected) {
  return new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`worker did not print ${expected}`)), 3000);
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      output += chunk;
      if (!output.includes(`${expected}\n`)) return;
      clearTimeout(timer);
      resolve();
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code !== 0) reject(new Error(`worker exited: ${code}`));
    });
  });
}

test("event log deduplicates scans and resumes exclusively after any persisted cursor", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-durable-events-"));
  const log = await openEventLog(join(directory, "events.sqlite"));
  const events = Array.from({ length: 600 }, (_, index) => ({
    entryId: `entry-${Math.floor(index / 2)}`,
    type: `event-${index}`,
  }));
  try {
    assert.equal(log.append("conversation-1", events), 600);
    assert.equal(log.append("conversation-1", events), 600);
    for (const cursor of [0, 1, 177, 500, 600]) {
      const replay = log.readFrom("conversation-1", cursor);
      assert.equal(replay[0]?.cursor ?? null, cursor === 600 ? null : cursor + 1);
      assert.deepEqual(replay.map((row) => row.cursor),
        Array.from({ length: 600 - cursor }, (_, index) => cursor + index + 1));
    }
    assert.equal(log.readFrom("conversation-1", 601).length, 0);
  } finally {
    log.close();
    await rm(directory, { recursive: true, force: true });
  }
});

test("SIGKILL during a scan leaves replay with no gaps or duplicate event identities", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-durable-kill-events-"));
  const path = join(directory, "events.sqlite");
  const interrupted = spawn(process.execPath, [WORKER, directory, "partial"], { stdio: ["ignore", "pipe", "pipe"] });
  let restarted;
  try {
    await waitForLine(interrupted, "ready");
    interrupted.kill("SIGKILL");
    await new Promise((resolve) => interrupted.once("exit", resolve));
    restarted = spawn(process.execPath, [WORKER, directory, "restart"], { stdio: ["ignore", "pipe", "pipe"] });
    await waitForLine(restarted, "finished");
    await new Promise((resolve, reject) => {
      restarted.once("exit", (code) => code === 0 ? resolve() : reject(new Error(`restart exited: ${code}`)));
    });
    const log = await openEventLog(path);
    try {
      const replay = log.readFrom("conversation-1", 0);
      assert.equal(replay.length, 600);
      assert.deepEqual(replay.map((row) => row.cursor), Array.from({ length: 600 }, (_, index) => index + 1));
      assert.equal(new Set(replay.map((row) => `${row.event.entryId}:${row.event.type}`)).size, 600);
      for (const cursor of [0, 1, 251, 599]) assert.equal(log.readFrom("conversation-1", cursor)[0].cursor, cursor + 1);
    } finally {
      log.close();
    }
  } finally {
    for (const child of [interrupted, restarted]) {
      if (child && child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    }
    await rm(directory, { recursive: true, force: true });
  }
});

test("entry mapping includes model usage priced from the pi-ai catalog and compaction activity", () => {
  const modelCatalog = {
    getModel(provider, id) {
      assert.equal(provider, "faux");
      assert.equal(id, "test-model");
      return { cost: { input: 1, output: 2, cacheRead: 0.5, cacheWrite: 1 } };
    },
  };
  const entry = {
    id: 12,
    kind: "pi.compaction",
    data: { reason: "manual" },
    model: [{ role: "assistant", provider: "faux", model: "test-model", content: [], usage: {
      input: 1_000_000, output: 1_000_000, cacheRead: 0, cacheWrite: 0, totalTokens: 2_000_000,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    } }],
  };
  const events = entryEvents(entry, modelCatalog);
  assert.equal(events.find((event) => event.type === "usage").costUsd, 3);
  assert.equal(events.find((event) => event.type === "activity").activity, "compaction");
});

test("bridge polls committed entries and resumes after the persisted cursor", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-durable-bridge-"));
  const previous = process.env.VARDE_PI_DURABLE_STORAGE_DIR;
  process.env.VARDE_PI_DURABLE_STORAGE_DIR = directory;
  const emitted = [];
  let entries = [{ id: 1, kind: "pi.user", model: [{ role: "user", content: "one" }] }];
  await bridge.init({ ctx: { emit: (event, session, data) => emitted.push({ event, session, data }), log() {} } });
  bridge.registerConversation("c-1", {
    async entries(query, limit, cursor) {
      const matching = entries.filter((entry) => entry.id >= query.minEntryId);
      const offset = cursor?.offset ?? 0;
      const items = matching.slice(offset, offset + limit);
      return { items, ...(offset + items.length < matching.length ? { next: { offset: offset + items.length } } : {}) };
    },
  });
  try {
    await bridge.methods["events.subscribe"]({ session: "c-1", after_cursor: 1 });
    await waitUntil(() => emitted.length === 1);
    assert.equal(emitted[0].data.cursor, 2);
    entries = [...entries, { id: 2, kind: "pi.compaction", data: { reason: "manual" }, model: [] }];
    await waitUntil(() => emitted.length === 3);
    assert.deepEqual(emitted.map(({ data }) => data.cursor), [2, 3, 4]);
    assert.equal(emitted[2].data.activity, "compaction");
    const usage = bridge.methods["usage.get"]({ session: "c-1" });
    assert.deepEqual(usage, { session: "c-1", models: [] });
  } finally {
    await bridge.close();
    if (previous === undefined) delete process.env.VARDE_PI_DURABLE_STORAGE_DIR;
    else process.env.VARDE_PI_DURABLE_STORAGE_DIR = previous;
    await rm(directory, { recursive: true, force: true });
  }
});

async function waitUntil(predicate) {
  const deadline = Date.now() + 3000;
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error("condition was not reached before timeout");
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}
