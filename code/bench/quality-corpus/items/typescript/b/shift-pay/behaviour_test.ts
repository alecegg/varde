import assert from "node:assert/strict";
import { solution } from "./solution.ts";

type R = Record<string, any>;
const shift = (day: unknown, start: unknown, end: unknown, breakMinutes: unknown = 0, holiday: unknown = false, callout: unknown = false): R => ({ day, start, end, break: breakMinutes, holiday, callout });
const req = (role: unknown = "helper", shifts: R[] = [], bonus: unknown = false): R => ({ role, shifts, bonus });
const fail = (error: string, index: number | null = null) => ({ error, index });
const roundHalfUp = (n: number, d: number) => Math.floor((2 * n + d) / (2 * d));

// Independent oracle: table validation followed by minute expansion and pricing.
function oracle(input: R): R {
  const role = typeof input.role === "string" ? input.role.trim().toLowerCase() : input.role;
  const shifts = input.shifts as R[];
  if (!(role === "helper" || role === "nurse" || role === "lead")) return fail("BAD_ROLE");
  if (shifts.length === 0) return fail("EMPTY_WEEK");
  if (shifts.length > 14) return fail("TOO_MANY_SHIFTS");
  if (typeof input.bonus !== "boolean") return fail("BAD_BONUS");
  const starts: number[] = [];
  const durations: number[] = [];
  for (let index = 0; index < shifts.length; index++) {
    const row = shifts[index];
    const checks: [string, number, number, string][] = [
      ["day", 0, 6, "BAD_DAY"], ["start", 0, 1439, "BAD_START"],
      ["end", 0, 1439, "BAD_END"], ["break", 0, 240, "BAD_BREAK"],
    ];
    for (const [field, low, high, code] of checks) {
      const value = row[field];
      if (typeof value !== "number" || !Number.isInteger(value) || value < low || value > high) return fail(code, index);
    }
    if (typeof row.holiday !== "boolean") return fail("BAD_HOLIDAY", index);
    if (typeof row.callout !== "boolean") return fail("BAD_CALLOUT", index);
    const duration = (row.end - row.start + 1440) % 1440 || 1440;
    if (duration < 1 || duration > 960) return fail("BAD_LENGTH", index);
    if (row.break > duration) return fail("BREAK_TOO_LONG", index);
    starts.push(row.day * 1440 + row.start);
    durations.push(duration);
  }
  const overlaps: [number, number][] = [];
  for (let left = 0; left < shifts.length; left++) for (let right = left + 1; right < shifts.length; right++) {
    for (const offset of [-10080, 0, 10080]) {
      const beginning = Math.max(starts[left], starts[right] + offset);
      if (beginning < Math.min(starts[left] + durations[left], starts[right] + offset + durations[right])) {
        overlaps.push([beginning, right]);
      }
    }
  }
  overlaps.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (overlaps.length) return fail("OVERLAP", overlaps[0][1]);
  const rate = role === "helper" ? 1800 : role === "nurse" ? 2400 : 3000;
  const out: R[] = [];
  let weekCount = 0;
  for (let i = 0; i < shifts.length; i++) {
    const inputRow = shifts[i];
    const duration = durations[i];
    const unpaid = duration > 360 ? inputRow.break : 0;
    const worked = duration - unpaid;
    let amountNumerator = 0;
    let regular = 0, overtime = 0, night = 0, weekend = 0, holiday = 0;
    let dailyRule = false, weeklyRule = false;
    for (let n = 0; n < worked; n++) {
      const absoluteMinute = starts[i] + unpaid + n;
      const localMinute = absoluteMinute % 1440;
      const weekday = Math.floor(absoluteMinute / 1440) % 7;
      const daily = n >= 480;
      const weekly = weekCount + n >= 2400;
      dailyRule ||= daily;
      weeklyRule ||= weekly;
      const overtimeMinute = daily || weekly;
      regular += Number(!overtimeMinute);
      overtime += Number(overtimeMinute);
      night += Number(localMinute >= 1320 || localMinute < 360);
      weekend += Number(weekday === 5 || weekday === 6);
      holiday += Number(inputRow.holiday);
      amountNumerator += rate * (20 + 10 * Number(overtimeMinute) + 4 * Number(localMinute >= 1320 || localMinute < 360)
        + 5 * Number(weekday === 5 || weekday === 6) + 20 * Number(inputRow.holiday));
    }
    const topUp = inputRow.callout ? Math.max(0, 180 - worked) : 0;
    amountNumerator += rate * topUp * 20;
    out.push({ day: inputRow.day, start: inputRow.start, end: inputRow.end, paid_minutes: worked,
      regular_minutes: regular, overtime_minutes: overtime, night_minutes: night, weekend_minutes: weekend,
      holiday_minutes: holiday, callout_minutes: topUp, bonus_cents: 0,
      cents: roundHalfUp(amountNumerator, 1200), _daily: dailyRule, _weekly: weeklyRule });
    weekCount += worked;
  }
  if (input.bonus && weekCount >= 600) {
    out[out.length - 1].bonus_cents = 500;
    out[out.length - 1].cents += 500;
  }
  const rules: [string, string][] = [["_daily", "daily-overtime"], ["_weekly", "weekly-overtime"],
    ["night_minutes", "night-premium"], ["weekend_minutes", "weekend-premium"],
    ["holiday_minutes", "holiday-rate"], ["callout_minutes", "callout-minimum"], ["bonus_cents", "bonus"]];
  const applied = rules.filter(([key]) => out.some((row) => row[key] > 0)).map(([, name]) => name);
  const rows = out.map(({ _daily, _weekly, ...row }) => row);
  return { shifts: rows, weekly_paid_minutes: weekCount, weekly_cents: rows.reduce((sum, row) => sum + row.cents, 0), applied };
}

function check(input: R, expected: R = oracle(input)): void {
  assert.deepStrictEqual(solution(input), expected, `request=${JSON.stringify(input)}`);
}

const worked: [R, number, number][] = [
  [req("helper", [shift(0, 540, 1020, 30)]), 450, 13500], [req("nurse", [shift(1, 1320, 360, 30)]), 450, 21600],
  [req("helper", [shift(5, 540, 780)]), 240, 9000], [req("lead", [shift(2, 540, 780, 0, true)]), 240, 24000],
  [req("helper", [shift(0, 540, 600, 0, false, true)]), 60, 5400], [req("nurse", [shift(4, 480, 1080, 60)]), 540, 22800],
  [req("helper", [shift(6, 1380, 180)]), 240, 9090], [req("lead", [shift(5, 600, 1080, 30, true)], true), 450, 50625],
  [req("helper", [shift(1, 360, 900, 60)]), 480, 14400], [req("nurse", [shift(0, 720, 840, 0, false, true)], true), 120, 7200],
  [req("helper", Array.from({ length: 6 }, (_, day) => shift(day, 540, 1020))), 2880, 97200],
  [req("helper", [shift(0, 1260, 300)]), 480, 16920],
];
for (const [input, paid, cents] of worked) {
  assert.deepStrictEqual([oracle(input).weekly_paid_minutes, oracle(input).weekly_cents], [paid, cents]);
  check(input);
}

const errors: [R, string, number | null][] = [
  [req("unknown"), "BAD_ROLE", null], [req("helper", [], null), "EMPTY_WEEK", null],
  [req("helper", Array(15).fill(shift(0, 0, 60)), 1), "TOO_MANY_SHIFTS", null],
  [req("helper", [shift(7, 0, 60)], 1), "BAD_BONUS", null],
  [req("helper", [{ ...shift(0, 0, 60), day: true }]), "BAD_DAY", 0],
  [req("helper", [{ ...shift(0, 0, 60), start: true }]), "BAD_START", 0],
  [req("helper", [{ ...shift(0, 0, 60), end: true }]), "BAD_END", 0],
  [req("helper", [{ ...shift(0, 0, 60), break: true }]), "BAD_BREAK", 0],
  [req("helper", [{ ...shift(0, 0, 60), day: 7, start: 1440 }]), "BAD_DAY", 0],
  [req("helper", [{ ...shift(0, 0, 60), start: 1440, end: 1500 }]), "BAD_START", 0],
  [req("helper", [{ ...shift(0, 0, 60), end: 1500, break: 241 }]), "BAD_END", 0],
  [req("helper", [{ ...shift(0, 0, 60), break: 241, holiday: 1 }]), "BAD_BREAK", 0],
  [req("helper", [{ ...shift(0, 0, 60), holiday: 1, callout: 1 }]), "BAD_HOLIDAY", 0],
  [req("helper", [{ ...shift(0, 0, 961), callout: 1 }]), "BAD_CALLOUT", 0],
  [req("helper", [shift(0, 0, 961, 240)]), "BAD_LENGTH", 0], [req("helper", [shift(0, 540, 540)]), "BAD_LENGTH", 0],
  [req("helper", [shift(0, 0, 60, 61)]), "BREAK_TOO_LONG", 0],
  [req("helper", [shift(0, 0, 120), shift(0, 60, 180)]), "OVERLAP", 1],
  [req("helper", [shift(0, 0, 961), shift(0, 60, 180), shift(0, 90, 200)]), "BAD_LENGTH", 0],
];
for (const [input, code, index] of errors) check(input, fail(code, index));

for (const [field, code, badValues] of [
  ["day", "BAD_DAY", [-1, 5.5, "5", null, true]], ["start", "BAD_START", [-1, 5.5, "5", null, true]],
  ["end", "BAD_END", [-1, 5.5, "5", null, true]], ["break", "BAD_BREAK", [-1, 5.5, "5", null, true]],
] as [string, string, unknown[]][]) for (const value of badValues) for (const index of [1, 2]) {
  const rows = [shift(0, 0, 30), shift(2, 0, 30), shift(4, 0, 30)].slice(0, index);
  rows.push({ ...shift(6, 0, 30), [field]: value }); check(req("helper", rows), fail(code, index));
}
for (const [field, code] of [["holiday", "BAD_HOLIDAY"], ["callout", "BAD_CALLOUT"]]) for (const index of [1, 2]) {
  const rows = [shift(0, 0, 30), shift(2, 0, 30), shift(4, 0, 30)].slice(0, index);
  rows.push({ ...shift(6, 0, 30), [field]: 1 }); check(req("helper", rows), fail(code, index));
}
for (const [invalid, code] of [[shift(6, 0, 961), "BAD_LENGTH"], [shift(6, 0, 60, 61), "BREAK_TOO_LONG"]] as [R, string][]) {
  for (const index of [1, 2]) check(req("helper", [...[shift(0, 0, 30), shift(2, 0, 30)].slice(0, index), invalid]), fail(code, index));
}

// Closed numeric bounds and the first value outside each boundary.
for (const [field, low, high, code] of [["day", 0, 6, "BAD_DAY"], ["start", 0, 1439, "BAD_START"], ["end", 0, 1439, "BAD_END"], ["break", 0, 240, "BAD_BREAK"]] as [string, number, number, string][]) {
  const atLow = shift(0, 0, 30); atLow[field] = low;
  if (field === "end") atLow.start = 1439;
  check(req("helper", [atLow]));
  const atHigh = shift(0, 0, 30); atHigh[field] = high;
  if (field === "day") atHigh.start = 0;
  if (field === "start") { atHigh.end = 0; }
  if (field === "end") { atHigh.start = 479; }
  if (field === "break") { atHigh.end = 960; atHigh.break = 240; }
  check(req("helper", [atHigh]));
  for (const invalid of [low - 1, high + 1]) {
    const row = shift(0, 0, 30); row[field] = invalid;
    check(req("helper", [row]), fail(code, 0));
  }
  for (const invalid of [null, "a", true, 5.5, "5"]) {
    const row = shift(0, 0, 30); row[field] = invalid;
    check(req("helper", [row]), fail(code, 0));
  }
}
for (const [duration, breakMinutes, paid] of [[360, 60, 360], [361, 60, 301], [480, 0, 480], [481, 0, 481], [960, 240, 720]]) {
  const input = req("helper", [shift(0, 0, duration % 1440, breakMinutes)]);
  assert.equal(oracle(input).weekly_paid_minutes, paid); check(input);
}
assert.equal(oracle(req("helper", [shift(0, 0, 480)])).shifts[0].overtime_minutes, 0);
assert.equal(oracle(req("helper", [shift(0, 0, 481)])).shifts[0].overtime_minutes, 1);
check(req("helper", [shift(0, 0, 400, 400, false, true)])); check(req("helper", [shift(0, 0, 60, 60)]));
for (const duration of [179, 180]) check(req("helper", [shift(0, 0, duration, 0, false, true)]));
check(req("helper", Array.from({ length: 14 }, (_, i) => shift(Math.floor(i / 2), (i % 2) * 100, (i % 2) * 100 + 30))));
const overnightHoliday = req("lead", [shift(5, 1439, 1, 0, true)]);
assert.equal(oracle(overnightHoliday).shifts[0].holiday_minutes, 2); check(overnightHoliday);
for (const [start, expected] of [[359, 1], [360, 0], [1319, 59], [1320, 60]]) {
  const input = req("helper", [shift(0, start, (start + 60) % 1440)]);
  assert.equal(oracle(input).shifts[0].night_minutes, expected); check(input);
}
for (const rows of [[shift(0, 60, 120), shift(6, 1380, 180)], [shift(6, 1380, 180), shift(0, 60, 120)], [shift(0, 0, 60), shift(0, 60, 120)]]) check(req("helper", rows));
const weekly = req("helper", Array.from({ length: 6 }, (_, day) => shift(day, 540, 1020)));
assert.equal(oracle(weekly).shifts[5].overtime_minutes, 480); check(weekly);
const weeklyEdge = req("helper", [...[4, 3, 2, 1, 0].map((day) => shift(day, 540, 1020)), shift(5, 540, 541)]);
assert.equal(oracle(weeklyEdge).shifts[5].overtime_minutes, 1); check(weeklyEdge);
const threshold = req("helper", [...[0, 1, 2, 3].map((day) => shift(day, 540, 1020)), shift(4, 0, 479), shift(5, 0, 2)]);
assert.equal(oracle(threshold).shifts[5].overtime_minutes, 1); check(threshold);
const combined = req("helper", [...[0, 1, 2, 3, 4].map((day) => shift(day, 540, 1020)), shift(5, 540, 1021)]);
assert.deepEqual(oracle(combined).applied.slice(0, 2), ["daily-overtime", "weekly-overtime"]); check(combined);
const calloutThreshold = req("helper", [...[0, 1, 2, 3, 4].map((day) => shift(day, 0, 478)), shift(5, 0, 10, 0, false, true)]);
assert.equal(oracle(calloutThreshold).shifts[5].overtime_minutes, 0); check(calloutThreshold);
const topUpNotWeekly = req("helper", [...[0, 1, 2, 3, 4].map((day) => shift(day, 0, 460)), shift(5, 0, 10, 0, false, true), shift(6, 0, 1)]);
assert.equal(oracle(topUpNotWeekly).shifts[6].overtime_minutes, 0); check(topUpNotWeekly);
for (const [workedMinutes, cents] of [[599, 0], [600, 500]]) {
  const first = Math.floor(workedMinutes / 2); const input = req("helper", [shift(0, 0, first), shift(1, 0, workedMinutes - first)], true);
  assert.equal(oracle(input).shifts[1].bonus_cents, cents); check(input);
}
const halfCent = req("helper", [shift(5, 600, 601)]);
assert.equal(oracle(halfCent).shifts[0].cents, 38); check(halfCent);
const perShift = req("helper", [shift(5, 600, 601), shift(6, 600, 601)]);
assert.equal(oracle(perShift).weekly_cents, 76); check(perShift);
const breakNight = req("helper", [shift(0, 330, 810, 30)]);
assert.equal(oracle(breakNight).shifts[0].night_minutes, 0); check(breakNight);
const weekendHoliday = req("lead", [shift(5, 600, 601, 0, true)]);
assert.equal(oracle(weekendHoliday).shifts[0].cents, 113); check(weekendHoliday);
check(req(" Helper ", [shift(0, 600, 601)]));
check(req("helper", [shift(0, 0, 120), shift(0, 60, 120), shift(0, 60, 120)]), fail("OVERLAP", 1));
check(req("helper", [shift(0, 0, 960, 0, false, true)], true));

let state = 20261018;
function random(limit: number): number { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state % limit; }
const RANDOM_CASES = Number(process.env.SHIFT_PAY_RANDOM_CASES ?? 4000);
let valid = 0, invalid = 0;
for (let iteration = 0; iteration < RANDOM_CASES; iteration++) {
  const rows: R[] = [];
  const role = ["helper", "nurse", "lead"][random(3)];
  if (random(4) !== 0) {
    const count = 1 + random(14);
    const slot = Math.floor(10080 / count);
    for (let i = 0; i < count; i++) {
      const duration = 1 + random(Math.min(960, slot));
      const minute = i * slot + random(Math.max(1, slot - duration + 1));
      const start = minute % 1440;
      rows.push(shift(Math.floor(minute / 1440), start, (start + duration) % 1440,
        random(Math.min(241, duration + 1)), random(2) === 1, random(2) === 1));
    }
    // Target long shifts and multi-day overtime while keeping intervals disjoint.
    if (iteration % 4 === 0) rows.splice(0, rows.length, ...[0, 1, 2, 3, 4, 5].map((day) => shift(day, 540, 1020, 0, random(2) === 1, random(2) === 1)));
    if (iteration % 8 === 0) rows[0] = shift(0, 1380, 180, 0, true, true);
    rows.sort(() => 0); // preserve timeline ordering for overlap-free generated sets
    if (random(3) === 0) rows[0].day = -1;
  } else {
    rows.push(shift(random(7), random(1400), random(1400), random(241), random(2) === 1, random(2) === 1));
    if (random(2) === 0) rows[0].holiday = 1;
  }
  const input = req(role, rows, random(2) === 1);
  check(input);
  if (oracle(input).error) invalid++; else valid++;
}
assert.ok(valid * 2 >= RANDOM_CASES, `valid random mix too small: ${valid}/${RANDOM_CASES}`);
console.log(`shift-pay: ${worked.length} worked examples, ${errors.length} precedence errors, ${valid} valid and ${invalid} invalid seeded requests passed`);
