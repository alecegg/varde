const permissionEventTypes = [
  "agent_permission_request",
  "agent_permission_resolved",
];

export function createPermissionEventBridge(sessionId, emit) {
  const pendingIds = new Set();
  const resolvedIds = new Set();

  function requested(request) {
    const requestId = request?.id;
    if (typeof requestId !== "string" || pendingIds.has(requestId)) return;
    pendingIds.add(requestId);
    resolvedIds.delete(requestId);
    emit(sessionId, "permission_requested", {
      request_id: requestId,
      request,
    });
  }

  function resolved(requestId, resolution) {
    if (typeof requestId !== "string" || resolvedIds.has(requestId)) return;
    pendingIds.delete(requestId);
    resolvedIds.add(requestId);
    if (resolvedIds.size > 256) resolvedIds.delete(resolvedIds.values().next().value);
    emit(sessionId, "permission_resolved", {
      request_id: requestId,
      resolution,
    });
  }

  function sync(pendingPermissions) {
    if (!Array.isArray(pendingPermissions)) return;
    for (const request of pendingPermissions) requested(request);
  }

  function update(message) {
    if (message?.type === "agent_permission_request") {
      if (message.payload?.agentId === sessionId) requested(message.payload.request);
      return;
    }
    if (message?.type === "agent_permission_resolved") {
      const payload = message.payload;
      if (payload?.agentId === sessionId) {
        resolved(payload.requestId, payload.resolution);
      }
    }
  }

  return { requested, resolved, sync, update };
}

export function subscribePermissionEvents(client, sessionId, bridge) {
  const subscription = client.observeEvents(permissionEventTypes, {
    notifications: true,
  });
  const unsubscribe = subscription.subscribe({
    snapshot() {},
    update: bridge.update,
  });

  return {
    ready: subscription.ready,
    async release() {
      unsubscribe();
      await subscription.release();
    },
  };
}
