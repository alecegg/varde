// Bridges the SDK canUseTool callback to host events and back. Every request
// resolves exactly once: approve, deny, or expired (abort, interrupt, stop,
// session end). Nothing is replayed; a callback that is gone stays gone.
import { ContractError } from "./options.mjs";

export const EXPIRED_MESSAGE = "Permission request expired; the tool call was not run";

export function createPermissionBridge() {
  const pending = new Map(); // session id -> Map(request id -> entry)

  const forSession = (session) => {
    let map = pending.get(session.id);
    if (!map) pending.set(session.id, (map = new Map()));
    return map;
  };

  function settle(session, requestId, decision, result) {
    const map = pending.get(session.id);
    const entry = map?.get(requestId);
    if (!entry) return false;
    map.delete(requestId);
    entry.signal?.removeEventListener("abort", entry.onAbort);
    entry.resolve(result);
    session.emit("permission_resolved", { request_id: requestId, decision });
    return true;
  }

  const expire = (session, requestId) =>
    settle(session, requestId, "expired", { behavior: "deny", message: EXPIRED_MESSAGE });

  return {
    canUseTool(session) {
      return (toolName, input, options = {}) =>
        new Promise((resolve) => {
          const requestId = options.toolUseID ?? `perm-${session.id}-${pending.get(session.id)?.size ?? 0}`;
          const entry = { resolve, input, signal: options.signal, onAbort: () => expire(session, requestId) };
          forSession(session).set(requestId, entry);
          if (options.signal?.aborted) {
            expire(session, requestId);
            return;
          }
          options.signal?.addEventListener("abort", entry.onAbort, { once: true });
          session.emit("permission_requested", {
            request_id: requestId,
            tool_use_id: options.toolUseID ?? null,
            kind: "tool",
            tool: toolName,
            summary: options.title ?? `Permission requested for ${toolName}`,
            input,
          });
        });
    },

    async respond(session, requestId, decision) {
      if (decision !== "approve" && decision !== "deny") {
        throw new ContractError("invalid_params", "decision must be approve or deny");
      }
      const entry = pending.get(session.id)?.get(requestId);
      if (!entry) throw new ContractError("unknown_request", `no pending permission request ${requestId}`);
      const result =
        decision === "approve"
          ? { behavior: "allow", updatedInput: entry.input }
          : { behavior: "deny", message: "Denied by Varde" };
      settle(session, requestId, decision, result);
    },

    expireAll(session) {
      for (const requestId of [...(pending.get(session.id)?.keys() ?? [])]) expire(session, requestId);
      pending.delete(session.id);
    },

    pendingCount: (session) => pending.get(session.id)?.size ?? 0,
  };
}
