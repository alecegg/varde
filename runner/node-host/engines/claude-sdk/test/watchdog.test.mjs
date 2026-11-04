import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import { fakeSdk, harness } from "./helpers.mjs";

const params = { cwd: "/", model: "m", mode: "workspace-write", stream_idle_timeout_s: 0.1 };
const silentFlags = (h) =>
  h.events.filter((item) => item.event === "status" && "silent" in item.data).map((item) => item.data.silent);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

describe("silence watchdog", () => {
  beforeEach(() => fakeSdk.reset());

  it("flags mid-turn silence without killing, then clears on activity", async () => {
    const h = harness();
    const { session } = await h.call("session.start", { ...params, prompt: "hang" });
    await h.until(() => silentFlags(h).includes(true));
    await sleep(300);
    assert.deepEqual(silentFlags(h), [true], "flagged once, not repeatedly");
    assert.equal(fakeSdk.calls[0].closed, false, "query not closed");
    assert.equal(fakeSdk.calls[0].interrupted, 0, "query not interrupted");
    assert.equal((await h.call("session.alive", { session })).alive, true);
    await h.call("session.send", { session, text: "wake" });
    await h.until(() => h.names().includes("usage"));
    assert.deepEqual(silentFlags(h), [true, false]);
    await h.call("session.stop", { session });
  });

  it("does not flag while a tool is in flight", async () => {
    const h = harness();
    const { session } = await h.call("session.start", { ...params, prompt: "toolhang" });
    await h.until(() => h.names().includes("tool_intent"));
    await sleep(450);
    assert.deepEqual(silentFlags(h), []);
    await h.call("session.stop", { session });
  });

  it("does not flag an idle session", async () => {
    const h = harness();
    const { session } = await h.call("session.start", params);
    await sleep(450);
    assert.deepEqual(silentFlags(h), []);
    await h.call("session.stop", { session });
  });

  it("stops the timer when the session stops", async () => {
    const h = harness();
    const { session } = await h.call("session.start", { ...params, prompt: "hang" });
    await h.call("session.stop", { session });
    const before = h.events.length;
    await sleep(350);
    assert.equal(h.events.length, before);
  });

  it("rejects a bad timeout", async () => {
    const h = harness();
    await assert.rejects(h.call("session.start", { ...params, stream_idle_timeout_s: 0 }), {
      code: "invalid_params",
    });
  });
});
