import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { OrderSystem } from "./solution.ts";

let system: OrderSystem;
beforeEach(() => {
  system = new OrderSystem();
});

const dates = (orders: { date: string }[]): string[] => orders.map((o) => o.date);

test("first order on the start date", () => {
  const plan = system.addRecurring("ann", 1000, 2, "2024-01-15");
  const orders = system.ordersThrough("2024-01-15");
  assert.deepEqual(
    orders.map((o) => [o.recurringId, o.date, o.totalCents]),
    [[plan, "2024-01-15", 2000]],
  );
});

test("repeats monthly", () => {
  system.addRecurring("ann", 500, 1, "2024-01-15");
  assert.deepEqual(dates(system.ordersThrough("2024-03-20")), ["2024-01-15", "2024-02-15", "2024-03-15"]);
});

test("day is clamped to the month length", () => {
  system.addRecurring("ann", 500, 1, "2024-01-31");
  assert.deepEqual(dates(system.ordersThrough("2024-03-31")), ["2024-01-31", "2024-02-29", "2024-03-31"]);
});

test("orders are generated once", () => {
  system.addRecurring("ann", 500, 1, "2024-01-15");
  assert.deepEqual(dates(system.ordersThrough("2024-01-31")), ["2024-01-15"]);
  assert.deepEqual(dates(system.ordersThrough("2024-02-20")), ["2024-02-15"]);
  assert.deepEqual(dates(system.ordersThrough("2024-02-20")), []);
});

test("cancel stops future orders", () => {
  const plan = system.addRecurring("ann", 500, 1, "2024-01-15");
  assert.equal(system.ordersThrough("2024-01-20").length, 1);
  system.cancel(plan);
  assert.deepEqual(system.ordersThrough("2024-06-01"), []);
});

test("start after the date generates nothing", () => {
  system.addRecurring("ann", 500, 1, "2024-05-01");
  assert.deepEqual(system.ordersThrough("2024-04-30"), []);
});

test("invalid plan is rejected", () => {
  assert.throws(() => system.addRecurring("ann", 500, 0, "2024-01-01"));
  assert.throws(() => system.addRecurring("ann", -1, 1, "2024-01-01"));
});

test("orders sorted by date then plan", () => {
  system.addRecurring("a", 100, 1, "2024-01-20");
  system.addRecurring("b", 100, 1, "2024-01-10");
  system.addRecurring("c", 100, 1, "2024-01-10");
  assert.deepEqual(system.ordersThrough("2024-01-31").map((o) => o.recurringId), [2, 3, 1]);
});
