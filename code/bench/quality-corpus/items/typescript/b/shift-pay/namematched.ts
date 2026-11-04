type Shift = {
  day: number; start: number; end: number; break: number; holiday: boolean; callout: boolean;
};
type Request = { role: string; shifts: Shift[]; bonus: boolean };
type PreparedShift = Shift & {
  index: number; duration: number; paid: number; timeline: number;
};
type ShiftResult = Record<string, number> & { daily: number; weekly: number };
type PayFailure = { error: string; index: number | null };
const HOURLY_RATES = { helper: 1800, nurse: 2400, lead: 3000 };
const APPLIED_RULES = [
  ["daily", "daily-overtime"], ["weekly", "weekly-overtime"],
  ["night_minutes", "night-premium"], ["weekend_minutes", "weekend-premium"],
  ["holiday_minutes", "holiday-rate"], ["callout_minutes", "callout-minimum"],
  ["bonus_cents", "bonus"],
] as const;

/** Return ordered shift pay rows or the first contract validation error. */
export function solution(request: Request): Record<string, unknown> {
  const role = normalise(request.role), issue = validate(role, request.shifts, request.bonus);
  if (issue) return issue;
  const rows = prepareShifts(request.shifts), invalid = validateShifts(rows);
  if (invalid) return invalid;
  return overlap(rows) || pay(role, rows, request.bonus);
}
function normalise(v: string): string { return v.trim().toLowerCase(); }
function validate(r: string, rows: Shift[], b: boolean): PayFailure | null {
  return checkRequestFields(r, rows, b);
}
function checkRequestFields(r: string, rows: Shift[], b: boolean): PayFailure | null {
  if (!Object.hasOwn(HOURLY_RATES, r)) return failure("BAD_ROLE", null);
  return validateRequestRows(rows) || (typeof b === "boolean" ? null : failure("BAD_BONUS", null));
}
function validateRequestRows(rows: Shift[]): PayFailure | null {
  return rows.length ? validateShiftCount(rows) : failure("EMPTY_WEEK", null);
}
function validateShiftCount(rows: Shift[]): PayFailure | null {
  return rows.length <= 14 ? null : failure("TOO_MANY_SHIFTS", null);
}
function failure(c: string, i: number | null): PayFailure { return { error: c, index: i }; }
function prepareShifts(rows: Shift[]): PreparedShift[] {
  return rows.map((s, i) => prepareShift(s, i));
}
function prepareShift(s: Shift, i: number): PreparedShift {
  return { ...s, index: i, duration: 0, paid: 0, timeline: 0 };
}
function validateShifts(rows: PreparedShift[]): PayFailure | null { return checkAllShifts(rows); }
function checkAllShifts(rows: PreparedShift[]): PayFailure | null {
  for (const p of rows) { const e = validateShift(p); if (e) return e; }
  return null;
}
function validateShift(p: PreparedShift): PayFailure | null {
  return validateIntegerFields(p) || validateFlags(p) || validateLength(p);
}
function validateIntegerFields(p: PreparedShift): PayFailure | null {
  for (const [v, hi, code] of integerFields(p)) {
    const failure = boundedIntegerError(v, hi, code, p.index);
    if (failure) return failure;
  }
  return null;
}
function integerFields(p: PreparedShift): readonly [number, number, string][] {
  return [[p.day, 6, "BAD_DAY"], [p.start, 1439, "BAD_START"],
    [p.end, 1439, "BAD_END"], [p.break, 240, "BAD_BREAK"]];
}
function boundedIntegerError(v: number, hi: number, code: string, i: number): PayFailure | null {
  return validBoundedInteger(v, hi) ? null : failure(code, i);
}
function validBoundedInteger(v: number, hi: number): boolean {
  return Number.isInteger(v) && v >= 0 && v <= hi;
}
function validateFlags(p: PreparedShift): PayFailure | null {
  if (typeof p.holiday !== "boolean") return failure("BAD_HOLIDAY", p.index);
  return typeof p.callout === "boolean" ? null : failure("BAD_CALLOUT", p.index);
}
function validateLength(p: PreparedShift): PayFailure | null {
  return checkDuration(p, shiftDuration(p));
}
function shiftDuration(p: PreparedShift): number { return (p.end - p.start + 1440) % 1440 || 1440; }
function checkDuration(p: PreparedShift, d: number): PayFailure | null {
  if (d < 1 || d > 960) return failure("BAD_LENGTH", p.index);
  if (p.break > d) return failure("BREAK_TOO_LONG", p.index);
  return storeTimes(p, d);
}
function storeTimes(p: PreparedShift, d: number): null {
  p.duration = d; p.paid = d - (d > 360 ? p.break : 0);
  p.timeline = timelineStart(p); return null;
}
function timelineStart(p: PreparedShift): number { return p.day * 1440 + p.start; }
function overlap(rows: PreparedShift[]): PayFailure | null { return findOverlaps(rows); }
function findOverlaps(rows: PreparedShift[]): PayFailure | null {
  const hits: [number, number][] = [];
  for (let i = 0; i < rows.length; i++) checkShiftPairs(rows, i, hits);
  return chooseOverlap(hits);
}
function chooseOverlap(hits: [number, number][]): PayFailure | null {
  hits.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  return hits.length ? failure("OVERLAP", hits[0][1]) : null;
}
function checkShiftPairs(rows: PreparedShift[], i: number, hits: [number, number][]): void {
  for (let j = i + 1; j < rows.length; j++) checkOffsets(rows[i], rows[j], hits);
}
function checkOffsets(a: PreparedShift, b: PreparedShift, hits: [number, number][]): void {
  for (const n of [-10080, 0, 10080]) recordOverlap(a, b, n, hits);
}
function recordOverlap(
  a: PreparedShift, b: PreparedShift, n: number, hits: [number, number][],
): void {
  const lo = overlapStart(a, b, n), hi = overlapEnd(a, b, n);
  if (lo < hi) hits.push([lo, Math.max(a.index, b.index)]);
}
function overlapStart(a: PreparedShift, b: PreparedShift, n: number): number {
  return Math.max(a.timeline, b.timeline + n);
}
function overlapEnd(a: PreparedShift, b: PreparedShift, n: number): number {
  return Math.min(a.timeline + a.duration, b.timeline + n + b.duration);
}
function pay(r: string, rows: PreparedShift[], bonus: boolean): Record<string, unknown> {
  const out: ShiftResult[] = [], prior = collectShiftRows(r, rows, out);
  if (bonus && prior >= 600) addBonus(out[out.length - 1]);
  return assembleResult(out, prior);
}
function collectShiftRows(r: string, rows: PreparedShift[], out: ShiftResult[]): number {
  let prior = 0;
  for (const p of rows) { out.push(priceWorkedMinutes(r, p, prior)); prior += p.paid; }
  return prior;
}
function priceWorkedMinutes(r: string, p: PreparedShift, prior: number): ShiftResult {
  const row = emptyShiftResult(p);
  for (let k = 0; k < p.paid; k++) priceMinute(row, r, p, prior, k);
  addCalloutPay(row, r, p); return row;
}
function emptyShiftResult(p: PreparedShift): ShiftResult {
  return { day: p.day, start: p.start, end: p.end, paid_minutes: p.paid,
    regular_minutes: 0, overtime_minutes: 0, night_minutes: 0, weekend_minutes: 0,
    holiday_minutes: 0, callout_minutes: 0, bonus_cents: 0, cents: 0, daily: 0, weekly: 0 };
}
function priceMinute(
  row: ShiftResult, r: string, p: PreparedShift, prior: number, k: number,
): void {
  const f = classifyMinute(p, prior, k);
  recordMinuteFlags(row, f);
  row.cents += HOURLY_RATES[r] * minuteBaseUnits(f);
}
function recordMinuteFlags(row: ShiftResult, f: boolean[]): void {
  recordOvertimeFlags(row, f);
  row.regular_minutes += Number(!f[0]); row.overtime_minutes += Number(f[0]);
  row.night_minutes += Number(f[1]); row.weekend_minutes += Number(f[2]);
  row.holiday_minutes += Number(f[3]);
}
function recordOvertimeFlags(row: ShiftResult, f: boolean[]): void {
  row.daily ||= Number(f[4]); row.weekly ||= Number(f[5]);
}
function classifyMinute(p: PreparedShift, prior: number, k: number): boolean[] {
  const abs = p.timeline + p.duration - p.paid + k;
  return classifyMinuteFlags(abs, k, prior, p.holiday);
}
function classifyMinuteFlags(abs: number, k: number, prior: number, holiday: boolean): boolean[] {
  const [d, m] = minuteDayClock(abs);
  const daily = k >= 480, weekly = prior + k >= 2400;
  return [daily || weekly, isNightMinute(m), isWeekendMinute(d), holiday, daily, weekly];
}
function minuteDayClock(abs: number): [number, number] {
  return [Math.floor(abs / 1440) % 7, abs % 1440];
}
function isNightMinute(m: number): boolean { return m >= 1320 || m < 360; }
function isWeekendMinute(d: number): boolean { return d >= 5; }
function minuteBaseUnits(f: boolean[]): number {
  return 20 + 10 * Number(f[0]) + 4 * Number(f[1])
    + 5 * Number(f[2]) + 20 * Number(f[3]);
}
function addCalloutPay(row: ShiftResult, r: string, p: PreparedShift): void {
  row.callout_minutes = p.callout ? Math.max(0, 180 - p.paid) : 0;
  row.cents = roundHalfUp(row.cents + HOURLY_RATES[r] * row.callout_minutes * 20, 1200);
}
function roundHalfUp(n: number, d: number): number { return Math.floor((2 * n + d) / (2 * d)); }
function addBonus(row: ShiftResult): void { row.bonus_cents = 500; row.cents += 500; }
function assembleResult(rows: ShiftResult[], paid: number): Record<string, unknown> {
  return makeResult(rows, paid);
}
function makeResult(rows: ShiftResult[], paid: number): Record<string, unknown> {
  const clean = publicShiftRows(rows);
  return {
    shifts: clean, weekly_paid_minutes: paid,
    weekly_cents: sumShiftCents(clean), applied: activeRuleNames(rows),
  };
}
function publicShiftRows(rows: ShiftResult[]): Record<string, number>[] {
  return rows.map(({ daily: _d, weekly: _w, ...row }) => row);
}
function sumShiftCents(rows: Record<string, number>[]): number {
  return rows.reduce((n, x) => n + x.cents, 0);
}
function activeRuleNames(rows: ShiftResult[]): string[] {
  return APPLIED_RULES.filter(([k]) => rows.some((x) => x[k] > 0)).map(([, v]) => v);
}
