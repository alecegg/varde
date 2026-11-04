import assert from "node:assert/strict";

import { solution } from "./solution.ts";

type Invoice = { id: string; days_overdue: number; balance: number };

const bankCases: [Invoice[], unknown][] = [
  [
    [],
    {
      invoices: [],
      totals: { current: 0, "1-30": 0, "31-60": 0, "61-90": 0, "over-90": 0 },
    },
  ],
  [
    [{ id: "A", days_overdue: 0, balance: 100 }],
    {
      invoices: [{ id: "A", bucket: "current", fee: 0 }],
      totals: { current: 100, "1-30": 0, "31-60": 0, "61-90": 0, "over-90": 0 },
    },
  ],
  [
    [{ id: "A", days_overdue: 1, balance: 100 }],
    {
      invoices: [{ id: "A", bucket: "1-30", fee: 2 }],
      totals: { current: 0, "1-30": 100, "31-60": 0, "61-90": 0, "over-90": 0 },
    },
  ],
  [
    [{ id: "A", days_overdue: 30, balance: 100 }],
    {
      invoices: [{ id: "A", bucket: "1-30", fee: 2 }],
      totals: { current: 0, "1-30": 100, "31-60": 0, "61-90": 0, "over-90": 0 },
    },
  ],
  [
    [{ id: "A", days_overdue: 31, balance: 200 }],
    {
      invoices: [{ id: "A", bucket: "31-60", fee: 10 }],
      totals: { current: 0, "1-30": 0, "31-60": 200, "61-90": 0, "over-90": 0 },
    },
  ],
  [
    [{ id: "A", days_overdue: 60, balance: 50 }],
    {
      invoices: [{ id: "A", bucket: "31-60", fee: 2.5 }],
      totals: { current: 0, "1-30": 0, "31-60": 50, "61-90": 0, "over-90": 0 },
    },
  ],
  [
    [{ id: "A", days_overdue: 61, balance: 100 }],
    {
      invoices: [{ id: "A", bucket: "61-90", fee: 8 }],
      totals: { current: 0, "1-30": 0, "31-60": 0, "61-90": 100, "over-90": 0 },
    },
  ],
  [
    [{ id: "A", days_overdue: 90, balance: 50 }],
    {
      invoices: [{ id: "A", bucket: "61-90", fee: 4 }],
      totals: { current: 0, "1-30": 0, "31-60": 0, "61-90": 50, "over-90": 0 },
    },
  ],
  [
    [{ id: "A", days_overdue: 91, balance: 300 }],
    {
      invoices: [{ id: "A", bucket: "over-90", fee: 30 }],
      totals: { current: 0, "1-30": 0, "31-60": 0, "61-90": 0, "over-90": 300 },
    },
  ],
  [
    [{ id: "B", days_overdue: -2, balance: 40 }],
    {
      invoices: [{ id: "B", bucket: "current", fee: 0 }],
      totals: { current: 40, "1-30": 0, "31-60": 0, "61-90": 0, "over-90": 0 },
    },
  ],
  [
    [
      { id: "B", days_overdue: -2, balance: 40 },
      { id: "A", days_overdue: 31, balance: 80 },
      { id: "C", days_overdue: 5, balance: 50 },
    ],
    {
      invoices: [
        { id: "A", bucket: "31-60", fee: 4 },
        { id: "B", bucket: "current", fee: 0 },
        { id: "C", bucket: "1-30", fee: 1 },
      ],
      totals: { current: 40, "1-30": 50, "31-60": 80, "61-90": 0, "over-90": 0 },
    },
  ],
];

const names = ["current", "1-30", "31-60", "61-90", "over-90"];
const bounds = [1, 31, 61, 91];
const rateNumerators = [0n, 2n, 5n, 8n, 10n];

const rejected: Invoice[][] = [
  [{ id: "", days_overdue: 3, balance: 10 }],
  [{ id: null as unknown as string, days_overdue: 3, balance: 10 }],
  [{ id: "A", days_overdue: 1.5, balance: 10 }],
  [{ id: "A", days_overdue: 3, balance: -10 }],
  [{ id: "A", days_overdue: 3, balance: Number.NaN }],
  [{ id: 7 as unknown as string, days_overdue: 3, balance: 10 }],
  [{ id: "A", days_overdue: 3, balance: "10" as unknown as number }],
  [{ id: "A", days_overdue: 3 } as unknown as Invoice],
  [{ id: "A", days_overdue: Number.POSITIVE_INFINITY, balance: 10 }],
  [{ id: "A", days_overdue: Number.NEGATIVE_INFINITY, balance: 10 }],
];

/** Round a non-negative rational to the nearest integer, halves up. */
function rounded(value: bigint, denominator: bigint): bigint {
  return (value * 2n + denominator) / (denominator * 2n);
}

// The reference keeps every amount in integer hundredths, so the bucket fees it
// checks come from exact rational arithmetic rather than the float implementation.
function exact(invoices: Invoice[]) {
  const centsByBucket = names.map(() => 0n);
  const rows = invoices.map((invoice) => {
    const index = bounds.filter((bound) => bound <= invoice.days_overdue).length;
    const hundredths = BigInt(Math.round(invoice.balance * 100));
    centsByBucket[index] += hundredths;
    const feeCents = rounded(hundredths * rateNumerators[index], 100n);
    return { id: invoice.id, bucket: names[index], fee: Number(feeCents) / 100 };
  });
  rows.sort((left, right) => (left.id < right.id ? -1 : 1));
  const totals: Record<string, number> = {};
  for (const [index, name] of names.entries()) {
    totals[name] = Number(centsByBucket[index]) / 100;
  }
  return { invoices: rows, totals };
}

let seed = 20261017;
function nextValue(): number {
  seed = (Math.imul(seed, 1103515245) + 12345) >>> 0;
  return seed % 1000000;
}

for (const [invoices, expected] of bankCases) {
  assert.deepEqual(solution(invoices), expected, JSON.stringify(invoices));
}

for (const invoices of rejected) {
  assert.throws(() => solution(invoices), {
    message: "invalid invoice",
    cause: invoices,
  });
}

for (let index = 0; index < 2000; index += 1) {
  const size = nextValue() % 6;
  const invoices: Invoice[] = [];
  for (let position = 0; position < size; position += 1) {
    invoices.push({
      id: `I${String(nextValue() % 100000).padStart(6, "0")}`,
      days_overdue: (nextValue() % 300) - 20,
      balance: (nextValue() % 100000) / 4,
    });
  }
  assert.deepEqual(solution(invoices), exact(invoices), JSON.stringify(invoices));
}

const large: Invoice[] = [];
for (let index = 0; index < 1000; index += 1) {
  large.push({
    id: `I${String((index * 7919) % 100000).padStart(6, "0")}`,
    days_overdue: (index % 25) * 5 - 20,
    balance: (index % 4000) / 4,
  });
}
assert.deepEqual(solution(large), exact(large));
