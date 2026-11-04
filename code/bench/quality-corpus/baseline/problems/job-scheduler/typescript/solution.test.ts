import assert from "node:assert/strict";
import { test } from "node:test";
import { runJobs } from "./solution.ts";

const job = (id: string, duration: number, priority = 0, deps: string[] = []) => ({ id, duration, priority, deps });
const plan = (jobs: ReturnType<typeof job>[], limit: number) =>
  runJobs(jobs, limit).map((r) => [r.id, r.start, r.end]);

test("single job", () => {
  assert.deepEqual(plan([job("a", 3)], 1), [["a", 0, 3]]);
});

test("dependency order", () => {
  assert.deepEqual(plan([job("b", 3, 0, ["a"]), job("a", 2)], 2), [["a", 0, 2], ["b", 2, 5]]);
});

test("priority among ready jobs", () => {
  assert.deepEqual(plan([job("a", 1, 1), job("b", 1, 5), job("c", 1, 3)], 1), [["b", 0, 1], ["c", 1, 2], ["a", 2, 3]]);
});

test("limit one runs serially", () => {
  assert.deepEqual(plan([job("c", 2), job("a", 2), job("b", 2)], 1), [["a", 0, 2], ["b", 2, 4], ["c", 4, 6]]);
});

test("limit two runs in parallel", () => {
  assert.deepEqual(plan([job("a", 2), job("b", 2), job("c", 2)], 2), [["a", 0, 2], ["b", 0, 2], ["c", 2, 4]]);
});

test("equal priority breaks by id", () => {
  assert.deepEqual(plan([job("x", 1), job("a", 1)], 1), [["a", 0, 1], ["x", 1, 2]]);
});

test("cycle is an error", () => {
  assert.throws(() => runJobs([job("a", 1, 0, ["b"]), job("b", 1, 0, ["a"])], 2));
  assert.throws(() => runJobs([job("a", 1, 0, ["a"])], 2));
});

test("invalid input is an error", () => {
  assert.throws(() => runJobs([job("a", 1, 0, ["missing"])], 1));
  assert.throws(() => runJobs([job("a", 1)], 0));
});
