import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import * as approvals from "../approvals.mjs";
import { openApprovalStore } from "../approval-store.mjs";

const WORKER = fileURLToPath(new URL("./approval-worker.mjs", import.meta.url));

function nextLine(child, predicate, timeoutMs = 3000) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => reject(new Error("approval worker timed out")), timeoutMs);
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line) continue;
        const value = JSON.parse(line);
        if (!predicate(value)) continue;
        clearTimeout(timer);
        resolve(value);
      }
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code !== 0) reject(new Error(`approval worker exited: ${code}`));
    });
  });
}

test("gate persists pending approval across SIGKILL and delivers an approved effect once", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-durable-approval-"));
  const effectsPath = join(directory, "effects.log");
  const first = spawn(process.execPath, [WORKER, directory, effectsPath], { stdio: ["ignore", "pipe", "pipe"] });
  let restarted;
  try {
    const initialRequest = await nextLine(first, (line) => line.event === "permission_request");
    assert.equal(initialRequest.data.approval_id, "conversation-1:call-1");
    first.kill("SIGKILL");
    await new Promise((resolve) => first.once("exit", resolve));

    restarted = spawn(process.execPath, [WORKER, directory, effectsPath], { stdio: ["ignore", "pipe", "pipe"] });
    const resumedRequest = await nextLine(restarted, (line) => line.event === "permission_request");
    assert.equal(resumedRequest.data.approval_id, initialRequest.data.approval_id);
    const store = await openApprovalStore(join(directory, "approvals.sqlite"));
    try {
      assert.equal(store.get("conversation-1:call-1").status, "pending");
      assert.equal(store.respond("conversation-1:call-1", "approved", Date.now()), true);
      assert.equal(store.respond("conversation-1:call-1", "denied", Date.now()), false);
    } finally {
      store.close();
    }
    const result = await nextLine(restarted, (line) => line.result);
    assert.deepEqual(result.result, { status: "executed", value: "effect result" });
    await new Promise((resolve, reject) => restarted.once("exit", (code) => code === 0 ? resolve() : reject(new Error(`restart exited: ${code}`))));
    assert.equal((await readFile(effectsPath, "utf8")).trim().split("\n").length, 1);
  } finally {
    for (const child of [first, restarted]) {
      if (child && child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    }
    await rm(directory, { recursive: true, force: true });
  }
});

test("gate returns denied and expired outcomes and replays a completed delivery", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-durable-approval-module-"));
  const previous = process.env.VARDE_PI_DURABLE_STORAGE_DIR;
  process.env.VARDE_PI_DURABLE_STORAGE_DIR = directory;
  const requests = [];
  await approvals.init({ ctx: { emit: (_event, _session, data) => requests.push(data), log() {} } });
  try {
    const denied = approvals.gateAndEffect({ key: "c:denied", tool: "bash", summary: "deny", input: {} }, async () => "unused");
    await waitUntil(() => requests.some((request) => request.approval_id === "c:denied"));
    await approvals.methods["permission.respond"]({ approval_id: "c:denied", decision: "denied" });
    assert.deepEqual(await denied, { status: "denied" });

    const expired = approvals.gateAndEffect({ key: "c:expired", tool: "bash", summary: "expire", input: {} }, async () => "unused");
    await waitUntil(() => requests.some((request) => request.approval_id === "c:expired"));
    await approvals.methods["permission.respond"]({ approval_id: "c:expired", decision: "expired" });
    assert.deepEqual(await expired, { status: "expired" });

    let effects = 0;
    const request = { key: "c:once", tool: "bash", summary: "once", input: {} };
    const first = approvals.gateAndEffect(request, async () => { effects += 1; return "saved"; });
    await waitUntil(() => requests.some((item) => item.approval_id === "c:once"));
    await approvals.methods["permission.respond"]({ approval_id: "c:once", decision: "approved" });
    assert.deepEqual(await first, { status: "executed", value: "saved" });
    assert.deepEqual(await approvals.gateAndEffect(request, async () => { effects += 1; return "duplicate"; }), {
      status: "executed",
      value: "saved",
    });
    assert.equal(effects, 1);
    await assert.rejects(
      approvals.methods["permission.respond"]({ approval_id: "c:once", decision: "denied" }),
      { code: "stale_approval" },
    );
  } finally {
    await approvals.close();
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
