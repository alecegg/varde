// Test engine for the Node host: echo, event burst, slow call, crash, hang,
// children in the host group and in a tracked detached group.
import fs from "node:fs";
import { spawn } from "node:child_process";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const methods = {
  async echo(params) {
    return params;
  },
  async burst({ n, session }, ctx) {
    for (let i = 0; i < n; i += 1) ctx.emit("tick", session ?? null, { i });
    return { emitted: n };
  },
  async slow({ ms }) {
    await sleep(ms);
    return { slept: ms };
  },
  async crash() {
    process.exit(1);
  },
  async hang() {
    return new Promise(() => {});
  },
  async "spawn-child"({ tracked }, ctx) {
    const child = spawn("sleep", ["300"], { detached: Boolean(tracked), stdio: "ignore" });
    child.unref();
    if (tracked) ctx.trackChild(child.pid, child.pid);
    return { pid: child.pid, pgid: tracked ? child.pid : process.pid };
  },
  async untrack({ pgid }, ctx) {
    ctx.untrackChild(pgid);
    return {};
  },
  async "stdout-noise"() {
    console.log("this must not corrupt the frame stream");
    return {};
  },
  async "raw-line"({ line }) {
    fs.writeSync(1, `${line}\n`);
    return {};
  },
  async big({ bytes }) {
    return { blob: "x".repeat(bytes) };
  },
  async "non-object"() {
    return 5;
  },
};

export default {
  name: "echo",
  async init(ctx) {
    ctx.log("info", "echo engine ready");
  },
  async handle(method, params, ctx) {
    const fn = methods[method];
    if (!fn) {
      const err = new Error(`unknown method ${method}`);
      err.code = "unknown_method";
      throw err;
    }
    return fn(params, ctx);
  },
  async shutdown() {},
};
