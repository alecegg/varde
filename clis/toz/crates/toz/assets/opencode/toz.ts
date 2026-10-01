// toz (tool-output-zone) plugin for opencode ≥ 2.0. Installed by `varde-toz install opencode`; do not
// edit in place.
//
// - session "context" hook: appends the toz usage note to the system prompt.
// - shell "create.before" hook: sets VARDE_TOZ_SESSION so `varde-toz stats --session` works.
// - tool "execute.after" hook: hands large text results to
//   `varde-toz capture --hook --harness opencode` and swaps in the preview it returns. Fails open.

// Type-only import: erased at load time, so the plugin needs no node_modules next to it.
import type { Plugin } from "@opencode/plugin";
import { spawnSync } from "node:child_process";

const TOZ = "{{TOZ_BIN}}";
const NOTE = "{{TOZ_NOTE_JSON}}";
const NOTE_MARKER = "varde-toz (tool-output-zone) is active";
const PRECHECK_BYTES = 2048;

// varde-ignore-next-line duplicate-code-clone -- packaged plugin and harness template intentionally mirror each other
function usageNote(cwd: string): string {
  try {
    const r = spawnSync(TOZ, ["note", "--harness", "opencode"], {
      cwd, env: process.env,
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
      cwd, env: process.env, timeout: 1_000, stdio: "ignore",
    });
  } catch {
    // Failure reporting is best effort.
  }
}

type Content = { type: "text"; text: string } | { type: "file"; uri: string; mime: string; name?: string };

function resultText(result: { output?: unknown; content?: unknown }): string | undefined {
  if (typeof result.output === "string") return result.output;
  if (typeof result.content === "string") return result.content;
  if (Array.isArray(result.content)) {
    const texts = (result.content as Array<{ type?: string; text?: string }>)
      .filter((b) => b && b.type === "text" && typeof b.text === "string")
      .map((b) => b.text as string);
    if (texts.length > 0) return texts.join("\n");
  }
  return undefined;
}

export const TozPlugin: Plugin.Plugin = {
  id: "varde-toz",

  async setup(ctx: Plugin.Context) {
    const cwd = ctx.location?.directory ?? process.cwd();

    await ctx.session.hook("context", async (event) => {
      if (event.system.some((p) => typeof p.text === "string" && p.text.includes(NOTE_MARKER))) return;
      event.system.push({ type: "text", text: usageNote(cwd) });
    });

    await ctx.shell.hook("create.before", async (event) => {
      event.env.VARDE_TOZ_SESSION = event.env.VARDE_TOZ_SESSION || event.env.TOZ_SESSION || "opencode";
    });

    await ctx.tool.hook("execute.after", async (event) => {
      if (event.status !== "completed") return;
      const text = resultText(event.result);
      if (!text || text.length < PRECHECK_BYTES) return;
      const payload = JSON.stringify({
        harness: "opencode",
        session_id: event.sessionID,
        tool_name: event.tool,
        tool_input: event.input ?? {},
        tool_response: text,
      });
      const fail = (reason: string) => reportFailure(reason, event.tool, Buffer.byteLength(text), cwd);
      let r;
      try {
        r = spawnSync(TOZ, ["capture", "--hook", "--harness", "opencode"], {
          input: payload,
          encoding: "utf8",
          timeout: 20_000,
          cwd,
          env: { ...process.env, VARDE_TOZ_SESSION: `opencode-${event.sessionID}` },
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
        const rest: Content[] = Array.isArray(event.result.content)
          ? (event.result.content as readonly Content[]).filter((b) => b.type !== "text")
          : [];
        const content: Content[] = [{ type: "text", text: updated }, ...rest];
        event.result = {
          ...event.result,
          output: typeof event.result.output === "string" ? updated : event.result.output,
          content,
        };
      } catch { fail("invalid-response"); }
    });
  },
};

export default TozPlugin;
