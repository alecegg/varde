import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import * as fakeSdk from "./fake-sdk.mjs";
import { harness as makeHarness } from "./helpers.mjs";
import { REMOVED_ENV_VARS } from "../options.mjs";

const baseParams = { cwd: "/work", model: "fake-model", mode: "workspace-write" };

const bare = { permission: null, watchdog: null, processes: null };
const harness = (deps = {}) => makeHarness({ ...bare, ...deps });

describe("claude-sdk engine", () => {
  beforeEach(() => fakeSdk.reset());

  it("starts, normalizes a turn and reports usage with USD", async () => {
    const h = harness();
    const { session, resumed } = await h.call("session.start", { ...baseParams, prompt: "tool" });
    assert.equal(resumed, false);
    await h.until(() => h.names().includes("usage"));
    assert.deepEqual(h.names(), [
      "status", "handle", "text", "tool_intent", "tool_result", "session_end", "status", "usage",
    ]);
    assert.ok(h.events.every((item) => item.session === session));
    const byName = Object.fromEntries(h.events.map((item) => [item.event, item.data]));
    assert.deepEqual(byName.handle, { handle: fakeSdk.FAKE_HANDLE, cwd: "/work" });
    assert.deepEqual(byName.tool_intent, { call_id: "tu1", name: "Bash", status: "running", input: { command: "ls" } });
    assert.deepEqual(byName.tool_result, { call_id: "tu1", status: "completed", content: "ok" });
    assert.deepEqual(byName.session_end, { status: "completed", result: "done", subtype: "success" });
    assert.equal(byName.usage.total_cost_usd, 0.0123);
    assert.equal(byName.usage.context_window, 200000);
    assert.equal(byName.usage.usage.cache_read_input_tokens, 2);
    assert.equal(byName.usage.model_usage["fake-model"].cost_usd, 0.0123);
    await h.call("session.stop", { session });
  });

  it("sends further messages and answers session.alive", async () => {
    const h = harness();
    const { session } = await h.call("session.start", baseParams);
    assert.deepEqual(await h.call("session.alive", { session }), { alive: true, state: "idle" });
    await h.call("session.send", { session, text: "hello" });
    assert.deepEqual(await h.call("session.alive", { session }), { alive: true, state: "running" });
    await h.until(() => h.names().includes("usage"));
    assert.deepEqual(fakeSdk.calls[0].sent, ["hello"]);
    assert.equal((await h.call("session.alive", { session })).state, "idle");
    await h.call("session.stop", { session });
    assert.deepEqual(await h.call("session.alive", { session }), { alive: false, state: "ended" });
  });

  it("resumes from a handle with the original cwd and reports resumed", async () => {
    const h = harness();
    const result = await h.call("session.start", { ...baseParams, resume_handle: "old-handle", prompt: "again" });
    assert.equal(result.resumed, true);
    assert.equal(fakeSdk.calls[0].options.resume, "old-handle");
    assert.equal(fakeSdk.calls[0].options.cwd, "/work");
    await h.until(() => h.names().includes("handle"));
    assert.equal(h.events.find((e) => e.event === "handle").data.handle, "old-handle");
    await h.call("session.stop", { session: result.session });
  });

  it("starts fresh without a handle", async () => {
    const h = harness();
    const { session } = await h.call("session.start", baseParams);
    assert.equal("resume" in fakeSdk.calls[0].options, false);
    await h.call("session.stop", { session });
  });

  it("maps modes, effort and model into SDK options", async () => {
    const h = harness();
    const cases = [
      ["read-only", "plan", false],
      ["workspace-write", "acceptEdits", false],
      ["auto", "acceptEdits", false],
      ["full-access", "bypassPermissions", true],
    ];
    for (const [mode, expected, bypass] of cases) {
      fakeSdk.reset();
      const { session } = await h.call("session.start", { ...baseParams, mode, effort: "high" });
      const { options } = fakeSdk.calls[0];
      assert.equal(options.permissionMode, expected);
      assert.equal(options.allowDangerouslySkipPermissions === true, bypass);
      assert.equal(options.effort, "high");
      assert.equal(options.model, "fake-model");
      await h.call("session.stop", { session });
    }
  });

  it("rejects invalid parameters with contract codes", async () => {
    const h = harness();
    const code = async (params) => {
      try {
        await h.call("session.start", params);
      } catch (error) {
        return error.code;
      }
      return null;
    };
    assert.equal(await code({ ...baseParams, mode: "bogus" }), "invalid_mode");
    assert.equal(await code({ ...baseParams, effort: "extreme" }), "invalid_effort");
    assert.equal(await code({ ...baseParams, cwd: "relative" }), "invalid_params");
    assert.equal(await code({ ...baseParams, model: "" }), "invalid_params");
    assert.equal(await code({ ...baseParams, env: [] }), "invalid_params");
    await assert.rejects(h.call("session.send", { session: "nope", text: "x" }), { code: "unknown_session" });
    await assert.rejects(h.call("nope", {}), { code: "unknown_method" });
    await assert.rejects(h.call("permission.respond", { session: "s", request_id: "r", decision: "approve" }), {
      code: "unsupported",
    });
  });

  it("passes the session env with credentials removed and never logs values", async () => {
    const h = harness();
    const env = { PATH: "/bin", VARDE_AGENT_ID: "a1", VARDE_HARNESS: "claude-sdk" };
    for (const name of REMOVED_ENV_VARS) env[name] = "secret-value";
    const { session } = await h.call("session.start", { ...baseParams, env });
    assert.deepEqual(fakeSdk.calls[0].options.env, {
      PATH: "/bin",
      VARDE_AGENT_ID: "a1",
      VARDE_HARNESS: "claude-sdk",
    });
    await h.call("session.stop", { session });
    assert.ok(!JSON.stringify(h.events).includes("secret-value"));
  });

  it("falls back to a scrubbed process env when none is given", async () => {
    process.env.ANTHROPIC_API_KEY = "secret-value";
    try {
      const h = harness();
      const { session } = await h.call("session.start", baseParams);
      assert.equal("ANTHROPIC_API_KEY" in fakeSdk.calls[0].options.env, false);
      await h.call("session.stop", { session });
    } finally {
      delete process.env.ANTHROPIC_API_KEY;
    }
  });

  it("interrupt calls the SDK once and the session keeps running", async () => {
    const h = harness();
    const { session } = await h.call("session.start", { ...baseParams, prompt: "hang" });
    await h.call("session.interrupt", { session });
    assert.equal(fakeSdk.calls[0].interrupted, 1);
    await h.until(() => h.names().includes("usage"));
    assert.equal(h.events.find((e) => e.event === "session_end").data.status, "failed");
    assert.equal((await h.call("session.alive", { session })).alive, true);
    await h.call("session.stop", { session });
  });

  it("stop closes the query, emits exit stopped, and is idempotent", async () => {
    const h = harness();
    const { session } = await h.call("session.start", { ...baseParams, prompt: "hang" });
    await h.call("session.stop", { session });
    assert.equal(fakeSdk.calls[0].closed, true);
    assert.deepEqual(h.events.at(-1), { event: "exit", session, data: { reason: "stopped" } });
    assert.deepEqual(await h.call("session.stop", { session }), {});
  });

  it("a stream failure emits error then exit and later sends fail", async () => {
    const h = harness();
    const { session } = await h.call("session.start", { ...baseParams, prompt: "x" });
    await h.until(() => h.names().includes("usage"));
    await h.call("session.send", { session, text: "fail" });
    await h.until(() => h.names().includes("exit"));
    const names = h.names();
    assert.deepEqual(names.slice(-2), ["error", "exit"]);
    assert.equal(h.events.at(-1).data.reason, "error");
    await assert.rejects(h.call("session.send", { session, text: "more" }), { code: "session_ended" });
    await h.call("session.stop", { session });
  });

  it("reports sdk_unavailable and drops the session", async () => {
    const h = harness({ loadSdk: async () => Promise.reject(Object.assign(new Error("missing"), { code: "sdk_unavailable" })) });
    await assert.rejects(h.call("session.start", baseParams), { code: "sdk_unavailable" });
    assert.deepEqual(await h.call("session.alive", { session: "x" }), { alive: false, state: "ended" });
  });

  it("shutdown stops every session", async () => {
    const h = harness();
    await h.call("session.start", { ...baseParams, session: "a" });
    await h.call("session.start", { ...baseParams, session: "b" });
    await assert.rejects(h.call("session.start", { ...baseParams, session: "a" }), { code: "session_exists" });
    await h.engine.shutdown();
    assert.ok(fakeSdk.calls.every((call) => call.closed));
  });

  it("calls the optional seams when installed", async () => {
    const seen = [];
    const permission = { canUseTool: () => "can-use-tool", expireAll: () => {} };
    const watchdog = {
      attach: () => seen.push("attach"),
      touch: () => seen.push("touch"),
      detach: () => seen.push("detach"),
    };
    const h = harness({ permission, watchdog });
    const { session } = await h.call("session.start", { ...baseParams, prompt: "x" });
    assert.equal(fakeSdk.calls[0].options.canUseTool, "can-use-tool");
    await h.until(() => h.names().includes("usage"));
    await h.call("session.stop", { session });
    assert.equal(seen[0], "attach");
    assert.ok(seen.includes("touch"));
    assert.equal(seen.at(-1), "detach");
  });
});
