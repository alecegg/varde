// Pure validation and SDK option building for session.start.
import path from "node:path";

const MODE_MAP = {
  "read-only": "plan",
  "workspace-write": "acceptEdits",
  auto: "acceptEdits",
  "full-access": "bypassPermissions",
};
const EFFORTS = new Set(["low", "medium", "high", "xhigh", "max"]);
export const REMOVED_ENV_VARS = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"];

export class ContractError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

export function scrubbedEnv(source) {
  const env = {};
  for (const [key, value] of Object.entries(source)) {
    if (typeof value === "string" && !REMOVED_ENV_VARS.includes(key)) env[key] = value;
  }
  return env;
}

export function buildQueryOptions(params, base = process.env) {
  const { cwd, model, effort, mode, env, resume_handle: resumeHandle } = params;
  if (typeof cwd !== "string" || !path.isAbsolute(cwd)) {
    throw new ContractError("invalid_params", "cwd must be an absolute path");
  }
  if (typeof model !== "string" || model === "") {
    throw new ContractError("invalid_params", "model must be a non-empty string");
  }
  const permissionMode = MODE_MAP[mode];
  if (!permissionMode) throw new ContractError("invalid_mode", `unsupported runner mode: ${mode}`);
  if (effort != null && !EFFORTS.has(effort)) {
    throw new ContractError("invalid_effort", `unsupported effort: ${effort}`);
  }
  if (resumeHandle != null && (typeof resumeHandle !== "string" || resumeHandle === "")) {
    throw new ContractError("invalid_params", "resume_handle must be a non-empty string");
  }
  if (env != null && (typeof env !== "object" || Array.isArray(env))) {
    throw new ContractError("invalid_params", "env must be an object");
  }
  const options = {
    cwd,
    model,
    permissionMode,
    env: scrubbedEnv(env ?? base),
  };
  if (effort != null) options.effort = effort;
  if (permissionMode === "bypassPermissions") options.allowDangerouslySkipPermissions = true;
  if (resumeHandle != null) options.resume = resumeHandle;
  return options;
}
