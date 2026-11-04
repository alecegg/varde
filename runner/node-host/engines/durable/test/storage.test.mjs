import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { openDurableStorage } from "../storage.mjs";

const HOST = fileURLToPath(new URL("../../../host.mjs", import.meta.url));
const ENGINE = fileURLToPath(new URL("../index.mjs", import.meta.url));

function startHost(storageDir) {
  return spawn(process.execPath, [HOST, ENGINE], {
    env: { ...process.env, VARDE_PI_DURABLE_STORAGE_DIR: storageDir },
    stdio: ["pipe", "pipe", "pipe"],
  });
}

async function firstLine(child, timeout = 3000) {
  return await new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error("host did not become ready")), timeout);
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      output += chunk;
      const newline = output.indexOf("\n");
      if (newline === -1) return;
      clearTimeout(timer);
      resolve(JSON.parse(output.slice(0, newline)));
    });
    child.once("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`host exited before ready: ${code}`));
    });
  });
}

async function waitForExit(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  await new Promise((resolve) => child.once("exit", resolve));
}

test("opens Durable storage behind its fence and releases it on close", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-durable-storage-"));
  const storagePath = join(directory, "durable.sqlite");
  const opened = await openDurableStorage(storagePath);
  try {
    assert.ok(opened.storage);
    await assert.rejects(
      import("../fence.mjs").then(({ acquireStorageFence }) =>
        acquireStorageFence(storagePath),
      ),
      /busy|locked/i,
    );
  } finally {
    await opened.close();
    await rm(directory, { recursive: true, force: true });
  }
  const reopened = await openDurableStorage(storagePath);
  await reopened.close();
});

test("engine module initializes required storage and rejects unknown methods", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-durable-engine-"));
  const previous = process.env.VARDE_PI_DURABLE_STORAGE_DIR;
  process.env.VARDE_PI_DURABLE_STORAGE_DIR = directory;
  const engine = (await import("../index.mjs")).default;
  try {
    await engine.init({
      emit() {},
      log() {},
      trackChild() {},
      untrackChild() {},
    });
    await assert.rejects(engine.handle("missing", {}), { code: "unknown_method" });
  } finally {
    await engine.shutdown();
    if (previous === undefined) delete process.env.VARDE_PI_DURABLE_STORAGE_DIR;
    else process.env.VARDE_PI_DURABLE_STORAGE_DIR = previous;
    await rm(directory, { recursive: true, force: true });
  }
});

test("a new Node host reclaims fenced storage after the owner is killed", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-durable-host-fence-"));
  let owner;
  let contender;
  let reclaimed;
  try {
    owner = startHost(directory);
    assert.deepEqual(await firstLine(owner), {
      type: "ready",
      protocol: 1,
      engine: "pi-durable",
      node: process.versions.node,
    });

    const start = Date.now();
    contender = startHost(directory);
    let stderr = "";
    let stdout = "";
    contender.stderr.setEncoding("utf8");
    contender.stderr.on("data", (chunk) => (stderr += chunk));
    contender.stdout.setEncoding("utf8");
    contender.stdout.on("data", (chunk) => (stdout += chunk));
    await Promise.race([
      waitForExit(contender),
      new Promise((resolve) => setTimeout(resolve, 900)),
    ]);
    if (contender.exitCode === null && contender.signalCode === null) {
      contender.kill("SIGKILL");
      await waitForExit(contender);
    }
    assert.doesNotMatch(stdout, /"type":"ready"/);
    assert.match(stderr, /busy|locked/i);
    assert.ok(Date.now() - start < 1000);

    owner.kill("SIGKILL");
    await waitForExit(owner);
    reclaimed = startHost(directory);
    assert.deepEqual(await firstLine(reclaimed), {
      type: "ready",
      protocol: 1,
      engine: "pi-durable",
      node: process.versions.node,
    });
  } finally {
    for (const child of [owner, contender, reclaimed]) {
      if (child && child.exitCode === null && child.signalCode === null) {
        child.kill("SIGKILL");
        await waitForExit(child);
      }
    }
    await rm(directory, { recursive: true, force: true });
  }
});
