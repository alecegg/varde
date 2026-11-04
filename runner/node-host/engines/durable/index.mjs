import { resolve } from "node:path";
import { defineEngine } from "../../engine-api.mjs";
import * as events from "./events.mjs";
import * as approvals from "./approvals.mjs";
import * as tools from "./tools/index.mjs";
import * as sessions from "./sessions.mjs";
import { openDurableStorage } from "./storage.mjs";

const modules = [events, approvals, tools, sessions];
const methods = new Map(
  modules.flatMap((module) => Object.entries(module.methods)),
);

let ctx;
let durable;
let initialized = [];

const engine = {
  name: "pi-durable",
  async init(engineContext) {
    ctx = engineContext;
    const storageDir = process.env.VARDE_PI_DURABLE_STORAGE_DIR;
    if (!storageDir) {
      throw new Error("VARDE_PI_DURABLE_STORAGE_DIR is required");
    }
    const storagePath = resolve(storageDir, "durable.sqlite");
    durable = await openDurableStorage(storagePath);
    const dependencies = { ctx, storage: durable.storage, events, approvals };
    for (const module of modules) {
      await module.init(dependencies);
      initialized.push(module);
    }
  },
  async handle(method, params) {
    const handler = methods.get(method);
    if (!handler) {
      const error = new Error(`unknown method: ${method}`);
      error.code = "unknown_method";
      throw error;
    }
    return await handler(params, { ctx, storage: durable?.storage });
  },
  async shutdown() {
    for (const module of [...initialized].reverse()) {
      await module.close();
    }
    initialized = [];
    await durable?.close();
    durable = undefined;
    ctx = undefined;
  },
};

export default defineEngine(engine);
