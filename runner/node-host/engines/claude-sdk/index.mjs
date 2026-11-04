import { randomUUID } from "node:crypto";
import { defineEngine } from "../../engine-api.mjs";
import { ContractError, buildQueryOptions } from "./options.mjs";
import { createProcesses } from "./interrupt.mjs";
import { createPermissionBridge } from "./permission.mjs";
import { Session } from "./session.mjs";
import { DEFAULT_IDLE_S, createWatchdog } from "./watchdog.mjs";

const SDK_PACKAGE = "@anthropic-ai/claude-agent-sdk";

async function defaultLoadSdk() {
  const specifier = process.env.VARDE_CLAUDE_SDK_MODULE || SDK_PACKAGE;
  try {
    return await import(specifier);
  } catch (error) {
    throw new ContractError("sdk_unavailable", `cannot load ${specifier}: ${error?.message ?? error}`);
  }
}

function idleTimeout(params) {
  const value = params.stream_idle_timeout_s ?? DEFAULT_IDLE_S;
  if (typeof value !== "number" || !(value > 0)) {
    throw new ContractError("invalid_params", "stream_idle_timeout_s must be a positive number");
  }
  return value;
}

function requireString(params, key) {
  if (typeof params[key] !== "string" || params[key] === "") {
    throw new ContractError("invalid_params", `${key} must be a non-empty string`);
  }
  return params[key];
}

export function createEngine(overrides = {}) {
  // Pass null for a seam to run without it (the s1 engine-core tests do).
  const deps = {
    permission: createPermissionBridge(),
    watchdog: createWatchdog(),
    processes: createProcesses(),
    ...overrides,
  };
  const loadSdk = deps.loadSdk ?? defaultLoadSdk;
  const sessions = new Map();
  let sdkPromise = null;
  const sdk = () => (sdkPromise ??= loadSdk());

  function find(params) {
    const session = sessions.get(requireString(params, "session"));
    if (!session) throw new ContractError("unknown_session", `unknown session ${params.session}`);
    return session;
  }

  async function start(params, ctx) {
    const options = buildQueryOptions(params);
    const id = params.session ?? randomUUID();
    if (sessions.has(id)) throw new ContractError("session_exists", `session ${id} already exists`);
    const session = new Session({
      id,
      cwd: params.cwd,
      ctx,
      deps,
      idleTimeoutS: idleTimeout(params),
    });
    sessions.set(id, session);
    try {
      session.begin(await sdk(), options);
    } catch (error) {
      sessions.delete(id);
      throw error;
    }
    if (typeof params.prompt === "string" && params.prompt !== "") session.send(params.prompt);
    return { session: id, resumed: params.resume_handle != null };
  }

  const handlers = {
    "session.start": start,
    async "session.send"(params) {
      find(params).send(requireString(params, "text"));
      return {};
    },
    async "session.interrupt"(params) {
      await find(params).interrupt();
      return {};
    },
    async "session.stop"(params) {
      const session = sessions.get(requireString(params, "session"));
      if (session) {
        await session.stop();
        sessions.delete(session.id);
      }
      return {};
    },
    async "permission.respond"(params) {
      if (!deps.permission) throw new ContractError("unsupported", "permission bridge is not installed");
      const session = find(params);
      await deps.permission.respond(session, requireString(params, "request_id"), requireString(params, "decision"));
      return {};
    },
    async "session.alive"(params) {
      const session = sessions.get(requireString(params, "session"));
      return { alive: session !== undefined && session.state !== "ended", state: session?.state ?? "ended" };
    },
  };

  return defineEngine({
    name: "claude-sdk",
    async init(ctx) {
      ctx.log("info", "claude-sdk engine ready");
    },
    async handle(method, params, ctx) {
      const handler = handlers[method];
      if (!handler) throw new ContractError("unknown_method", `unknown method: ${method}`);
      return handler(params, ctx);
    },
    async shutdown() {
      await Promise.allSettled([...sessions.values()].map((session) => session.stop()));
      sessions.clear();
    },
  });
}

export default createEngine();
