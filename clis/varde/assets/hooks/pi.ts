// Varde extension for pi. Installed by `varde setup hooks install --harness pi`; do not edit in place.
//
// - before_agent_start: appends `varde hook session-start --harness pi` output to the system prompt of
//   top-level sessions (no session file, or a header with `parentSession`, gets nothing), then
//   appends `varde hook user-prompt-submit --harness pi` unread inbox one-liners on every run.
// - tool_result: checks context usage for every result and captures large results through
//   `varde hook post-tool-use --harness pi`; nested results keep their original values for scripts.
// Everything fails open: if varde is missing or errors, the original result flows through.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawn, spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";

const VARDE = "{{VARDE_BIN}}";
const PRECHECK_BYTES = 2048;
const MAX_RESPONSE_BYTES = 64 * 1024;
const CAPTURE_TIMEOUT_MS = 20_000;

type NewerToolResultFields = {
  parentToolCallId?: unknown;
  structuredContent?: unknown;
};

// VARDE_FEATURE:session-start:start
function sessionContext(cwd: string, sessionId: string): string {
  try {
    const r = spawnSync(VARDE, ["hook", "session-start", "--harness", "pi"], {
      input: JSON.stringify({ session_id: sessionId }),
      cwd, env: process.env, encoding: "utf8", timeout: 20_000,
    });
    if (r.status === 0 && r.stdout?.trim()) return r.stdout.trim();
  } catch {
    // Session context is optional.
  }
  return "";
}
// VARDE_FEATURE:session-start:end

// Unread inbox one-liners change every turn, so this runs uncached on every
// agent run and is never skipped by the systemPrompt.includes guard.
// VARDE_FEATURE:inbox:start
function promptInbox(cwd: string, sessionId: string): string {
  try {
    const r = spawnSync(VARDE, ["hook", "user-prompt-submit", "--harness", "pi"], {
      input: JSON.stringify({ session_id: sessionId }),
      cwd, env: process.env, encoding: "utf8", timeout: 20_000,
    });
    if (r.status === 0 && r.stdout?.trim()) return r.stdout.trim();
  } catch {
    // Unread inbox messages are optional.
  }
  return "";
}
// VARDE_FEATURE:inbox:end

function reportFailure(reason: string, tool: string, bytes: number, cwd: string) {
  try {
    const child = spawn(VARDE, ["event", "--harness", "pi", "--outcome", "failed", "--reason", reason,
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

// VARDE_FEATURE:post-tool-use:start
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
      child = spawn(VARDE, ["hook", "post-tool-use", "--harness", "pi"], {
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
// VARDE_FEATURE:post-tool-use:end

export default function varde(pi: ExtensionAPI) {
  const cached = new Map<string, string>();

  // VARDE_FEATURE:agent-start:start
  pi.on("before_agent_start", (event, ctx) => {
    try {
      // Sessions change in-process (/new, /resume), so check on every call.
      const sm = ctx.sessionManager;
      if (!sm.getSessionFile() || sm.getHeader()?.parentSession) return undefined;
      // VARDE_FEATURE:session-start:start
      const sessionId = sm.getSessionId() ?? "";
      let context = cached.get(sessionId);
      if (context === undefined) {
        context = sessionContext(process.cwd(), sessionId);
        cached.set(sessionId, context);
      }
      const additions: string[] = [];
      if (context && !event.systemPrompt.includes(context)) additions.push(context);
      // VARDE_FEATURE:session-start:end
      // VARDE_FEATURE:inbox:start
      const inbox = promptInbox(process.cwd(), sessionId);
      if (inbox) additions.push(inbox);
      // VARDE_FEATURE:inbox:end
      if (additions.length === 0) return undefined;
      return { systemPrompt: `${event.systemPrompt}\n\n${additions.join("\n\n")}` };
    } catch {
      return undefined;
    }
  });
  // VARDE_FEATURE:agent-start:end

  // VARDE_FEATURE:post-tool-use:start
  pi.on("tool_result", async (event, ctx) => {
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
        const fullOutputPath = isShell && structured !== null && typeof structured === "object" && "full_output_path" in structured
          ? (structured as { full_output_path?: unknown }).full_output_path
          : undefined;
        if (typeof fullOutputPath === "string" && fullOutputPath.length > 0) {
          try {
            response = await readFile(fullOutputPath, "utf8");
          } catch {
            reportFailure("full-output-unavailable", event.toolName, Buffer.byteLength(text, "utf8"), ctx.cwd);
            return;
          }
        } else if (typeof output === "string") {
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

    let sessionId = "";
    try {
      sessionId = ctx.sessionManager.getSessionId() ?? "";
    } catch {
      // A missing session ID is safe; capture uses an empty value.
    }

    let payload: string;
    try {
      const payloadValue: Record<string, unknown> = {
        harness: "pi",
        session_id: sessionId,
        tool_name: event.toolName,
        tool_input: event.input ?? {},
      };
      let hasContextSample = false;
      // Child pi processes (no session file, or a parentSession header) must not be nudged.
      let topLevel = false;
      try {
        const sm = ctx.sessionManager;
        topLevel = Boolean(sm.getSessionFile()) && !sm.getHeader()?.parentSession;
      } catch {
        // Unknown session kind: send no usage.
      }
      try {
        if (!topLevel) throw new Error("child session");
        const contextUsage = ctx.getContextUsage;
        const model = ctx.model;
        if (typeof contextUsage === "function" && model && typeof model.contextWindow === "number") {
          const usage = contextUsage.call(ctx);
          if (usage && typeof usage.tokens === "number" && Number.isFinite(usage.tokens) && usage.tokens >= 0) {
            payloadValue.context_usage = {
              usage: { input: usage.tokens, output: 0, cacheRead: 0, cacheWrite: 0 },
              model: { id: model.id, contextWindow: model.contextWindow },
            };
            hasContextSample = true;
          }
        }
      } catch {
        // An unavailable usage sample must not block capture.
      }
      if (bytes >= PRECHECK_BYTES) payloadValue.tool_response = response;
      if (topLevel && !hasContextSample) {
        try {
          const sessionFile = ctx.sessionManager.getSessionFile();
          if (typeof sessionFile === "string" && sessionFile) payloadValue.session_file = sessionFile;
        } catch {
          // Session-file fallback is optional.
        }
      }
      const serialized = JSON.stringify(payloadValue);
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
        const nudge = out?.hookSpecificOutput?.additionalContext ?? out?.additionalContext;
        if (typeof updated !== "string" && typeof nudge !== "string") {
          reportFailure("missing-update", event.toolName, bytes, ctx.cwd);
          return undefined;
        }
        return { updated, nudge };
      } catch {
        reportFailure("invalid-response", event.toolName, bytes, ctx.cwd);
        return undefined;
      }
    });

    return result.then((responseOutput) => {
      if (!responseOutput) return undefined;
      const { updated, nudge } = responseOutput;
      // Nested results are consumed by scripts; keep their values unchanged.
      if (nested) return undefined;
      const nonText = blocks.filter((b) => b.type !== "text");
      const original = text;
      const replacement = typeof updated === "string" ? updated : original;
      const combined = typeof nudge === "string" && nudge
        ? `${replacement}${replacement ? "\n\n" : ""}${nudge}`
        : replacement;
      if (typeof updated !== "string" && !nudge) return undefined;
      return { content: [{ type: "text" as const, text: combined }, ...nonText] };
    });
  });
  // VARDE_FEATURE:post-tool-use:end
}
