import { join } from "node:path";
import { openApprovalStore } from "./approval-store.mjs";

const POLL_INTERVAL_MS = 50;
let ctx;
let store;
const inFlight = new Map();

export const methods = { "permission.respond": respond };

export async function init({ ctx: engineContext }) {
  ctx = engineContext;
  const storageDir = process.env.VARDE_PI_DURABLE_STORAGE_DIR;
  if (!storageDir) throw new Error("VARDE_PI_DURABLE_STORAGE_DIR is required");
  store = await openApprovalStore(join(storageDir, "approvals.sqlite"));
}

export async function close() {
  inFlight.clear();
  store?.close();
  store = undefined;
  ctx = undefined;
}

/** Gate a side effect behind a durable decision and idempotent delivery key. */
export async function gateAndEffect({ key, tool, summary, input }, effect) {
  if (!store || !ctx) throw new Error("approval bridge is not initialized");
  requiredString(key, "key");
  requiredString(tool, "tool");
  requiredString(summary, "summary");
  if (key.indexOf(":") < 1) throw new TypeError("key must include a conversation id and call id");
  if (typeof effect !== "function") throw new TypeError("effect must be a function");
  const approval = store.ensurePending({ key, tool, summary, input });
  if (approval.status === "pending") {
    const session = key.slice(0, key.indexOf(":"));
    ctx.emit("permission_request", session, {
      approval_id: key,
      tool,
      summary,
      input,
    });
  }
  const status = await waitForDecision(key);
  if (status === "denied") return { status: "denied" };
  if (status === "expired") return { status: "expired" };
  return deliverOnce(key, effect);
}

async function respond(params) {
  const key = requiredString(params.approval_id, "approval_id");
  const decision = params.decision;
  if (!["approved", "denied", "expired"].includes(decision)) {
    throw new TypeError("decision must be approved, denied or expired");
  }
  if (!store.respond(key, decision, Date.now())) {
    const error = new Error(`approval is stale or unknown: ${key}`);
    error.code = "stale_approval";
    throw error;
  }
  return { approval_id: key, status: decision };
}

async function waitForDecision(key) {
  while (true) {
    const approval = store.get(key);
    if (!approval) throw new Error(`approval disappeared: ${key}`);
    if (approval.status !== "pending") return approval.status;
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
}

function deliverOnce(key, effect) {
  const current = inFlight.get(key);
  if (current) return current;
  const delivery = runDelivery(key, effect);
  inFlight.set(key, delivery);
  delivery.finally(() => inFlight.delete(key)).catch(() => {});
  return delivery;
}

async function runDelivery(key, effect) {
  const delivery = store.beginDelivery(key);
  if (!delivery.claimed) {
    if (delivery.status === "completed") {
      return { status: "executed", value: delivery.value };
    }
    const error = new Error(`approval delivery outcome is uncertain and will not be retried: ${key}`);
    error.code = "delivery_uncertain";
    throw error;
  }
  try {
    const value = await effect();
    store.completeDelivery(key, value);
    return { status: "executed", value };
  } catch (error) {
    store.failDelivery(key, String(error));
    throw error;
  }
}

function requiredString(value, name) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${name} must be a non-empty string`);
  }
  return value;
}
