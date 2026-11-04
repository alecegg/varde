import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import { createProcesses } from "../interrupt.mjs";
import { fakeSdk, harness, pidAlive, waitFor } from "./helpers.mjs";

const env = (extra = {}) => ({ PATH: process.env.PATH, ...extra });
const params = (extra = {}) => ({ cwd: "/", model: "m", mode: "workspace-write", prompt: "hang", env: env(), ...extra });

async function started(h, extra) {
  const { session } = await h.call("session.start", params(extra));
  const call = fakeSdk.calls.at(-1);
  await waitFor(() => call.grandchild !== null);
  return { session, call };
}

function trackingHarness(options) {
  const h = harness({ processes: createProcesses(options) });
  const tracked = [];
  const untracked = [];
  h.ctx.trackChild = (pid, pgid) => tracked.push({ pid, pgid });
  h.ctx.untrackChild = (pgid) => untracked.push(pgid);
  return { h, tracked, untracked };
}

describe("per-session process groups", () => {
  beforeEach(() => fakeSdk.reset());

  it("tracks the child group and kills it, tool subprocesses included, on stop", async () => {
    const { h, tracked, untracked } = trackingHarness();
    const { session, call } = await started(h);
    assert.equal(tracked.length, 1);
    const pid = tracked[0].pid;
    assert.equal(tracked[0].pgid, pid);
    assert.ok(pidAlive(pid) && pidAlive(call.grandchild));
    await h.call("session.stop", { session });
    await waitFor(() => !pidAlive(pid) && !pidAlive(call.grandchild));
    assert.deepEqual(untracked, [pid]);
    assert.equal(h.events.at(-1).data.reason, "stopped");
  });

  it("escalates to SIGKILL when the child ignores SIGTERM", async () => {
    const { h, tracked } = trackingHarness({ stopGraceMs: 200 });
    const { session, call } = await started(h, { env: env({ FAKE_STUBBORN: "1" }) });
    const pid = tracked[0].pid;
    await h.call("session.stop", { session });
    await waitFor(() => !pidAlive(pid) && !pidAlive(call.grandchild));
  });

  it("stops one session without touching another", async () => {
    const { h, tracked } = trackingHarness();
    const first = await started(h);
    const second = await started(h);
    const [firstPid, secondPid] = tracked.map((item) => item.pid);
    await h.call("session.stop", { session: first.session });
    await waitFor(() => !pidAlive(firstPid));
    assert.ok(pidAlive(secondPid) && pidAlive(second.call.grandchild));
    assert.equal((await h.call("session.alive", { session: second.session })).alive, true);
    await h.call("session.stop", { session: second.session });
    await waitFor(() => !pidAlive(secondPid));
  });

  it("interrupt delivers the result, then kills the group and ends as interrupted", async () => {
    const { h, tracked } = trackingHarness({ interruptGraceMs: 2000 });
    const { session, call } = await started(h);
    const pid = tracked[0].pid;
    await h.call("session.interrupt", { session });
    await waitFor(() => !pidAlive(pid) && !pidAlive(call.grandchild));
    await h.until((events) => events.some((item) => item.event === "exit"));
    const names = h.names();
    assert.ok(names.indexOf("session_end") < names.indexOf("exit"), "result flushed before the kill");
    assert.equal(h.events.at(-1).data.reason, "interrupted");
    assert.ok(!names.includes("error"));
    await assert.rejects(h.call("session.send", { session, text: "more" }), { code: "session_ended" });
    await h.call("session.stop", { session });
  });

  it("interrupt of an idle session kills the group at once", async () => {
    const { h, tracked } = trackingHarness();
    const { session } = await started(h, { prompt: "x" });
    await h.until(() => h.names().includes("usage"));
    await h.call("session.interrupt", { session });
    await waitFor(() => !pidAlive(tracked[0].pid));
    await h.until((events) => events.some((item) => item.event === "exit"));
    assert.equal(h.events.at(-1).data.reason, "interrupted");
    await h.call("session.stop", { session });
  });

  it("refuses sends while interrupting so no later turn is killed", async () => {
    const { h, tracked } = trackingHarness({ interruptGraceMs: 400 });
    const { session } = await started(h, { prompt: "stuck" });
    const interrupt = h.call("session.interrupt", { session });
    await new Promise((resolve) => setTimeout(resolve, 50));
    await assert.rejects(h.call("session.send", { session, text: "next" }), { code: "session_interrupting" });
    await interrupt;
    await waitFor(() => !pidAlive(tracked[0].pid));
    assert.equal(fakeSdk.calls[0].sent.includes("next"), false);
    await h.call("session.stop", { session });
  });

  it("kills only this session's group when an interrupt does not end the turn", async () => {
    const { h, tracked } = trackingHarness({ interruptGraceMs: 150 });
    const other = await started(h);
    const stuck = await started(h, { prompt: "stuck" });
    const [otherPid, stuckPid] = tracked.map((item) => item.pid);
    await h.call("session.interrupt", { session: stuck.session });
    await waitFor(() => !pidAlive(stuckPid) && !pidAlive(stuck.call.grandchild));
    await h.until((events) => events.some((item) => item.session === stuck.session && item.event === "exit"));
    const exit = h.events.find((item) => item.session === stuck.session && item.event === "exit");
    assert.equal(exit.data.reason, "interrupted");
    assert.ok(!h.events.some((item) => item.session === stuck.session && item.event === "error"));
    assert.ok(pidAlive(otherPid));
    await h.call("session.stop", { session: other.session });
    await h.call("session.stop", { session: stuck.session });
  });
});
