import assert from "node:assert/strict";
import test from "node:test";

import {
  createPermissionEventBridge,
  subscribePermissionEvents,
} from "./permission-events.mjs";

test("maps Paseo daemon permission events to runner events", async () => {
  let observer;
  let subscribedEvents;
  let subscriptionOptions;
  const emitted = [];
  const client = {
    observeEvents(events, options) {
      subscribedEvents = events;
      subscriptionOptions = options;
      return {
        ready: Promise.resolve(),
        subscribe(nextObserver) {
          observer = nextObserver;
          return () => {};
        },
        async release() {},
      };
    },
  };
  const bridge = createPermissionEventBridge("agent-a", (sessionId, event, payload) => {
    emitted.push({ sessionId, event, payload });
  });
  const subscription = subscribePermissionEvents(client, "agent-a", bridge);
  await subscription.ready;

  const request = {
    id: "permission-a",
    kind: "tool",
    title: "Run command: /bin/zsh -lc 'echo ok > /tmp/probe.txt'",
  };
  observer.update({
    type: "agent_permission_request",
    payload: { agentId: "agent-a", request },
  });
  bridge.sync([request]);
  observer.update({
    type: "agent_permission_resolved",
    payload: {
      agentId: "agent-a",
      requestId: "permission-a",
      resolution: { behavior: "deny" },
    },
  });

  assert.deepEqual(subscribedEvents, [
    "agent_permission_request",
    "agent_permission_resolved",
  ]);
  assert.deepEqual(subscriptionOptions, { notifications: true });
  assert.deepEqual(emitted, [
    {
      sessionId: "agent-a",
      event: "permission_requested",
      payload: { request_id: "permission-a", request },
    },
    {
      sessionId: "agent-a",
      event: "permission_resolved",
      payload: {
        request_id: "permission-a",
        resolution: { behavior: "deny" },
      },
    },
  ]);
  await subscription.release();
});

test("emits pending permissions from snapshots once", () => {
  const emitted = [];
  const bridge = createPermissionEventBridge("agent-a", (sessionId, event, payload) => {
    emitted.push({ sessionId, event, payload });
  });
  const request = { id: "permission-b", kind: "tool" };

  bridge.sync([request]);
  bridge.sync([request]);

  assert.equal(emitted.length, 1);
  assert.deepEqual(emitted[0], {
    sessionId: "agent-a",
    event: "permission_requested",
    payload: { request_id: "permission-b", request },
  });
});
