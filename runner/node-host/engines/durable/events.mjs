import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { join } from "node:path";
import { openEventLog } from "./event-log.mjs";
import { entryEvents as mapEntryEvents } from "./compaction.mjs";

const POLL_INTERVAL_MS = 50;
const PAGE_SIZE = 100;

let ctx;
let log;
let models;
const conversations = new Map();
const subscriptions = new Map();

export const methods = {
  "events.subscribe": subscribe,
  "usage.get": getUsage,
};

/** Register the live Durable conversation after the session manager opens it. */
export function registerConversation(conversationId, conversation, modelCatalog) {
  if (!log) throw new Error("event bridge is not initialized");
  const previous = conversations.get(conversationId);
  if (previous) clearInterval(previous.timer);
  models = modelCatalog ?? models;
  const state = { conversation, timer: undefined, scanning: false, lastEntryId: 0 };
  state.timer = setInterval(() => scanConversation(conversationId, state), POLL_INTERVAL_MS);
  state.timer.unref?.();
  conversations.set(conversationId, state);
  void scanConversation(conversationId, state);
}

export function unregisterConversation(conversationId) {
  const state = conversations.get(conversationId);
  if (state) clearInterval(state.timer);
  conversations.delete(conversationId);
}

export async function init({ ctx: engineContext }) {
  ctx = engineContext;
  const storageDir = process.env.VARDE_PI_DURABLE_STORAGE_DIR;
  if (!storageDir) throw new Error("VARDE_PI_DURABLE_STORAGE_DIR is required");
  log = await openEventLog(join(storageDir, "events.sqlite"));
}

export async function close() {
  for (const state of conversations.values()) clearInterval(state.timer);
  conversations.clear();
  for (const subscription of subscriptions.values()) clearInterval(subscription.timer);
  subscriptions.clear();
  await log?.close();
  log = undefined;
  ctx = undefined;
}

async function scanConversation(conversationId, state) {
  if (state.scanning || !log) return;
  state.scanning = true;
  try {
    const entries = [];
    const minEntryId = state.lastEntryId + 1;
    let cursor;
    do {
      const page = await state.conversation.entries(
        { order: "ascending", minEntryId },
        PAGE_SIZE,
        cursor,
        BACKGROUND_CONTEXT,
      );
      entries.push(...page.items);
      cursor = page.next;
    } while (cursor !== undefined);
    const lastEntryId = entries.length > 0
      ? Math.max(state.lastEntryId, ...entries.map((entry) => Number(entry.id)))
      : state.lastEntryId;
    const rows = entries.flatMap((entry) => mapEntryEvents(entry, models));
    await log.append(conversationId, rows);
    state.lastEntryId = lastEntryId;
    for (const subscription of subscriptions.values()) {
      if (subscription.conversationId === conversationId) emitAvailable(subscription);
    }
  } catch (error) {
    ctx?.log("warn", `event bridge scan failed for ${conversationId}: ${error.message}`);
  } finally {
    state.scanning = false;
  }
}

async function subscribe(params) {
  const session = requiredString(params.session, "session");
  const cursor = nonNegativeInteger(params.after_cursor, "after_cursor");
  if (!conversations.has(session)) {
    const error = new Error(`unknown conversation: ${session}`);
    error.code = "unknown_session";
    throw error;
  }
  const existing = subscriptions.get(session);
  if (existing) clearInterval(existing.timer);
  const subscription = { conversationId: session, cursor, timer: undefined };
  subscription.timer = setInterval(() => emitAvailable(subscription), POLL_INTERVAL_MS);
  subscription.timer.unref?.();
  subscriptions.set(session, subscription);
  emitAvailable(subscription);
  return { session, cursor };
}

function emitAvailable(subscription) {
  if (!log || !ctx) return;
  const events = log.readFrom(subscription.conversationId, subscription.cursor);
  for (const row of events) {
    ctx.emit(row.event.type, subscription.conversationId, {
      ...row.event,
      cursor: row.cursor,
    });
    subscription.cursor = row.cursor;
  }
}

function getUsage(params) {
  const session = requiredString(params.session, "session");
  return { session, models: log.usage(session) };
}

function requiredString(value, name) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${name} must be a non-empty string`);
  }
  return value;
}

function nonNegativeInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative safe integer`);
  }
  return value;
}
