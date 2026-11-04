import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { builtinModels } from "@earendil-works/pi-ai/providers/all";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import * as sessions from "../sessions.mjs";

test("session engine exposes the claude-sdk host lifecycle contract", () => {
  assert.deepEqual(
    Object.keys(sessions.methods).sort(),
    ["session.alive", "session.interrupt", "session.send", "session.start", "session.stop"],
  );
});

test("unknown sessions are ended and stop is idempotent", async () => {
  assert.deepEqual(await sessions.methods["session.alive"]({ session: "missing" }), { alive: false, state: "ended" });
  assert.deepEqual(await sessions.methods["session.stop"]({ session: "missing" }), {});
});

test("start and send validate required fields", async () => {
  await assert.rejects(sessions.methods["session.start"]({}), /cwd must be a non-empty string/);
  await assert.rejects(sessions.methods["session.send"]({}), /session must be a non-empty string/);
});

test("start creates an ownerless conversation and can resume it by id", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-durable-session-"));
  const registered = [];
  const models = builtinModels();
  const [model] = models.getModels("openai");
  assert.ok(model);
  await sessions.init({
    ctx: { log() {} },
    storage: await openNodeSqliteStorage(join(directory, "durable.sqlite")),
    approvals: {},
    events: {
      registerConversation(id, conversation) { registered.push([id, conversation]); },
      unregisterConversation() {},
    },
  });
  try {
    const started = await sessions.methods["session.start"]({
      cwd: directory,
      provider: model.provider,
      model: `${model.provider}/${model.id}`,
      role: "builder",
      mode: "workspace-write",
      prompt: "",
      env: {},
    });
    assert.equal(typeof started.session, "string", JSON.stringify(started));
    assert.equal((await sessions.methods["session.alive"]({ session: started.session })).state, "idle");
    assert.equal(registered[0][0], started.session);
    const resumed = await sessions.methods["session.start"]({
      cwd: directory,
      provider: model.provider,
      model: `${model.provider}/${model.id}`,
      role: "builder",
      mode: "workspace-write",
      conversation: started.session,
      env: {},
    });
    assert.deepEqual(resumed, { session: started.session, resumed: true });
    assert.deepEqual(await sessions.methods["session.stop"]({ session: started.session }), {});
    assert.deepEqual(await sessions.methods["session.alive"]({ session: started.session }), { alive: false, state: "ended" });
  } finally {
    await sessions.close();
  }
});
