// varde-workflow session-start plugin for opencode. Installed by `varde-workflow hook install --harness
// opencode`; do not edit in place. The installer keeps only the half matching the installed opencode
// (1.x hook-map plugin, or 2.x setup plugin) and fills in the binary path.
//
// Runs `varde-workflow hook session-start --harness opencode` once and appends its stdout to the
// system prompt of main sessions. Child sessions (those with a parentID) are skipped in both halves.
// Fails open: any error injects nothing, and a failed or slow session lookup (over 2s) injects.
//
// opencode 1.x calls *every* export as a plugin factory, so each half exports exactly one thing.
//@@v1
import type { Plugin } from "@opencode-ai/plugin";
import { spawnSync } from "node:child_process";

const VARDE = "{{VARDE_WORKFLOW_BIN}}";

function sessionContext(cwd: string): string {
  try {
    const r = spawnSync(VARDE, ["hook", "session-start", "--harness", "opencode"], {
      cwd, env: process.env, encoding: "utf8", timeout: 20_000,
    });
    if (r.status === 0 && r.stdout?.trim()) return r.stdout.trim();
  } catch {
    // Session context is optional.
  }
  return "";
}

const LOOKUP_TIMEOUT_MS = 2_000;

function withTimeout<T>(work: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("lookup timed out")), LOOKUP_TIMEOUT_MS);
  });
  return Promise.race([work, timeout]).finally(() => clearTimeout(timer));
}

export const VardeSessionPlugin: Plugin = async ({ client, directory, worktree }) => {
  const cwd = directory || worktree || process.cwd();
  let cached: string | undefined;
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
    "experimental.chat.system.transform": async (input, output) => {
      try {
        if (input.sessionID && (await childSession(input.sessionID))) return;
        cached ??= sessionContext(cwd);
        if (cached && !output.system.includes(cached)) output.system.push(cached);
      } catch {
        // Session context is optional.
      }
    },
  };
};
//@@v2
import type { Plugin } from "@opencode/plugin";
import { spawnSync } from "node:child_process";

const VARDE = "{{VARDE_WORKFLOW_BIN}}";

function sessionContext(cwd: string): string {
  try {
    const r = spawnSync(VARDE, ["hook", "session-start", "--harness", "opencode"], {
      cwd, env: process.env, encoding: "utf8", timeout: 20_000,
    });
    if (r.status === 0 && r.stdout?.trim()) return r.stdout.trim();
  } catch {
    // Session context is optional.
  }
  return "";
}

const LOOKUP_TIMEOUT_MS = 2_000;

function withTimeout<T>(work: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("lookup timed out")), LOOKUP_TIMEOUT_MS);
  });
  return Promise.race([work, timeout]).finally(() => clearTimeout(timer));
}

export const VardeSessionPlugin: Plugin.Plugin = {
  id: "varde-session",

  async setup(ctx: Plugin.Context) {
    const cwd = ctx.location?.directory ?? process.cwd();
    let cached: string | undefined;
    // One plugin instance serves parent and child sessions, and the hook runs on every LLM
    // request, so look each session up once.
    const isChild = new Map<string, boolean>();

    async function childSession(event: { sessionID: Parameters<typeof ctx.session.get>[0]["sessionID"] }): Promise<boolean> {
      const known = isChild.get(event.sessionID);
      if (known !== undefined) return known;
      try {
        const info = await withTimeout(ctx.session.get({ sessionID: event.sessionID }));
        const child = Boolean(info.parentID);
        isChild.set(event.sessionID, child);
        return child;
      } catch {
        return false;
      }
    }

    await ctx.session.hook("context", async (event) => {
      try {
        if (await childSession(event)) return;
        cached ??= sessionContext(cwd);
        if (cached && !event.system.some((p) => p.text === cached)) {
          event.system.push({ type: "text", text: cached });
        }
      } catch {
        // Session context is optional.
      }
    });
  },
};

export default VardeSessionPlugin;
