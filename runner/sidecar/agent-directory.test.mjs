import assert from "node:assert/strict";
import test from "node:test";

import { listAgents, listWorkspaces } from "./agent-directory.mjs";

test("lists Paseo agents with the daemon-compatible default query", async () => {
  let argumentsReceived = "not-called";
  const entries = [
    { agent: { id: "agent-a", status: "running", updatedAt: "2026-10-20T10:00:00Z" }, workspace: { id: "workspace-a" } },
  ];
  const result = await listAgents({
    agents: { list: async (...args) => { argumentsReceived = args; return { entries }; } },
  });

  assert.deepEqual(argumentsReceived, []);
  assert.deepEqual(result, entries);
});

test("lists workspaces from agent workspace IDs and cwd when workspace objects are sparse", () => {
  assert.deepEqual(listWorkspaces([
    { agent: { workspaceId: "workspace-a", cwd: "/work/a" } },
    { agent: { workspaceId: "workspace-a", cwd: "/work/a" } },
    { agent: { id: "agent-b", cwd: "/work/b" } },
  ]), [
    { id: "workspace-a", title: "/work/a", cwd: "/work/a" },
  ]);
});
