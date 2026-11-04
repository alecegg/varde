import { createConnection } from "node:net";
import { createInterface } from "node:readline";
import { createPaseoClient } from "@getpaseo/client";
import { listAgents, listWorkspaces } from "./agent-directory.mjs";
import {
  createPermissionEventBridge,
  subscribePermissionEvents,
} from "./permission-events.mjs";

const [socketPath, url] = process.argv.slice(2);
const socket = createConnection(socketPath);
const input = createInterface({ input: socket });
const agents = new Map();
const subscriptions = new Map();
let client;

function write(message) {
  socket.write(`${JSON.stringify(message)}\n`);
}

function event(sessionId, event, payload, rawEventRef) {
  write({ session_id: sessionId, event, payload, raw_event_ref: rawEventRef });
}

function statusEvent(agent) {
  const status = agent.status === "running" || agent.status === "error" ? agent.status : "idle";
  event(agent.id, "status", { status });
}

async function connect() {
  client = createPaseoClient({ url });
  await client.connect();
}

async function handle(message) {
  let startedSessionId;
  try {
    if (!client) await connect();
    let result = {};
    switch (message.op) {
      case "start": {
        const workspace = client.workspaces.ref(message.workspace_id);
        const agent = await workspace.agents.create({
          cwd: message.cwd,
          config: {
            provider: message.provider_model,
            ...(message.mode_id ? { modeId: message.mode_id } : {}),
            ...(message.reasoning_effort ? { thinkingOptionId: message.reasoning_effort } : {}),
          },
          prompt: message.prompt,
        });
        startedSessionId = agent.id;
        agents.set(agent.id, agent);
        event(agent.id, "status", { status: "running" });
        result = { session_id: agent.id };
        break;
      }
      case "open_workspace": {
        const workspace = await client.workspaces.open(message.cwd);
        result = { workspace_id: workspace.id };
        break;
      }
      case "resume": {
        const agent = client.agents.ref(message.session_id);
        const snapshot = await agent.refresh();
        if (!snapshot) throw new Error("Paseo agent session was not found");
        agents.set(agent.id, agent);
        result = { session_id: agent.id };
        break;
      }
      case "inspect": {
        const agent = client.agents.ref(message.session_id);
        const snapshot = await agent.refresh();
        if (!snapshot) throw new Error("Paseo agent session was not found");
        result = {
          status: snapshot.agent.status,
          archived: Boolean(snapshot.agent.archivedAt),
          current_mode_id: snapshot.agent.currentModeId,
          pending_permissions: snapshot.agent.pendingPermissions,
        };
        break;
      }
      case "list_agents": {
        result = { agents: await listAgents(client) };
        break;
      }
      case "list_workspaces": {
        result = { workspaces: listWorkspaces(await listAgents(client)) };
        break;
      }
      case "send":
        await client.agents.ref(message.session_id).send(message.prompt);
        break;
      case "permission":
        await client.agents.ref(message.session_id).respondToPermission({
          requestId: message.request_id,
          response: message.decision === "allow" ? { behavior: "allow" } : { behavior: "deny" },
        });
        subscriptions.get(message.session_id)?.permissionBridge.resolved(
          message.request_id,
          { behavior: message.decision === "allow" ? "allow" : "deny" },
        );
        break;
      case "stop":
        await client.agents.ref(message.session_id).archive();
        break;
      case "subscribe": {
        const agent = client.agents.ref(message.session_id);
        const snapshot = await agent.refresh();
        if (!snapshot) throw new Error("Paseo agent session was not found");
        statusEvent(snapshot.agent);
        if (snapshot.agent.status === "error" && snapshot.agent.lastError) {
          event(agent.id, "error", { message: snapshot.agent.lastError });
        }
        const existingSubscription = subscriptions.get(agent.id);
        if (existingSubscription) {
          existingSubscription.permissionBridge.sync(snapshot.agent.pendingPermissions);
        } else {
          const permissionBridge = createPermissionEventBridge(agent.id, event);
          permissionBridge.sync(snapshot.agent.pendingPermissions);
          const permissionEvents = subscribePermissionEvents(client, agent.id, permissionBridge);
          const offAgent = agent.subscribe((update) => {
            if (update.agent) {
              statusEvent(update.agent);
              permissionBridge.sync(update.agent.pendingPermissions);
              if (update.agent.lastError) {
                event(agent.id, "error", { message: update.agent.lastError });
              }
            }
          });
          const timeline = agent.timeline.subscribe((update) => {
            const timelineEvent = update.event;
            if (timelineEvent.type === "error") {
              event(agent.id, "error", { message: timelineEvent.error });
              return;
            }
            if (timelineEvent.type === "replacement") {
              event(agent.id, "session_end", { reason: "timeline_replaced" });
              return;
            }
            if (timelineEvent.type === "subscription_restored") {
              event(agent.id, "status", { status: "idle", reconnected: true });
              return;
            }
            if ("event" in timelineEvent) {
              const streamEvent = timelineEvent.event;
              if (streamEvent.type === "turn_started") event(agent.id, "status", { status: "running" });
              if (streamEvent.type === "turn_completed" || streamEvent.type === "turn_canceled") {
                event(agent.id, "status", { status: "idle" });
              }
              if (streamEvent.type === "turn_failed") {
                event(agent.id, "status", { status: "error" });
                event(agent.id, "error", { message: streamEvent.error });
              }
              if (streamEvent.type === "usage_updated" || streamEvent.type === "turn_completed" && streamEvent.usage) {
                event(agent.id, "usage", { usage: streamEvent.usage });
              }
              if (streamEvent.type === "permission_requested") {
                permissionBridge.requested(streamEvent.request);
              } else if (streamEvent.type === "permission_resolved") {
                permissionBridge.resolved(streamEvent.requestId, streamEvent.resolution);
              } else if (streamEvent.type === "timeline") {
                const kind = streamEvent.item.type === "text" || streamEvent.item.type === "assistant_message" ? "text" : "tool";
                event(agent.id, kind, { item: streamEvent.item });
              }
            }
          });
          let lastStatus = snapshot.agent.status;
          let lastError = snapshot.agent.lastError;
          const poll = setInterval(() => {
            void agent.refresh().then((latest) => {
              if (!latest) return;
              if (latest.agent.status !== lastStatus) {
                statusEvent(latest.agent);
                lastStatus = latest.agent.status;
              }
              permissionBridge.sync(latest.agent.pendingPermissions);
              if (latest.agent.lastError && latest.agent.lastError !== lastError) {
                event(agent.id, "error", { message: latest.agent.lastError });
                lastError = latest.agent.lastError;
              }
            }).catch((error) => event(agent.id, "error", { message: String(error) }));
          }, 500);
          subscriptions.set(agent.id, {
            offAgent,
            timeline,
            poll,
            permissionBridge,
            permissionEvents,
          });
          await permissionEvents.ready;
          await timeline.ready;
        }
        result = { snapshot: [] };
        break;
      }
      case "close":
        await client.close();
        client = undefined;
        break;
      default:
        throw new Error(`Unknown operation ${message.op}`);
    }
    write({ id: message.id, ...result });
  } catch (error) {
    write({
      id: message.id,
      error: error instanceof Error ? error.message : String(error),
      ...(startedSessionId ? { session_id: startedSessionId } : {}),
    });
  }
}

input.on("line", (line) => void handle(JSON.parse(line)));
socket.on("close", () => {
  for (const { offAgent, timeline, poll, permissionEvents } of subscriptions.values()) {
    clearInterval(poll);
    offAgent();
    timeline();
    void permissionEvents.release();
  }
  void client?.close();
});
