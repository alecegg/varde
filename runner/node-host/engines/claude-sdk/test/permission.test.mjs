import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import { fakeSdk, harness } from "./helpers.mjs";
import { createPermissionBridge } from "../permission.mjs";

const params = { cwd: "/", model: "m", mode: "workspace-write", prompt: "perm" };
const resolved = (h) => h.events.filter((item) => item.event === "permission_resolved");

describe("permission bridge", () => {
  beforeEach(() => fakeSdk.reset());

  it("emits the request and resolves allow exactly once on approve", async () => {
    const h = harness();
    const { session } = await h.call("session.start", params);
    await h.until(() => h.names().includes("permission_requested"));
    const requested = h.events.find((item) => item.event === "permission_requested");
    assert.deepEqual(requested.data, {
      request_id: "tu-perm",
      tool_use_id: "tu-perm",
      kind: "tool",
      tool: "Bash",
      summary: "Run rm",
      input: { command: "rm" },
    });
    await h.call("permission.respond", { session, request_id: "tu-perm", decision: "approve" });
    await h.until(() => h.names().includes("usage"));
    assert.deepEqual(resolved(h).map((item) => item.data), [{ request_id: "tu-perm", decision: "approve" }]);
    assert.ok(h.events.some((item) => item.event === "text" && item.data.text === "perm:allow"));
    await assert.rejects(
      h.call("permission.respond", { session, request_id: "tu-perm", decision: "approve" }),
      { code: "unknown_request" },
    );
    await h.call("session.stop", { session });
    assert.equal(resolved(h).length, 1);
  });

  it("deny reaches the SDK as a deny", async () => {
    const h = harness();
    const { session } = await h.call("session.start", params);
    await h.until(() => h.names().includes("permission_requested"));
    await h.call("permission.respond", { session, request_id: "tu-perm", decision: "deny" });
    await h.until(() => h.names().includes("usage"));
    assert.ok(h.events.some((item) => item.event === "text" && item.data.text === "perm:deny"));
    assert.equal(resolved(h)[0].data.decision, "deny");
    await h.call("session.stop", { session });
  });

  it("expires a pending request when the session stops", async () => {
    const h = harness();
    const { session } = await h.call("session.start", params);
    await h.until(() => h.names().includes("permission_requested"));
    await h.call("session.stop", { session });
    assert.deepEqual(resolved(h).map((item) => item.data), [{ request_id: "tu-perm", decision: "expired" }]);
  });

  it("expires a pending request on interrupt, once", async () => {
    const h = harness();
    const { session } = await h.call("session.start", params);
    await h.until(() => h.names().includes("permission_requested"));
    await h.call("session.interrupt", { session });
    await h.until(() => resolved(h).length > 0);
    assert.deepEqual(resolved(h).map((item) => item.data.decision), ["expired"]);
    await assert.rejects(
      h.call("permission.respond", { session, request_id: "tu-perm", decision: "approve" }),
      { code: "unknown_request" },
    );
    await h.call("session.stop", { session });
    assert.equal(resolved(h).length, 1);
  });

  it("rejects an invalid decision and an already-aborted request", async () => {
    const bridge = createPermissionBridge();
    const emitted = [];
    const session = { id: "s", emit: (event, data) => emitted.push({ event, data }) };
    const abort = new AbortController();
    abort.abort();
    const result = await bridge.canUseTool(session)("Bash", {}, { signal: abort.signal, toolUseID: "t" });
    assert.equal(result.behavior, "deny");
    assert.deepEqual(emitted.map((item) => item.event), ["permission_resolved"]);
    await assert.rejects(bridge.respond(session, "t", "maybe"), { code: "invalid_params" });
  });
});
