// One SDK query with streaming input and event normalization.
import { InputQueue, userMessage } from "./input-queue.mjs";
import { normalizeMessage } from "./normalize.mjs";

export class Session {
  state = "idle"; // idle | running | ended
  handle = null;
  query = null;
  killedBy = null;
  interrupting = false;
  #idleWaiters = [];
  toolsInFlight = new Set();
  #input = new InputQueue();
  #stopped = false;

  constructor({ id, cwd, ctx, deps, idleTimeoutS }) {
    this.idleTimeoutS = idleTimeoutS;
    this.id = id;
    this.cwd = cwd;
    this.ctx = ctx;
    this.deps = deps;
  }

  emit(event, data) {
    this.ctx.emit(event, this.id, data);
  }

  begin(sdk, options) {
    const { permission, processes } = this.deps;
    const full = {
      ...options,
      ...(permission ? { canUseTool: permission.canUseTool(this) } : {}),
      ...(processes ? processes.spawnOptions(this) : {}),
    };
    this.query = sdk.query({ prompt: this.#input, options: full });
    this.deps.watchdog?.attach(this);
    this.done = this.#consume();
  }

  send(text) {
    if (this.interrupting && this.state !== "ended") {
      const error = new Error("session is being interrupted; its process group is torn down");
      error.code = "session_interrupting";
      throw error;
    }
    this.deps.watchdog?.touch(this);
    if (!this.#input.push(userMessage(text))) {
      const error = new Error("session input is closed");
      error.code = "session_ended";
      throw error;
    }
    this.state = "running";
    this.emit("status", { status: "running" });
  }

  // Resolves when the running turn produces its result, the query ends, or the timeout passes.
  waitIdle(timeoutMs) {
    if (this.state !== "running") return Promise.resolve();
    return new Promise((resolve) => {
      const timer = setTimeout(resolve, timeoutMs);
      timer.unref?.();
      this.#idleWaiters.push(() => {
        clearTimeout(timer);
        resolve();
      });
    });
  }

  #releaseIdleWaiters() {
    for (const release of this.#idleWaiters.splice(0)) release();
  }

  expirePermissions() {
    this.deps.permission?.expireAll(this);
  }

  async interrupt() {
    if (this.deps.processes) return this.deps.processes.interrupt(this);
    this.expirePermissions();
    await this.query?.interrupt();
    return undefined;
  }

  async stop() {
    this.#stopped = true;
    this.expirePermissions();
    this.#input.close();
    if (this.deps.processes) await this.deps.processes.stop(this);
    else this.query?.close();
    await this.done;
  }

  async #consume() {
    let reason = "stream_ended";
    let message;
    try {
      for await (const sdkMessage of this.query) {
        this.deps.watchdog?.touch(this);
        this.#handleMessage(sdkMessage);
      }
    } catch (error) {
      if (!this.#stopped && !this.killedBy) {
        reason = "error";
        message = String(error?.message ?? error);
        this.emit("error", { message });
      }
    }
    if (this.#stopped) reason = "stopped";
    else if (this.killedBy) reason = "interrupted";
    this.state = "ended";
    this.#releaseIdleWaiters();
    this.#input.close();
    this.expirePermissions();
    this.deps.watchdog?.detach(this);
    this.deps.processes?.release(this);
    this.emit("exit", message ? { reason, message } : { reason });
  }

  #handleMessage(message) {
    if (message?.type === "system" && message.subtype === "init" && !this.handle) {
      this.handle = message.session_id;
      this.emit("handle", { handle: this.handle, cwd: this.cwd });
      return;
    }
    if (message?.type === "result") this.state = "idle";
    for (const { event, data } of normalizeMessage(message)) {
      if (event === "tool_intent") this.toolsInFlight.add(data.call_id);
      if (event === "tool_result") this.toolsInFlight.delete(data.call_id);
      this.emit(event, data);
    }
    if (message?.type === "result") {
      this.toolsInFlight.clear();
      this.#releaseIdleWaiters();
    }
  }
}
