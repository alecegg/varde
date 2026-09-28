// toz (tool-output-zone) extension for pi. Installed by `varde-toz install pi`; do not edit in place.
//
// - before_agent_start: appends the toz usage note to the system prompt.
// - tool_result: hands large text results to `varde-toz capture --hook --harness pi`, which stores
//   them and returns a preview; the result content is replaced with that preview.
// Everything fails open: if toz is missing or errors, the original result flows through.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawnSync } from "node:child_process";

const TOZ = "{{TOZ_BIN}}";
const NOTE = "{{TOZ_NOTE_JSON}}";
const FALLBACK = process.env.VARDE_TOZ_FALLBACK_DIR || process.env.TOZ_FALLBACK_DIR || "{{TOZ_FALLBACK_JSON}}";
// Don't spawn a process for small results; toz applies the real per-tool threshold.
const PRECHECK_BYTES = 2048;

function usageNote(cwd: string): string {
  try {
    const r = spawnSync(TOZ, ["note", "--harness", "pi"], {
      cwd, env: { ...process.env, VARDE_TOZ_FALLBACK_DIR: FALLBACK },
      encoding: "utf8", timeout: 1_000,
    });
    if (r.status === 0 && r.stdout?.trim()) return r.stdout.trim();
  } catch {
    // The note command is optional; use the fallback message below.
  }
  return `${NOTE}\nToz startup check failed. Run \`varde-toz doctor --json\` and report the failure.`;
}

function reportFailure(reason: string, tool: string, bytes: number, cwd: string) {
  try {
    spawnSync(TOZ, ["event", "--harness", "pi", "--outcome", "failed", "--reason", reason,
      "--tool", tool, "--bytes", String(bytes)], {
      cwd, env: { ...process.env, VARDE_TOZ_FALLBACK_DIR: FALLBACK }, timeout: 1_000, stdio: "ignore",
    });
  } catch {
    // Failure reporting is best effort.
  }
}

export default function toz(pi: ExtensionAPI) {
  pi.on("before_agent_start", (event) => ({
    systemPrompt: `${event.systemPrompt}\n\n${usageNote(process.cwd())}`,
  }));

  pi.on("tool_result", (event, ctx) => {
    if (event.isError) return;
    const blocks = event.content;
    const text = blocks
      .filter((b) => b.type === "text")
      .map((b) => (b as { text: string }).text)
      .join("\n");
    if (text.length < PRECHECK_BYTES) return;

    let sessionId = "";
    try {
      sessionId = ctx.sessionManager.getSessionId() ?? "";
    } catch {
      // A missing session ID is safe; capture uses an empty value.
    }
    const payload = JSON.stringify({
      harness: "pi",
      session_id: sessionId,
      tool_name: event.toolName,
      tool_input: event.input ?? {},
      tool_response: text,
    });
    const fail = (reason: string) => reportFailure(reason, event.toolName, Buffer.byteLength(text), ctx.cwd);
    let r;
    try {
      r = spawnSync(TOZ, ["capture", "--hook", "--harness", "pi"], {
        input: payload,
        encoding: "utf8",
        timeout: 20_000,
        cwd: ctx.cwd,
        env: { ...process.env, VARDE_TOZ_FALLBACK_DIR: FALLBACK, VARDE_TOZ_SESSION: sessionId ? `pi-${sessionId}` : "" },
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
      const nonText = blocks.filter((b) => b.type !== "text");
      return { content: [{ type: "text" as const, text: updated }, ...nonText] };
    } catch {
      fail("invalid-response");
      return;
    }
  });
}
