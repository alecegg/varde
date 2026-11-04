// Varde plugin for opencode 1.x. Installed by `varde setup hooks install --harness opencode` when the
// installed opencode predates the 2.0 plugin API; do not edit in place.
//
// - "experimental.chat.system.transform": appends `varde hook session-start --harness opencode` output
//   to the system prompt of main sessions (child sessions with a parentID are skipped).
// - "shell.env": sets VARDE_TOZ_SESSION so captures group by session.
// - "tool.execute.after": sends context usage for every completed result and hands large text results
//   to `varde hook post-tool-use --harness opencode` for capture. Fails open.
//
// opencode 1.x calls *every* export as a plugin factory, so this file exports exactly one thing.

// Type-only import: erased at load time, so the plugin needs no node_modules next to it.
import type { Plugin } from "@opencode-ai/plugin";
import { spawnSync } from "node:child_process";

const VARDE = "{{VARDE_BIN}}";
const PRECHECK_BYTES = 2048;
const MAX_USAGE_AGE_MS = 5 * 60_000;

// VARDE_FEATURE:session-start:start
function sessionContext(cwd: string, sessionID: string): string {
  try {
    const r = spawnSync(VARDE, ["hook", "session-start", "--harness", "opencode"], {
      input: JSON.stringify({ session_id: sessionID }),
      cwd, env: process.env, encoding: "utf8", timeout: 20_000,
    });
    if (r.status === 0 && r.stdout?.trim()) return r.stdout.trim();
  } catch {
    // Session context is optional.
  }
  return "";
}
// VARDE_FEATURE:session-start:end

function usageSample(value: unknown): unknown {
  const response = value as { data?: unknown } | undefined;
  const rows = Array.isArray(value)
    ? value
    : Array.isArray(response?.data)
    ? response.data
    : Array.isArray((response?.data as { data?: unknown[] } | undefined)?.data)
      ? (response?.data as { data: unknown[] }).data
      : [];
  const latest = [...rows].reverse().map((row) => {
    const item = row as { info?: Record<string, unknown> } & Record<string, unknown>;
    return item.info ?? item;
  }).find((info) => info.role === "assistant" || info.type === "assistant");
  if (!latest) return undefined;
  const time = latest.time as { created?: unknown; completed?: unknown } | undefined;
  const timestamp = typeof time?.completed === "number" ? time.completed : time?.created;
  if (typeof timestamp !== "number" || Date.now() - timestamp > MAX_USAGE_AGE_MS || timestamp > Date.now() + 5_000) {
    return undefined;
  }
  const tokens = latest.tokens as {
    input?: unknown; output?: unknown; reasoning?: unknown; cache?: { read?: unknown; write?: unknown };
  } | undefined;
  if (!tokens || ![tokens.input, tokens.output, tokens.reasoning, tokens.cache?.read, tokens.cache?.write]
    .every((count) => typeof count === "number" && Number.isFinite(count) && count >= 0)) return undefined;
  const modelID = typeof latest.modelID === "string"
    ? latest.modelID
    : typeof (latest.model as { id?: unknown } | undefined)?.id === "string"
      ? (latest.model as { id: string }).id
      : undefined;
  if (!modelID) return undefined;
  return {
    usage: {
      input: tokens.input,
      output: tokens.output,
      reasoning: tokens.reasoning,
      cacheRead: tokens.cache?.read,
      cacheWrite: tokens.cache?.write,
    },
    model: { id: modelID },
  };
}

const LOOKUP_TIMEOUT_MS = 2_000;

function withTimeout<T>(work: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("lookup timed out")), LOOKUP_TIMEOUT_MS);
  });
  return Promise.race([work, timeout]).finally(() => clearTimeout(timer));
}

function reportFailure(reason: string, tool: string, bytes: number, cwd: string) {
  try {
    spawnSync(VARDE, ["event", "--harness", "opencode", "--outcome", "failed", "--reason", reason,
      "--tool", tool, "--bytes", String(bytes)], {
      cwd, env: process.env, timeout: 1_000, stdio: "ignore",
    });
  } catch {
    // Failure reporting is best effort.
  }
}

export const VardePlugin: Plugin = async ({ client, directory, worktree }) => {
  const cwd = directory || worktree || process.cwd();
  const cached = new Map<string, string>();
  // One plugin instance serves parent and child sessions, and the transform runs on every LLM
  // request, so look each session up once.
  const isChild = new Map<string, boolean>();

  async function childSession(sessionID: string): Promise<boolean> {
    const known = isChild.get(sessionID);
    if (known !== undefined) return known;
    try {
      const res = await withTimeout(client.session.get({ path: { id: sessionID } }));
      if (res.error || !res.data) return false;
      const child = Boolean(res.data.parentID);
      isChild.set(sessionID, child);
      return child;
    } catch {
      return false;
    }
  }

  return {
    // VARDE_FEATURE:session-start:start
    "experimental.chat.system.transform": async (input, output) => {
      try {
        if (input.sessionID && (await childSession(input.sessionID))) return;
        const sessionID = input.sessionID ?? "";
        let context = cached.get(sessionID);
        if (context === undefined) {
          context = sessionContext(cwd, sessionID);
          cached.set(sessionID, context);
        }
        if (context && !output.system.includes(context)) output.system.push(context);
      } catch {
        // Session context is optional.
      }
    },
    // VARDE_FEATURE:session-start:end

    // VARDE_FEATURE:toz:start
    "shell.env": async (_input, output) => {
      output.env.VARDE_TOZ_SESSION = output.env.VARDE_TOZ_SESSION || output.env.TOZ_SESSION || "opencode";
    },
    // VARDE_FEATURE:toz:end

    // VARDE_FEATURE:post-tool-use:start
    "tool.execute.after": async (input, output) => {
      const text = typeof output.output === "string" ? output.output : "";
      let contextUsage: unknown;
      try {
        const result = await withTimeout(client.session.messages({
          path: { id: input.sessionID },
          query: { directory: cwd, limit: 100 },
        }));
        if (!result.error) contextUsage = usageSample(result.data);
      } catch {
        // A missing or stale usage sample skips session-notes nudges.
      }
      const payloadValue: Record<string, unknown> = {
        harness: "opencode",
        session_id: input.sessionID,
        tool_name: input.tool,
        tool_input: input.args ?? {},
      };
      if (Buffer.byteLength(text, "utf8") >= PRECHECK_BYTES) payloadValue.tool_response = text;
      if (contextUsage) payloadValue.context_usage = contextUsage;
      const payload = JSON.stringify(payloadValue);
      const fail = (reason: string) => reportFailure(reason, input.tool, Buffer.byteLength(text), cwd);
      let r;
      try {
        r = spawnSync(VARDE, ["hook", "post-tool-use", "--harness", "opencode"], {
          input: payload,
          encoding: "utf8",
          timeout: 20_000,
          cwd,
          env: { ...process.env, VARDE_TOZ_SESSION: `opencode-${input.sessionID}` },
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
        const nudge = out?.hookSpecificOutput?.additionalContext ?? out?.additionalContext;
        if (typeof updated !== "string" && typeof nudge !== "string") { fail("missing-update"); return; }
        const replacement = typeof updated === "string" ? updated : text;
        output.output = typeof nudge === "string" && nudge
          ? `${replacement}${replacement ? "\n\n" : ""}${nudge}`
          : replacement;
      } catch { fail("invalid-response"); }
    },
    // VARDE_FEATURE:post-tool-use:end
  };
};
