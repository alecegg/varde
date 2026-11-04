// Proves the tool registrations bind to a real Durable Harness and return the
// content-array result shape (faux provider, no network, no keys).
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { it } from "node:test";
import { createModels } from "@earendil-works/pi-ai";
import { fauxAssistantMessage, fauxProvider, fauxText, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { Harness, ToolResultEntry, createRegistry, defineExtension } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { buildSessionTools } from "../tools/index.mjs";

it("runs read, write and a refused escape through a real Harness", async () => {
  const dir = await mkdtemp(join(tmpdir(), "tools-harness-"));
  const cwd = join(dir, "repo");
  await mkdir(cwd);
  await writeFile(join(cwd, "hello.txt"), "hello from file");
  const tools = buildSessionTools({ cwd, role: "builder", mode: "workspace-write", env: {} });
  const extension = defineExtension({ name: "varde-tools", tools });
  const registry = createRegistry();
  registry.install(extension);

  const faux = fauxProvider({ models: [{ id: "faux-1", contextWindow: 8192, maxTokens: 256 }] });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses([
    fauxAssistantMessage(
      [
        fauxToolCall("read", { path: "hello.txt" }),
        fauxToolCall("write", { path: "out.txt", content: "written" }),
        fauxToolCall("read", { path: "../outside" }),
      ],
      { stopReason: "toolUse" },
    ),
    fauxAssistantMessage([fauxText("done")]),
  ]);

  const harness = await Harness.open(await openNodeSqliteStorage(join(dir, "db.sqlite")), { models, registry }, BACKGROUND_CONTEXT);
  try {
    const model = faux.getModel();
    const conversation = await harness.root(BACKGROUND_CONTEXT, {
      agent: { model: { provider: model.provider, modelId: model.id }, extensions: [extension], tools, instructions: "test" },
    });
    const submission = await conversation.submit({ type: "input", content: "go" }, BACKGROUND_CONTEXT);
    const settled = await submission.wait(BACKGROUND_CONTEXT);
    assert.equal(settled.status, "done");
    const page = await conversation.entries({ order: "ascending" }, 100, undefined, BACKGROUND_CONTEXT);
    const results = page.items.filter((entry) => ToolResultEntry.is(entry));
    const serialized = JSON.stringify(results);
    assert.equal(results.length, 3);
    assert.match(serialized, /hello from file/);
    assert.match(serialized, /refused: path escapes the workspace/);
    assert.equal(await readFile(join(cwd, "out.txt"), "utf8"), "written");
  } finally {
    await harness.close(BACKGROUND_CONTEXT);
  }
});
