import assert from "node:assert/strict";
import { test } from "node:test";
import { Dispatcher } from "./solution.ts";

function sender(failing: Set<string> = new Set()) {
  const calls: [string, string][] = [];
  const send = (channel: string, message: string): boolean => {
    calls.push([channel, message]);
    return !failing.has(channel);
  };
  return { calls, failing, send };
}

const ch = (name: string, limit: number) => ({ name, limit });

test("first channel is used", () => {
  const s = sender();
  const d = new Dispatcher([ch("email", 5), ch("sms", 5)], s.send);
  assert.equal(d.dispatch("hi", 0), "email");
  assert.deepEqual(s.calls, [["email", "hi"]]);
});

test("limit falls back", () => {
  const d = new Dispatcher([ch("email", 2), ch("sms", 9)], sender().send);
  assert.deepEqual([0, 1, 2].map((t) => d.dispatch("m", t)), ["email", "email", "sms"]);
});

test("window expires", () => {
  const d = new Dispatcher([ch("email", 1), ch("sms", 9)], sender().send);
  assert.deepEqual([0, 30, 61].map((t) => d.dispatch("m", t)), ["email", "sms", "email"]);
});

test("failed send falls back", () => {
  const d = new Dispatcher([ch("email", 5), ch("sms", 5)], sender(new Set(["email"])).send);
  assert.equal(d.dispatch("m", 0), "sms");
});

test("failed send keeps quota", () => {
  const s = sender(new Set(["email"]));
  const d = new Dispatcher([ch("email", 1), ch("sms", 9)], s.send);
  assert.equal(d.dispatch("m", 0), "sms");
  s.failing.clear();
  assert.equal(d.dispatch("m", 1), "email");
});

test("all unavailable returns null", () => {
  const s = sender(new Set(["email", "sms"]));
  const d = new Dispatcher([ch("email", 5), ch("sms", 5)], s.send);
  assert.equal(d.dispatch("m", 0), null);
  assert.deepEqual(s.calls.map((c) => c[0]), ["email", "sms"]);
});

test("boundary at the window edge", () => {
  const d = new Dispatcher([ch("email", 1), ch("sms", 9)], sender().send);
  assert.equal(d.dispatch("m", 0), "email");
  assert.equal(d.dispatch("m", 59), "sms");
  assert.equal(d.dispatch("m", 60), "email");
});

test("limited channel is not attempted", () => {
  const s = sender();
  const d = new Dispatcher([ch("email", 1), ch("sms", 9)], s.send);
  d.dispatch("a", 0);
  d.dispatch("b", 1);
  assert.deepEqual(s.calls, [["email", "a"], ["sms", "b"]]);
});
