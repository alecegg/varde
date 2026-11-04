import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import { acquireStorageFence, prepareStoragePath } from "../fence.mjs";

const fenceModule = fileURLToPath(new URL("../fence.mjs", import.meta.url));

test("fence refuses a second writer and is reclaimed after SIGKILL", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-durable-fence-"));
  const storagePath = join(directory, "durable.sqlite");
  await prepareStoragePath(storagePath);
  const fenceUrl = JSON.stringify(pathToFileURL(fenceModule).href);
  const childCode = `import { acquireStorageFence } from ${fenceUrl}; acquireStorageFence(process.argv[1]); console.log("locked"); setInterval(() => {}, 1000);`;
  const holder = spawn(process.execPath, ["--input-type=module", "-e", childCode, storagePath], {
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  holder.stdout.setEncoding("utf8");
  holder.stdout.on("data", (chunk) => (output += chunk));
  try {
    const deadline = Date.now() + 5000;
    while (!output.includes("locked") && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    assert.match(output, /locked/);

    const start = Date.now();
    const refused = spawnSync(process.execPath, ["--input-type=module", "-e", childCode, storagePath], {
      encoding: "utf8",
      timeout: 1000,
    });
    assert.notEqual(refused.status, 0);
    assert.match(refused.stderr, /busy|locked/i);
    assert.ok(Date.now() - start < 1000);

    holder.kill("SIGKILL");
    await new Promise((resolve) => holder.once("exit", resolve));
    const reclaimed = spawnSync(process.execPath, ["--input-type=module", "-e", `import { acquireStorageFence } from ${fenceUrl}; const release = acquireStorageFence(process.argv[1]); release(); console.log("reclaimed");`, storagePath], {
      encoding: "utf8",
      timeout: 1000,
    });
    assert.equal(reclaimed.status, 0, reclaimed.stderr);
    assert.match(reclaimed.stdout, /reclaimed/);
  } finally {
    if (holder.exitCode === null) holder.kill("SIGKILL");
    await rm(directory, { recursive: true, force: true });
  }
});

test("release is idempotent and allows a subsequent writer", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-durable-fence-"));
  try {
    const storagePath = join(directory, "durable.sqlite");
    const release = acquireStorageFence(storagePath);
    release();
    release();
    const next = acquireStorageFence(storagePath);
    next();
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
