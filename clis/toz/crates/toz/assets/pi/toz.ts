// toz (tool-output-zone) extension for pi. Installed by `varde-toz install pi`; do not edit in place.
//
// - before_agent_start: appends the toz usage note to the system prompt.
// - tool_result: captures large results; direct/final results receive a preview while nested
//   results keep their original values for the calling codemode script.
// Everything fails open: if toz is missing or errors, the original result flows through.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawn, spawnSync } from "node:child_process";

const TOZ = "{{TOZ_BIN}}";
const NOTE = "{{TOZ_NOTE_JSON}}";
// Don't spawn a process for small results; toz applies the real per-tool threshold.
const PRECHECK_BYTES = 2048;
const MAX_RESPONSE_BYTES = 64 * 1024;
const CAPTURE_TIMEOUT_MS = 20_000;

type NewerToolResultFields = {
  parentToolCallId?: unknown;
  structuredContent?: unknown;
};

function usageNote(cwd: string): string {
  try {
    const r = spawnSync(TOZ, ["note", "--harness", "pi"], {
      cwd, env: process.env,
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
    const child = spawn(TOZ, ["event", "--harness", "pi", "--outcome", "failed", "--reason", reason,
      "--tool", tool, "--bytes", String(bytes)], {
      cwd, env: process.env, stdio: "ignore",
    });
    let closed = false;
    const timeout = setTimeout(() => {
      if (!closed) child.kill("SIGKILL");
    }, 1_000);
    child.once("error", () => {
      closed = true;
      clearTimeout(timeout);
    });
    child.once("close", () => {
      closed = true;
      clearTimeout(timeout);
    });
  } catch {
    // Failure reporting is best effort.
  }
}

function capture(payload: string, sessionId: string, tool: string, bytes: number, cwd: string): Promise<string | undefined> {
  return new Promise((resolve) => {
    let child: ReturnType<typeof spawn> | undefined;
    let timeout: NodeJS.Timeout | undefined;
    let settled = false;
    let responseBytes = 0;
    let stdoutBytes = 0;
    const stdout: Buffer[] = [];

    const finish = (result: string | undefined, reason?: string, kill = false) => {
      if (settled) return;
      settled = true;
      if (timeout) clearTimeout(timeout);
      if (kill) {
        try { child?.kill("SIGKILL"); } catch { /* best effort */ }
      }
      if (reason) reportFailure(reason, tool, bytes, cwd);
      resolve(result);
    };

    try {
      child = spawn(TOZ, ["capture", "--hook", "--harness", "pi"], {
        cwd,
        env: { ...process.env, VARDE_TOZ_SESSION: sessionId ? `pi-${sessionId}` : "" },
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch {
      finish(undefined, "spawn");
      return;
    }

    child.once("error", () => finish(undefined, "spawn"));
    child.once("close", (code) => {
      if (settled) return;
      if (code !== 0) {
        finish(undefined, "exit");
        return;
      }
      finish(Buffer.concat(stdout, stdoutBytes).toString("utf8"));
    });

    const countOutput = (chunk: Buffer, isStdout: boolean) => {
      if (settled) return;
      responseBytes += chunk.length;
      if (responseBytes > MAX_RESPONSE_BYTES) {
        finish(undefined, "output-limit", true);
        return;
      }
      if (isStdout) {
        stdout.push(chunk);
        stdoutBytes += chunk.length;
      }
    };

    child.stdout?.on("data", (chunk: Buffer | string) => countOutput(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk), true));
    child.stderr?.on("data", (chunk: Buffer | string) => countOutput(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk), false));
    child.stdout?.once("error", () => finish(undefined, "spawn", true));
    child.stderr?.once("error", () => finish(undefined, "spawn", true));
    child.stdin?.on("error", () => {});
    timeout = setTimeout(() => finish(undefined, "timeout", true), CAPTURE_TIMEOUT_MS);
    try {
      child.stdin?.end(payload);
    } catch {
      finish(undefined, "spawn", true);
    }
  });
}

export default function toz(pi: ExtensionAPI) {
  pi.on("before_agent_start", (event) => ({
    systemPrompt: `${event.systemPrompt}\n\n${usageNote(process.cwd())}`,
  }));

  pi.on("tool_result", (event, ctx) => {
    if (event.isError) return;

    const fields = event as typeof event & NewerToolResultFields;
    const nested = typeof fields.parentToolCallId === "string" && fields.parentToolCallId.length > 0;
    const blocks = event.content;
    const text = blocks
      .filter((b) => b.type === "text")
      .map((b) => (b as { text: string }).text)
      .join("\n");

    let response = text;
    if (nested) {
      const structured = fields.structuredContent;
      if (structured !== undefined) {
        const isShell = event.toolName === "bash" || event.toolName === "powershell";
        const output = isShell && structured !== null && typeof structured === "object" && "output" in structured
          ? (structured as { output?: unknown }).output
          : undefined;
        if (typeof output === "string") {
          response = output;
        } else {
          try {
            const serialized = JSON.stringify(structured);
            if (typeof serialized !== "string") {
              reportFailure("serialization", event.toolName, Buffer.byteLength(text, "utf8"), ctx.cwd);
              return;
            }
            response = serialized;
          } catch {
            reportFailure("serialization", event.toolName, Buffer.byteLength(text, "utf8"), ctx.cwd);
            return;
          }
        }
      }
    }

    const bytes = Buffer.byteLength(response, "utf8");
    if (bytes < PRECHECK_BYTES) return;

    let sessionId = "";
    try {
      sessionId = ctx.sessionManager.getSessionId() ?? "";
    } catch {
      // A missing session ID is safe; capture uses an empty value.
    }

    let payload: string;
    try {
      const serialized = JSON.stringify({
        harness: "pi",
        session_id: sessionId,
        tool_name: event.toolName,
        tool_input: event.input ?? {},
        tool_response: response,
      });
      if (typeof serialized !== "string") {
        reportFailure("serialization", event.toolName, bytes, ctx.cwd);
        return;
      }
      payload = serialized;
    } catch {
      reportFailure("serialization", event.toolName, bytes, ctx.cwd);
      return;
    }

    const result = capture(payload, sessionId, event.toolName, bytes, ctx.cwd).then((stdout) => {
      if (!stdout || !stdout.trim()) return undefined;
      try {
        const out = JSON.parse(stdout);
        const updated = out?.hookSpecificOutput?.updatedToolOutput;
        if (typeof updated !== "string") {
          reportFailure("missing-update", event.toolName, bytes, ctx.cwd);
          return undefined;
        }
        return updated;
      } catch {
        reportFailure("invalid-response", event.toolName, bytes, ctx.cwd);
        return undefined;
      }
    });

    if (nested) return result.then(() => undefined);
    return result.then((updated) => {
      if (typeof updated !== "string") return undefined;
      const nonText = blocks.filter((b) => b.type !== "text");
      return { content: [{ type: "text" as const, text: updated }, ...nonText] };
    });
  });
}
