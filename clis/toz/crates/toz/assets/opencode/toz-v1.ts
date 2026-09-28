// toz (tool-output-zone) plugin for opencode 1.x. Installed by `varde-toz install opencode` when the
// installed opencode predates the 2.0 plugin API; do not edit in place.
//
// - "experimental.chat.system.transform": appends the toz usage note to the system prompt.
// - "shell.env": sets VARDE_TOZ_SESSION so `varde-toz stats --session` works.
// - "tool.execute.after": hands large text results to `varde-toz capture --hook --harness opencode`
//   and swaps in the preview it returns. Fails open.
//
// opencode 1.x calls *every* export as a plugin factory, so this file exports exactly one thing.

// Type-only import: erased at load time, so the plugin needs no node_modules next to it.
import type { Plugin } from "@opencode-ai/plugin";
import { spawnSync } from "node:child_process";

const TOZ = "{{TOZ_BIN}}";
const NOTE = "{{TOZ_NOTE_JSON}}";
const FALLBACK = process.env.VARDE_TOZ_FALLBACK_DIR || process.env.TOZ_FALLBACK_DIR || "{{TOZ_FALLBACK_JSON}}";
const NOTE_MARKER = "varde-toz (tool-output-zone) is active";
const PRECHECK_BYTES = 2048;

// varde-ignore-next-line duplicate-code-clone -- packaged plugin and harness template intentionally mirror each other
function usageNote(cwd: string): string {
  try {
    const r = spawnSync(TOZ, ["note", "--harness", "opencode"], {
      cwd, env: { ...process.env, VARDE_TOZ_FALLBACK_DIR: FALLBACK },
      encoding: "utf8", timeout: 1_000,
    });
    if (r.status === 0 && r.stdout?.trim()) return r.stdout.trim();
  } catch {
    // The note command is optional; use the fallback message below.
  }
  return `${NOTE}\nToz startup check failed. Run \`varde-toz doctor --json\` and report the failure.`;
}

// varde-ignore-next-line duplicate-code-clone -- packaged plugin and harness template intentionally mirror each other
function reportFailure(reason: string, tool: string, bytes: number, cwd: string) {
  try {
    spawnSync(TOZ, ["event", "--harness", "opencode", "--outcome", "failed", "--reason", reason,
      "--tool", tool, "--bytes", String(bytes)], {
      cwd, env: { ...process.env, VARDE_TOZ_FALLBACK_DIR: FALLBACK }, timeout: 1_000, stdio: "ignore",
    });
  } catch {
    // Failure reporting is best effort.
  }
}

export const TozPlugin: Plugin = async ({ directory, worktree }) => {
  const cwd = directory || worktree || process.cwd();

  return {
    "experimental.chat.system.transform": async (_input, output) => {
      if (output.system.some((p) => typeof p === "string" && p.includes(NOTE_MARKER))) return;
      output.system.push(usageNote(cwd));
    },

    "shell.env": async (_input, output) => {
      output.env.VARDE_TOZ_FALLBACK_DIR = output.env.VARDE_TOZ_FALLBACK_DIR || output.env.TOZ_FALLBACK_DIR || FALLBACK;
      output.env.VARDE_TOZ_SESSION = output.env.VARDE_TOZ_SESSION || output.env.TOZ_SESSION || "opencode";
    },

    "tool.execute.after": async (input, output) => {
      const text = output.output;
      if (typeof text !== "string" || text.length < PRECHECK_BYTES) return;
      const payload = JSON.stringify({
        harness: "opencode",
        session_id: input.sessionID,
        tool_name: input.tool,
        tool_input: input.args ?? {},
        tool_response: text,
      });
      const fail = (reason: string) => reportFailure(reason, input.tool, Buffer.byteLength(text), cwd);
      let r;
      try {
        r = spawnSync(TOZ, ["capture", "--hook", "--harness", "opencode"], {
          input: payload,
          encoding: "utf8",
          timeout: 20_000,
          cwd,
          env: { ...process.env, VARDE_TOZ_FALLBACK_DIR: FALLBACK, VARDE_TOZ_SESSION: `opencode-${input.sessionID}` },
        });
      } catch {
        fail("spawn");
        return;
      }
      if (r.error) { fail((r.error as NodeJS.ErrnoException).code === "ETIMEDOUT" ? "timeout" : "spawn"); return; }
      if (r.status !== 0) { fail("exit"); return; }
      if (!r.stdout || !r.stdout.trim()) return;
      try {
        const out = JSON.parse(r.stdout);
        const updated = out?.hookSpecificOutput?.updatedToolOutput;
        if (typeof updated !== "string") { fail("missing-update"); return; }
        output.output = updated;
      } catch { fail("invalid-response"); }
    },
  };
};
