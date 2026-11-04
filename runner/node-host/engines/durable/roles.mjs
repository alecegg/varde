// Which tools a role gets, and provider/model config resolution.
// Read-only roles are enforced by the tool set: the write tools are absent.
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
export const replayTable = require("./replay.json").tools;

const READ_TOOLS = ["read", "ls", "find", "grep", "bash"];
const WRITE_TOOLS = ["edit", "write"];
const READ_ONLY_ROLES = new Set(["explorer", "reviewer"]);
const WRITE_ROLES = new Set(["builder", "planner"]);
export const MODES = ["read-only", "workspace-write"];

export class RoleError extends Error {
  constructor(message) {
    super(message);
    this.code = "invalid_params";
  }
}

/** Effective mode: explorer and reviewer are read-only whatever the requested mode says. */
export function effectiveMode(role, mode) {
  if (!READ_ONLY_ROLES.has(role) && !WRITE_ROLES.has(role)) throw new RoleError(`unknown role: ${role}`);
  if (!MODES.includes(mode)) throw new RoleError(`unsupported mode: ${mode}`);
  return READ_ONLY_ROLES.has(role) ? "read-only" : mode;
}

export function toolNamesFor(role, mode) {
  return effectiveMode(role, mode) === "read-only" ? [...READ_TOOLS] : [...READ_TOOLS, ...WRITE_TOOLS];
}

/** Only builders may run approval-gated non-discovery commands; planners and read-only roles may not. */
export function mayRunApprovedCommands(role, mode) {
  return role === "builder" && effectiveMode(role, mode) === "workspace-write";
}

/**
 * `model` is provider-prefixed ("deepseek/deepseek-flash"). The key is reported by
 * variable name and presence only; the value is never read into the result.
 */
export function resolveModelConfig({ provider, model, key_env: keyEnv }, env = process.env) {
  if (typeof model !== "string" || model === "") throw new RoleError("model is required");
  const slash = model.indexOf("/");
  const modelProvider = slash > 0 ? model.slice(0, slash) : provider;
  const modelId = slash > 0 ? model.slice(slash + 1) : model;
  if (!modelProvider || !modelId) throw new RoleError("model must be provider-prefixed or provider must be set");
  if (provider && slash > 0 && provider !== modelProvider) throw new RoleError("provider and model prefix disagree");
  return {
    provider: modelProvider,
    modelId,
    keyEnv: keyEnv ?? null,
    keyPresent: keyEnv ? typeof env[keyEnv] === "string" && env[keyEnv] !== "" : false,
  };
}
