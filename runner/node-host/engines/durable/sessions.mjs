import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { builtinModels } from "@earendil-works/pi-ai/providers/all";
import { Harness, createRegistry, defineExtension } from "@earendil-works/pi-durable";
import { buildSessionTools } from "./tools/index.mjs";
import { resolveModelConfig } from "./roles.mjs";

let ctx;
let storage;
let approvals;
let events;
let harness;
let harnessPromise;
let registry;
const sessions = new Map();
const models = builtinModels();

export const methods = {
  "session.start": start,
  "session.send": send,
  "session.interrupt": interrupt,
  "session.stop": stop,
  "session.alive": alive,
};

export async function init(dependencies) {
  ({ ctx, storage, approvals, events } = dependencies);
}

export async function close() {
  sessions.clear();
  if (harness) await harness.close(BACKGROUND_CONTEXT);
  harness = undefined;
  harnessPromise = undefined;
  registry = undefined;
  ctx = storage = approvals = events = undefined;
}

async function start(params) {
  const cwd = requiredString(params.cwd, "cwd");
  const role = requiredString(params.role, "role");
  const mode = requiredString(params.mode, "mode");
  const modelConfig = resolveModelConfig({ provider: params.provider, model: params.model });
  const model = models.getModel(modelConfig.provider, modelConfig.modelId);
  if (!model) throw codedError("invalid_model", `unknown model: ${modelConfig.provider}/${modelConfig.modelId}`);
  const id = typeof params.conversation === "string" ? params.conversation : undefined;
  const durableId = id === undefined ? undefined : parseConversationId(id);
  const activeHarness = await getHarness();
  const existing = durableId === undefined
    ? undefined
    : await activeHarness.conversation(durableId, BACKGROUND_CONTEXT);
  if (id && !existing) throw codedError("unknown_session", `unknown conversation: ${id}`);

  const tools = buildSessionTools({ cwd, role, mode, env: params.env ?? {}, approvals, ctx });
  const conversation = existing ?? await activeHarness.createConversation({
    ownership: { kind: "ownerless" },
    agent: {
      model: { provider: model.provider, modelId: model.id },
      cwd,
      instructions: `You are acting as the ${role} role.`,
    },
  }, BACKGROUND_CONTEXT);
  const sessionId = String(conversation.id);
  const extension = defineExtension({ name: sessionId, tools });
  registry.install(extension);
  if (!existing) {
    await conversation.configure(
      { extensions: [extension], tools },
      BACKGROUND_CONTEXT,
    );
  }
  const active = {
    conversation,
    state: existing && await hasPendingWork(activeHarness, sessionId) ? "running" : "idle",
    cwd,
    pending: 0,
  };
  sessions.set(sessionId, active);
  events.registerConversation(sessionId, conversation, models);
  activeHarness.resume();
  if (typeof params.prompt === "string" && params.prompt.length > 0) {
    await queueInput(sessionId, params.prompt, crypto.randomUUID());
  }
  return { session: sessionId, resumed: Boolean(existing) };
}

async function hasPendingWork(activeHarness, sessionId) {
  const inspection = await activeHarness.inspect(BACKGROUND_CONTEXT);
  return inspection.submissions.some(
    (submission) =>
      String(submission.conversationId) === sessionId &&
      submission.status !== "done" &&
      submission.status !== "unanswered",
  );
}

async function send(params) {
  const sessionId = requiredString(params.session, "session");
  const text = requiredString(params.text, "text");
  const session = requireSession(sessionId);
  const requestId = requiredString(params.requestId, "requestId");
  await queueInput(sessionId, text, requestId);
  return {};
}

async function interrupt(params) {
  const sessionId = requiredString(params.session, "session");
  const session = requireSession(sessionId);
  await session.conversation.abort(BACKGROUND_CONTEXT);
  session.state = "idle";
  return {};
}

async function stop(params) {
  const sessionId = requiredString(params.session, "session");
  const session = sessions.get(sessionId);
  if (!session) return {};
  await session.conversation.abort(BACKGROUND_CONTEXT);
  events.unregisterConversation(sessionId);
  sessions.delete(sessionId);
  return {};
}

function alive(params) {
  const session = sessions.get(requiredString(params.session, "session"));
  return session
    ? { alive: true, state: session.state }
    : { alive: false, state: "ended" };
}

async function queueInput(sessionId, text, requestId) {
  const session = requireSession(sessionId);
  session.pending += 1;
  session.state = "running";
  let submission;
  try {
    submission = await session.conversation.submit(
      { type: "input", content: text, requestId },
      BACKGROUND_CONTEXT,
    );
  } catch (error) {
    setSubmissionState(session, -1);
    throw error;
  }
  void submission.wait(BACKGROUND_CONTEXT)
    .catch((error) => ctx.log("warn", `Pi Durable submission failed: ${error.message}`))
    .finally(() => setSubmissionState(session, -1));
}

function setSubmissionState(session, change) {
  session.pending += change;
  session.state = session.pending > 0 ? "running" : "idle";
}

async function getHarness() {
  if (!harnessPromise) {
    registry = createRegistry();
    harnessPromise = Harness.open(storage, { models, registry }, BACKGROUND_CONTEXT);
  }
  harness = await harnessPromise;
  return harness;
}

function requireSession(id) {
  const session = sessions.get(id);
  if (!session) throw codedError("unknown_session", `unknown session: ${id}`);
  return session;
}

function requiredString(value, name) {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(`${name} must be a non-empty string`);
  return value;
}

function codedError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function parseConversationId(value) {
  const id = Number(value);
  if (!Number.isSafeInteger(id) || id < 1) {
    throw codedError("invalid_params", "conversation must be a Durable conversation id");
  }
  return id;
}
