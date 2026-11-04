import { defineEngine } from "../../engine-api.mjs";
import { spawn } from "node:child_process";

/** @typedef {import('../../engine-api.mjs').Engine} Engine */

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** @type {Engine} */
const engine = {
  name: "fake",
  async init(ctx) {
    ctx.log("info", "fake engine initialized");
  },
  async handle(method, params, ctx) {
    switch (method) {
      case "echo":
        return params;
      case "burst": {
        const count = Number(params.count ?? 0);
        for (let index = 0; index < count; index += 1) {
          ctx.emit("tick", String(params.session ?? "s1"), { index });
        }
        return { emitted: count };
      }
      case "slow": {
        const ms = Number(params.ms ?? 0);
        await pause(ms);
        return { waited_ms: ms };
      }
      case "crash-on-request":
        process.exit(17);
      case "hang":
        return new Promise(() => {});
      case "stdout-noise":
        console.log("fake engine stdout must be redirected");
        return { clean: true };
      case "track-child": {
        const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
          detached: true,
          stdio: "ignore",
        });
        child.unref();
        if (child.pid === undefined) throw new Error("child did not receive a pid");
        ctx.trackChild(child.pid, child.pid);
        return { pid: child.pid, pgid: child.pid };
      }
      case "untrack-child":
        ctx.untrackChild(Number(params.pgid));
        return {};
      default: {
        const error = new Error(`unknown method: ${method}`);
        error.code = "unknown_method";
        throw error;
      }
    }
  },
  async shutdown() {},
};

export default defineEngine(engine);
