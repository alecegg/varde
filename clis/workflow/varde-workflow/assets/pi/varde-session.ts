// varde-workflow session-start extension for pi. Installed by `varde-workflow hook install --harness
// pi`; do not edit in place. The installer fills in the binary path.
//
// Runs `varde-workflow hook session-start --harness pi` once and appends its stdout to the system
// prompt of top-level sessions. Child sessions (no session file, or a header with `parentSession`)
// get nothing. Fails open: any error injects nothing.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawnSync } from "node:child_process";

const VARDE = "{{VARDE_WORKFLOW_BIN}}";

function sessionContext(cwd: string): string {
  try {
    const r = spawnSync(VARDE, ["hook", "session-start", "--harness", "pi"], {
      cwd, env: process.env, encoding: "utf8", timeout: 20_000,
    });
    if (r.status === 0 && r.stdout?.trim()) return r.stdout.trim();
  } catch {
    // Session context is optional.
  }
  return "";
}

export default function vardeSession(pi: ExtensionAPI) {
  let cached: string | undefined;

  pi.on("before_agent_start", (event, ctx) => {
    try {
      // Sessions change in-process (/new, /resume), so check on every call.
      const sm = ctx.sessionManager;
      if (!sm.getSessionFile() || sm.getHeader()?.parentSession) return undefined;
      cached ??= sessionContext(process.cwd());
      if (!cached || event.systemPrompt.includes(cached)) return undefined;
      return { systemPrompt: `${event.systemPrompt}\n\n${cached}` };
    } catch {
      return undefined;
    }
  });
}
