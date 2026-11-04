#!/usr/bin/env node
// Generic Node host: JSON Lines over stdio, one engine module loaded by path.
// Protocol: PROTOCOL.md. Usage: node host.mjs <engine-module-path>
import path from "node:path";
import { pathToFileURL } from "node:url";

const PROTOCOL = 1;
const MAX_LINE_BYTES = 16 * 1024 * 1024;
const SHUTDOWN_DEADLINE_MS = 2000;
const MIN_NODE = [22, 19];

function log(level, message) {
  process.stderr.write(`[host] ${level}: ${message}\n`);
}

function nodeIsSupported() {
  const [major, minor] = process.versions.node.split(".").map(Number);
  return major > MIN_NODE[0] || (major === MIN_NODE[0] && minor >= MIN_NODE[1]);
}

if (!nodeIsSupported()) {
  log("error", `Node >= ${MIN_NODE.join(".")} required, found ${process.versions.node}`);
  process.exit(3);
}

const writeFrameBytes = process.stdout.write.bind(process.stdout);
process.stdout.write = (chunk, encoding, callback) =>
  process.stderr.write(chunk, encoding, callback);
process.stdout.on("error", () => {});
// The runner may already be gone: broken pipes must not raise or recurse into log().
process.stderr.on("error", () => {});

function send(frame) {
  writeFrameBytes(`${JSON.stringify(frame)}\n`);
}

let engine = null;
let seq = 0;
let shuttingDown = false;
const trackedGroups = new Map();

const ctx = {
  emit(event, session, data) {
    seq += 1;
    send({ event, session: session ?? null, data: data ?? {}, seq });
  },
  log,
  trackChild(pid, pgid) {
    if (!Number.isSafeInteger(pid) || !Number.isSafeInteger(pgid) || pgid <= 1) {
      throw new TypeError("trackChild needs integer pid and pgid > 1");
    }
    trackedGroups.set(pgid, pid);
    ctx.emit("child_tracked", null, { pid, pgid });
  },
  untrackChild(pgid) {
    const pid = trackedGroups.get(pgid);
    if (pid === undefined) return;
    trackedGroups.delete(pgid);
    ctx.emit("child_untracked", null, { pid, pgid });
  },
};

function killGroup(pgid) {
  try {
    process.kill(-pgid, "SIGKILL");
  } catch {
    // group already gone
  }
}

function killOwnGroupAndExit(code) {
  // The runner starts the host as a session leader, so pgid == pid and this
  // reaches engine children in the host group. Not a leader: plain exit.
  try {
    process.kill(-process.pid, 0);
    process.kill(-process.pid, "SIGKILL");
  } catch {
    // not a group leader
  }
  process.exit(code);
}

async function shutdown(reason, exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  log("info", `shutdown: ${reason}`);
  if (engine) {
    const deadline = new Promise((resolve) => setTimeout(resolve, SHUTDOWN_DEADLINE_MS));
    try {
      await Promise.race([Promise.resolve().then(() => engine.shutdown()), deadline]);
    } catch (err) {
      log("error", `engine shutdown failed: ${err?.message ?? err}`);
    }
  }
  for (const pgid of trackedGroups.keys()) killGroup(pgid);
  killOwnGroupAndExit(exitCode);
}

function errorReply(id, code, message) {
  send({ id, error: { code, message } });
}

async function dispatch(id, method, params) {
  try {
    const result = await engine.handle(method, params, ctx);
    if (result === null || typeof result !== "object" || Array.isArray(result)) {
      errorReply(id, "bad_result", "engine returned a non-object result");
      return;
    }
    send({ id, result });
  } catch (err) {
    const code = typeof err?.code === "string" ? err.code : "engine_error";
    errorReply(id, code, String(err?.message ?? err));
  }
}

function handleLine(line) {
  if (line.length > MAX_LINE_BYTES) {
    log("error", "request line exceeds the frame limit");
    shutdown("oversize frame", 5);
    return;
  }
  if (line.length === 0) return;
  let frame;
  try {
    frame = JSON.parse(line.toString("utf8"));
  } catch {
    log("error", "ignored malformed request line");
    return;
  }
  const { id, method } = frame ?? {};
  if (!Number.isSafeInteger(id)) {
    log("error", "ignored request without integer id");
    return;
  }
  const params = frame.params ?? {};
  if (typeof method !== "string" || params === null || typeof params !== "object") {
    errorReply(id, "bad_request", "request needs string method and object params");
    return;
  }
  if (shuttingDown) {
    errorReply(id, "shutting_down", "host is shutting down");
    return;
  }
  dispatch(id, method, params);
}

function readRequests() {
  let parts = [];
  let partBytes = 0;
  process.stdin.on("data", (chunk) => {
    let start = 0;
    for (;;) {
      const end = chunk.indexOf(0x0a, start);
      if (end === -1) break;
      parts.push(chunk.subarray(start, end));
      const line = Buffer.concat(parts);
      parts = [];
      partBytes = 0;
      handleLine(line);
      start = end + 1;
    }
    const rest = chunk.subarray(start);
    if (rest.length === 0) return;
    parts.push(rest);
    partBytes += rest.length;
    if (partBytes > MAX_LINE_BYTES) {
      log("error", "request line exceeds the frame limit");
      shutdown("oversize frame", 5);
    }
  });
  process.stdin.on("end", () => shutdown("stdin closed"));
  process.stdin.on("close", () => shutdown("stdin closed"));
}

async function loadEngine(modulePath) {
  const loaded = await import(pathToFileURL(path.resolve(modulePath)).href);
  const candidate = loaded.default;
  const valid =
    candidate &&
    typeof candidate.name === "string" &&
    ["init", "handle", "shutdown"].every((key) => typeof candidate[key] === "function");
  if (!valid) throw new TypeError("engine default export needs name, init, handle, shutdown");
  return candidate;
}

async function main() {
  const modulePath = process.argv[2];
  if (!modulePath) {
    log("error", "usage: host.mjs <engine-module-path>");
    process.exit(2);
  }
  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("uncaughtException", (err) => {
    log("error", `uncaught: ${err?.stack ?? err}`);
    shutdown("uncaught exception", 1);
  });
  process.on("unhandledRejection", (err) => {
    log("error", `unhandled rejection: ${err?.stack ?? err}`);
    shutdown("unhandled rejection", 1);
  });
  try {
    engine = await loadEngine(modulePath);
    await engine.init(ctx);
  } catch (err) {
    log("error", `engine failed to start: ${err?.message ?? err}`);
    await shutdown("engine init failed", 4);
    return;
  }
  send({ type: "ready", protocol: PROTOCOL, engine: engine.name, node: process.versions.node });
  readRequests();
}

main();
