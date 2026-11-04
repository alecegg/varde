import * as fakeSdk from "./fake-sdk.mjs";
import { createEngine } from "../index.mjs";

export { fakeSdk };

export function pidAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

export async function waitFor(predicate, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error("timeout");
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}

export function harness(deps = {}) {
  const events = [];
  const waiters = [];
  const ctx = {
    emit: (event, session, data) => {
      events.push({ event, session, data });
      for (const waiter of waiters.splice(0)) waiter();
    },
    log: () => {},
    trackChild: () => {},
    untrackChild: () => {},
  };
  const engine = createEngine({ loadSdk: async () => fakeSdk, ...deps });
  const call = (method, params) => engine.handle(method, params, ctx);
  async function until(predicate, timeoutMs = 2000) {
    const deadline = Date.now() + timeoutMs;
    while (!predicate(events)) {
      if (Date.now() > deadline) throw new Error(`timeout; events: ${JSON.stringify(events.map((e) => e.event))}`);
      await new Promise((resolve) => {
        waiters.push(resolve);
        setTimeout(resolve, 20);
      });
    }
  }
  const names = () => events.map((item) => item.event);
  return { engine, events, call, until, names, ctx };
}
