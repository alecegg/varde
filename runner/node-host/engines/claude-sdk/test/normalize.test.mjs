import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { normalizeMessage } from "../normalize.mjs";
import { InputQueue, userMessage } from "../input-queue.mjs";

describe("normalizeMessage", () => {
  it("ignores unknown message types", () => {
    assert.deepEqual(normalizeMessage({ type: "stream_event" }), []);
    assert.deepEqual(normalizeMessage(undefined), []);
  });

  it("maps an assistant error and failed tool results", () => {
    const events = normalizeMessage({ type: "assistant", error: "rate_limit", message: { content: [] } });
    assert.equal(events[0].event, "error");
    const results = normalizeMessage({
      type: "user",
      message: { content: [{ type: "tool_result", tool_use_id: "t", is_error: true, content: "boom" }, { type: "text" }] },
    });
    assert.deepEqual(results, [{ event: "tool_result", data: { call_id: "t", status: "failed", content: "boom" } }]);
    assert.deepEqual(normalizeMessage({ type: "user", message: { content: "plain" } }), []);
  });

  it("marks error results failed and tolerates missing usage", () => {
    const events = normalizeMessage({ type: "result", subtype: "error_max_turns" });
    assert.equal(events[0].data.status, "failed");
    assert.equal(events[2].data.total_cost_usd, 0);
    assert.equal(events[2].data.context_window, null);
  });

  it("maps rate-limit messages to usage limits", () => {
    const [event] = normalizeMessage({ type: "rate_limit_event", rate_limit_info: { status: "ok" } });
    assert.deepEqual(event, { event: "usage", data: { source: "claude", limit: { status: "ok" } } });
  });
});

describe("InputQueue", () => {
  it("delivers queued and later items, then ends on close", async () => {
    const queue = new InputQueue();
    queue.push(userMessage("a"));
    const iterator = queue[Symbol.asyncIterator]();
    assert.equal((await iterator.next()).value.message.content, "a");
    const waiting = iterator.next();
    queue.push(userMessage("b"));
    assert.equal((await waiting).value.message.content, "b");
    const last = iterator.next();
    queue.close();
    assert.equal((await last).done, true);
    assert.equal(queue.push(userMessage("c")), false);
  });
});
