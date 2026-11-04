import assert from "node:assert/strict";
import { solution } from "./solution.ts";

type R = Record<string, unknown>;
const req = (x: R = {}): R => ({ property_id: "CEDAR", arrival: 10, departure: 11, adults: 2,
  children: 0, extras: [], bookings: [], promo_code: "", ...x });
const book = (property_id: unknown, arrival: unknown, departure: unknown): R => ({ property_id,
  arrival, departure });
const integer = (x: unknown): x is number => typeof x === "number" && Number.isInteger(x);
const fail = (error: string, index: number | null = null): R => ({ error, index });
const rhu = (n: number, d: number): number => Math.floor((2 * n + d) / (2 * d));

// Independent oracle: validation follows the contract table; pricing visits each day.
function oracle(x: R): R {
  const p = (x.property_id as string).trim().toUpperCase(), a = x.arrival, d = x.departure;
  const adults = x.adults, children = x.children,
    ex = (x.extras as string[]).map((v) => v.trim().toUpperCase());
  const bookings = x.bookings as R[], promo = (x.promo_code as string).trim().toUpperCase();
  if (p !== "CEDAR" && p !== "LAKE") return fail("BAD_PROPERTY");
  if (!integer(adults) || adults < 1 || adults > 8) return fail("BAD_ADULTS");
  if (!integer(children) || children < 0 || children > 8) return fail("BAD_CHILDREN");
  if (!integer(a) || !integer(d) || a < 0 || d < 0 || a > 1e6 || d > 1e6
    || d <= a) return fail("BAD_DAYS");
  if (ex.length > 4) return fail("BAD_EXTRA");
  const seen = new Set<string>();
  for (let i = 0; i < ex.length; i++) { if (!["PARKING",
    "PET"].includes(ex[i]) || seen.has(ex[i])) return fail("BAD_EXTRA", i); seen.add(ex[i]); }
  if (bookings.length > 100) return fail("BAD_BOOKING");
  const bs: [string, number, number][] = [];
  for (let i = 0; i < bookings.length; i++) {
    const b = bookings[i], bp = (b.property_id as string).trim().toUpperCase(), ba = b.arrival,
      bd = b.departure;
    if ((bp !== "CEDAR" && bp !== "LAKE") || !integer(ba) || !integer(bd) || ba < 0 || bd < 0
      || ba > 1e6 || bd > 1e6 || bd <= ba) return fail("BAD_BOOKING", i);
    bs.push([bp, ba, bd]);
  }
  const nights = d - a;
  if (nights < 1 || nights > 30) return fail("BAD_STAY");
  if (adults + children > (p === "CEDAR" ? 4 : 6)) return fail("OVER_CAPACITY");
  const counts = { LOW: 0, PEAK: 0, SHOULDER: 0 };
  for (let day = a; day < d; day++) {
    const s = day % 365;
    if (s < 120) counts.LOW++;
    else if (s < 240) counts.PEAK++;
    else counts.SHOULDER++;
  }
  for (const [s, min] of [["LOW", 1], ["PEAK", 3], ["SHOULDER", 2]] as [keyof typeof counts,
    number][]) if (counts[s] && nights < min) return fail("MIN_STAY");
  for (let i = 0; i < bs.length; i++) {
    const [bp, ba, bd] = bs[i];
    if (bp === p && a < bd && ba < d) return fail("UNAVAILABLE", i);
  }
  if (!["", "PCT10", "FIXED5000", "ONENIGHT"].includes(promo)) return fail("BAD_PROMO");
  const lines: R[] = [];
  for (let day = a; day < d; day++) {
    const phase = day % 365, season = phase < 120 ? "LOW" : phase < 240 ? "PEAK" : "SHOULDER";
    const base = season === "LOW" ? 5000 : season === "PEAK" ? 9000 : 6500,
      weekend = day % 7 === 4 || day % 7 === 5 ? 1500 : 0;
    lines.push({ day, season, base_cents: base, weekend_cents: weekend,
      night_cents: base + weekend });
  }
  const subtotal = lines.reduce((v, row) => v + (row.night_cents as number), 0), cleaning = 4500;
  const guestFee = (Math.max(0, adults - 2) * 2000 + children * 1000) * nights,
    tax = 800 * (adults + children) * Math.min(nights, 5);
  const extraFee = ex.reduce((v, e) => v + (e === "PARKING" ? 1200 * nights : 2500), 0),
    pre = subtotal + cleaning + guestFee + tax + extraFee;
  const long = nights >= 14 ? rhu(subtotal * 15, 100) : nights >= 7 ? rhu(subtotal * 10, 100) : 0,
    after = pre - long;
  const promoFee = promo === "PCT10" ? rhu(after * 10,
    100) : promo === "FIXED5000" ? Math.min(5000,
    after) : promo === "ONENIGHT" ? Math.min(...lines.map((v) => v.night_cents as number)) : 0;
  const total = after - promoFee, deposit = Math.min(total, Math.max(10000, rhu(total * 30,
    100))), applied: string[] = [];
  if (lines.some((v) => v.weekend_cents)) applied.push("weekend");
  if (cleaning) applied.push("cleaning");
  if (guestFee) applied.push("extra-guests");
  if (tax) applied.push("tourist-tax");
  if (ex.includes("PARKING")) applied.push("parking");
  if (ex.includes("PET")) applied.push("pet");
  if (long) applied.push("long-stay");
  if (promoFee) applied.push("promo");
  if (total) applied.push("deposit");
  return { nights, night_lines: lines, cleaning_fee: cleaning, extra_guest_fee: guestFee,
    tourist_tax: tax, extras_fee: extraFee,
    long_stay_discount: long, promo_discount: promoFee, total, deposit,
      balance_due: total - deposit, applied,
    cancellation: a >= 30 ? "FLEX" : a >= 7 ? "STANDARD" : "FIRM" };
}
function check(x: R, expected: R = oracle(x)): void { assert.deepStrictEqual(solution(x),
  expected, JSON.stringify(x)); }

const worked = [req(), req({ arrival: 11, departure: 12 }), req({ arrival: 120, departure: 121 }),
  req({ arrival: 10, departure: 13 }),
  req({ arrival: 120, departure: 123 }), req({ arrival: 14, departure: 21 }),
    req({ property_id: "LAKE", arrival: 10, departure: 12, adults: 3, children: 2,
    extras: ["PARKING", "PET"] }),
  req({ promo_code: "PCT10" }), req({ arrival: 120, departure: 123, promo_code: "FIXED5000" }),
    req({ arrival: 11, departure: 12, promo_code: "ONENIGHT" }),
  req({ arrival: 240, departure: 247 }), req({ arrival: 364, departure: 366 })];
for (const x of worked) check(x);
assert.equal((solution(worked[0]) as R).total, 11100);
assert.equal((solution(worked[5]) as R).total, 46700);
assert.equal((solution(worked[6]) as R).deposit, 11070);
assert.equal((solution(worked[10]) as R).total, 56150);
assert.equal((solution(worked[11]) as R).total, 19200);
const bad: [R, string, number | null][] = [
  [req({ property_id: "bad", adults: 0 }), "BAD_PROPERTY", null], [req({ adults: 0,
    children: -1 }), "BAD_ADULTS", null], [req({ children: -1 }), "BAD_CHILDREN", null],
  [req({ adults: 9 }), "BAD_ADULTS", null], [req({ adults: 10 }), "BAD_ADULTS", null],
    [req({ children: 9 }), "BAD_CHILDREN", null], [req({ children: 10 }), "BAD_CHILDREN", null],
  [req({ adults: true }), "BAD_ADULTS", null], [req({ children: true }), "BAD_CHILDREN", null],
    [req({ adults: "2" }), "BAD_ADULTS", null], [req({ arrival: "10" }), "BAD_DAYS", null],
  [req({ children: null }), "BAD_CHILDREN", null], [req({ arrival: -1, departure: 1 }),
    "BAD_DAYS", null], [req({ arrival: 10, departure: 10, extras: ["bad"] }), "BAD_DAYS", null],
  [req({ extras: ["PET", "BOGUS"] }), "BAD_EXTRA", 1], [req({ extras: ["PET", "PET"] }),
    "BAD_EXTRA", 1], [req({ extras: Array(5).fill("PARKING") }), "BAD_EXTRA", null],
  [req({ bookings: Array(101).fill(book("bad", 4, 3)) }), "BAD_BOOKING", null],
    [req({ bookings: [book("bad", 4, 3)] }), "BAD_BOOKING", 0],
  [req({ bookings: [book("CEDAR", -1, 1)] }), "BAD_BOOKING", 0], [req({ bookings: [book("CEDAR",
    0, -1)] }), "BAD_BOOKING", 0], [req({ bookings: [book("CEDAR", 0, 0)] }), "BAD_BOOKING", 0],
  [req({ arrival: 120, departure: 122 }), "MIN_STAY", null], [req({ adults: 4, children: 1,
    bookings: [book("CEDAR", 10, 11)] }), "OVER_CAPACITY", null],
  [req({ property_id: "LAKE", arrival: 120, departure: 123, bookings: [book("LAKE", 122, 125),
    book("LAKE", 119, 121)] }), "UNAVAILABLE", 0],
  [req({ bookings: [book("CEDAR", 10, 11)], promo_code: "bad" }), "UNAVAILABLE", 0],
    [req({ arrival: 0, departure: 31, promo_code: "bad" }), "BAD_STAY", null],
  [req({ extras: ["PET", "bad"], bookings: [book("bad", 4, 3)] }), "BAD_EXTRA", 1],
    [req({ bookings: [book("bad", 4, 3)], promo_code: "bad" }), "BAD_BOOKING", 0],
];
for (const [x, code, index] of bad) check(x, fail(code, index));
const boundaries = [req({ property_id: " cedar " }), req({ property_id: " lake ", adults: 6 }),
  req({ property_id: "LAKE", adults: 1, children: 6 }),
  req({ adults: 1 }), req({ adults: 8 }), req({ property_id: "LAKE", children: 8 }),
  req({ arrival: 0, departure: 1 }), req({ arrival: 999999, departure: 1000000 }),
    req({ arrival: 1000000, departure: 1000001 }), req({ extras: [" parking "] }),
    req({ extras: ["PET", "PARKING"] }),
  req({ bookings: [book(" cedar ", 11, 12)] }), req({ arrival: 239, departure: 242 }),
    req({ arrival: 364, departure: 366 }), req({ arrival: 10, departure: 10, adults: 0 }),
    req({ property_id: "x", adults: 0, children: -1 }),
  ...[[0, 1], [9, 10], [11, 12], [10, 10], [10, 11]].map(([a,
    d]) => req({ bookings: [book("CEDAR", a, d)] })), req({ bookings: [book("LAKE", 10, 11)] }),
  ...[30, 29, 31, 8, 7].map((arrival) => req({ arrival, departure: arrival + 1 })), ...[6, 7, 13,
    14, 30, 19].map((departure) => req({ arrival: 0, departure })),
  ...["PCT10", "FIXED5000", "ONENIGHT"].map((promo_code) => req({ arrival: 0, departure: 1,
    promo_code })),
  ...[" PCT10 ", "FIXED5000", "ONENIGHT"].map((promo_code) => req({ promo_code })),
  req({ arrival: 120, departure: 123 }), req({ arrival: 364, departure: 366 }), req({ arrival: 10,
    departure: 11, promo_code: "PCT10" }),
  req({ arrival: 10, departure: 11, promo_code: "FIXED5000" }), req({ arrival: 10, departure: 11,
    promo_code: "ONENIGHT" }),
  req({ arrival: 13, departure: 20 }), req({ arrival: 20, departure: 34 }), req({ arrival: 0,
    departure: 7 }), req({ arrival: 0, departure: 13 }),
  req({ arrival: 0, departure: 14 }), req({ arrival: 0, departure: 30 }),
  req({ extras: ["PET", "PARKING", "PET", "PARKING", "PET"] }), req({ extras: ["PARKING",
    "PARKING", "PARKING", "PARKING", "PARKING"] }),
  req({ bookings: [book("CEDAR", 0, 1), book("CEDAR", 10, 11)] }),
  req({ bookings: [book("CEDAR", 10, 11), book("CEDAR", 10, 12)] }),
  req({ bookings: [book("LAKE", 20, 21), book("bad", 4, 3)] }),
  req({ bookings: [book("LAKE", 20, 21), book("CEDAR", 4, 3)] }),
  req({ arrival: 6, departure: 7 }),
  req({ arrival: 239, departure: 240 }),
  req({ arrival: 14, departure: 28, promo_code: "PCT10" }),
  req({ departure: 1000001 }), req({ promo_code: "pct10" }),
  req({ promo_code: "fixed5000" }), req({ promo_code: "onenight" }),
  req({ bookings: [book("LAKE", 0, 101), ...Array(100).fill(book("LAKE", 0, 1))] })];
for (const x of boundaries) check(x);
check(req({ bookings: Array.from({ length: 100 }, (_, i) => book("LAKE", 100 + 2 * i,
  101 + 2 * i)) }));
for (const field of ["adults", "children", "arrival", "departure"]) for (const value of [true,
  "a", null, 5.5]) check(req({ [field]: value }));
let state = 20261018;
const random = (n: number): number => {
  state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
  return Math.floor((state >>> 16) / 65536 * n);
};
let valid = 0, invalid = 0;
const properties = new Set<string>(), promos = new Set<string>(), seasons = new Set<number>();
const weekdays = new Set<number>(), errors = new Set<string>();
const distribution: Record<string, number> = {};
const errorKinds = ["BAD_PROPERTY", "BAD_ADULTS", "BAD_CHILDREN", "BAD_DAYS", "BAD_EXTRA",
  "BAD_BOOKING", "BAD_STAY", "OVER_CAPACITY", "MIN_STAY", "UNAVAILABLE", "BAD_PROMO"];
for (let i = 0; i < 2000; i++) {
  const property_id = random(2) ? "CEDAR" : "LAKE", season = random(3),
    start = Math.floor(random(100000) / 365) * 365 + (season === 0 ? random(90) : season === 1
    ? 120 + random(90) : 240 + random(95));
  const length = season === 0 ? 1 + random(30) : season === 1 ? 3 + random(28) : 2 + random(29),
    guests = 1 + random(property_id === "CEDAR" ? 4 : 6), adults = 1 + random(guests);
  const promo = ["", "PCT10", "FIXED5000", "ONENIGHT"][random(4)];
  const x = req({ property_id, arrival: start, departure: start + length, adults,
    children: guests - adults, extras: random(3) ? ["PARKING", "PET"] : [], promo_code: promo });
  properties.add(property_id); promos.add(promo); seasons.add(season);
  weekdays.add(start % 7);
  let generatedError: string | null = null;
  if (random(4) === 0) {
    generatedError = errorKinds[random(errorKinds.length)];
    if (generatedError === "BAD_PROPERTY") x.property_id = "bad";
    else if (generatedError === "BAD_ADULTS") x.adults = 0;
    else if (generatedError === "BAD_CHILDREN") x.children = -1;
    else if (generatedError === "BAD_DAYS") x.departure = 1000001;
    else if (generatedError === "BAD_EXTRA") x.extras = ["BAD"];
    else if (generatedError === "BAD_BOOKING") x.bookings = [book("CEDAR", -1, 1)];
    else if (generatedError === "BAD_STAY") x.departure = x.arrival as number + 31;
    else if (generatedError === "OVER_CAPACITY") {
      x.property_id = "CEDAR"; x.adults = 4; x.children = 1;
    }
    else if (generatedError === "MIN_STAY") { x.arrival = 120; x.departure = 121; }
    else if (generatedError === "UNAVAILABLE") {
      x.bookings = [book(property_id, start, start + length)];
    }
    else x.promo_code = "UNKNOWN";
  }
  const expected = oracle(x); check(x, expected); if ("error" in expected) invalid++; else valid++;
  const key = "error" in expected ? expected.error as string : "valid";
  errors.add(key); distribution[key] = (distribution[key] ?? 0) + 1;
}
assert.ok(valid >= 1000, `${valid} valid random requests`);
for (const value of ["CEDAR", "LAKE"]) assert.ok(properties.has(value), `property ${value}`);
for (const value of ["", "PCT10", "FIXED5000", "ONENIGHT"]) {
  assert.ok(promos.has(value), `promo ${value}`);
}
for (const value of [0, 1, 2]) assert.ok(seasons.has(value), `season ${value}`);
for (const value of [0, 1, 2, 3, 4, 5, 6]) assert.ok(weekdays.has(value), `weekday ${value}`);
for (const value of errorKinds) assert.ok(errors.has(value), `error ${value}`);
console.log(`rental-quote: ${worked.length} worked, ${bad.length} errors,` +
  ` ${boundaries.length} boundaries; random ${valid} valid/${invalid} invalid;` +
  ` ${JSON.stringify(distribution)}`);
