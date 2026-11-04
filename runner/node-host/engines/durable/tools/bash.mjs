// The bash tool: discovery commands run directly; anything else is refused
// (read-only roles) or goes through the approval gate (builder).
import { realpath } from "node:fs/promises";
import { resolve } from "node:path";
import { mayRunApprovedCommands } from "../roles.mjs";
import { classifyBash } from "./bash-policy.mjs";
import { isInside, ToolRefusal } from "./paths.mjs";
import { runShell } from "./shell.mjs";

const text = (value) => ({ output: [{ type: "text", text: value }] });
const GLOB = /[*?[]/;

// A relative path argument may still name a link that leads outside the workspace.
async function assertArgsConfined(cwd, segments) {
  const root = await realpath(cwd);
  for (const [, ...args] of segments) {
    for (const arg of args.filter((a) => !a.startsWith("-") && !GLOB.test(a))) {
      const real = await realpath(resolve(cwd, arg)).catch(() => null);
      if (real && !isInside(root, real)) throw new ToolRefusal(`path escapes the workspace through a link: ${arg}`);
    }
  }
}

/**
 * `approvals.gateAndEffect({key, tool, summary, input}, effect)` is d3's helper. It resolves
 * `{status: "executed", value}`, `{status: "denied"}` or `{status: "expired"}`; the effect runs
 * once per key, and a replay returns the stored value.
 */
export function bashExecute({ cwd, role, mode, sessionEnv, approvals, track }) {
  return async ({ command, timeout }, api) => {
    const verdict = classifyBash(command);
    const run = () => runShell(command, { cwd, sessionEnv, timeoutS: timeout, track });
    if (verdict.kind === "discovery") {
      await assertArgsConfined(cwd, verdict.segments);
      return text(await run());
    }
    if (!mayRunApprovedCommands(role, mode)) {
      throw new ToolRefusal(`${verdict.reason}; this role may only run read-only discovery commands`);
    }
    if (typeof approvals?.gateAndEffect !== "function") throw new ToolRefusal("approval bridge is not available");
    const key = `${api.conversationId}:${api.callId}`;
    const outcome = await approvals.gateAndEffect({ key, tool: "bash", summary: `Run: ${command}`, input: { command } }, run);
    if (outcome.status !== "executed") throw new ToolRefusal(`command was ${outcome.status}`);
    return text(outcome.value);
  };
}
