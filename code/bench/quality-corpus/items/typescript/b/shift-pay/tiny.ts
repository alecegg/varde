type Shift = {
  day: number; start: number; end: number; break: number; holiday: boolean; callout: boolean;
};
type Request = { role: string; shifts: Shift[]; bonus: boolean };
type P = Shift & { index: number; duration: number; paid: number; timeline: number };
type R = Record<string, number> & { daily: number; weekly: number };
type E = { error: string; index: number | null };
const A = { helper: 1800, nurse: 2400, lead: 3000 };
const B = [
  ["daily", "daily-overtime"], ["weekly", "weekly-overtime"],
  ["night_minutes", "night-premium"], ["weekend_minutes", "weekend-premium"],
  ["holiday_minutes", "holiday-rate"], ["callout_minutes", "callout-minimum"],
  ["bonus_cents", "bonus"],
] as const;

/** Return ordered shift pay rows or the first contract validation error. */
export function solution(request: Request): Record<string, unknown> {
  const role = norm(request.role), issue = req(role, request.shifts, request.bonus);
  if (issue) return issue;
  const rows = spans(request.shifts), invalid = check(rows);
  if (invalid) return invalid;
  return clash(rows) || price(role, rows, request.bonus);
}
function norm(v: string): string { return v.trim().toLowerCase(); }
function req(r: string, rows: Shift[], b: boolean): E | null { return reqs(r, rows, b); }
function reqs(r: string, rows: Shift[], b: boolean): E | null {
  if (!Object.hasOwn(A, r)) return err("BAD_ROLE", null);
  return requestRows(rows) || (typeof b === "boolean" ? null : err("BAD_BONUS", null));
}
function requestRows(rows: Shift[]): E | null {
  return rows.length ? rowLimit(rows) : err("EMPTY_WEEK", null);
}
function rowLimit(rows: Shift[]): E | null {
  return rows.length <= 14 ? null : err("TOO_MANY_SHIFTS", null);
}
function err(c: string, i: number | null): E { return { error: c, index: i }; }
function spans(rows: Shift[]): P[] { return rows.map((s, i) => span(s, i)); }
function span(s: Shift, i: number): P {
  return { ...s, index: i, duration: 0, paid: 0, timeline: 0 };
}
function check(rows: P[]): E | null { return checks(rows); }
function checks(rows: P[]): E | null {
  for (const p of rows) { const e = rowError(p); if (e) return e; }
  return null;
}
function rowError(p: P): E | null {
  return ints(p) || flags(p) || length(p);
}
function ints(p: P): E | null {
  for (const [v, hi, code] of intFields(p)) {
    const failure = integerError(v, hi, code, p.index);
    if (failure) return failure;
  }
  return null;
}
function intFields(p: P): readonly [number, number, string][] {
  return [[p.day, 6, "BAD_DAY"], [p.start, 1439, "BAD_START"],
    [p.end, 1439, "BAD_END"], [p.break, 240, "BAD_BREAK"]];
}
function integerError(v: number, hi: number, code: string, i: number): E | null {
  return validInt(v, hi) ? null : err(code, i);
}
function validInt(v: number, hi: number): boolean {
  return Number.isInteger(v) && v >= 0 && v <= hi;
}
function flags(p: P): E | null {
  if (typeof p.holiday !== "boolean") return err("BAD_HOLIDAY", p.index);
  return typeof p.callout === "boolean" ? null : err("BAD_CALLOUT", p.index);
}
function length(p: P): E | null { return lengthCheck(p, duration(p)); }
function duration(p: P): number { return (p.end - p.start + 1440) % 1440 || 1440; }
function lengthCheck(p: P, d: number): E | null {
  if (d < 1 || d > 960) return err("BAD_LENGTH", p.index);
  if (p.break > d) return err("BREAK_TOO_LONG", p.index);
  return store(p, d);
}
function store(p: P, d: number): null {
  p.duration = d; p.paid = d - (d > 360 ? p.break : 0); p.timeline = clock(p); return null;
}
function clock(p: P): number { return p.day * 1440 + p.start; }
function clash(rows: P[]): E | null { return clashes(rows); }
function clashes(rows: P[]): E | null {
  const hits: [number, number][] = [];
  for (let i = 0; i < rows.length; i++) pairHits(rows, i, hits);
  return overlapResult(hits);
}
function overlapResult(hits: [number, number][]): E | null {
  hits.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  return hits.length ? err("OVERLAP", hits[0][1]) : null;
}
function pairHits(rows: P[], i: number, hits: [number, number][]): void {
  for (let j = i + 1; j < rows.length; j++) hitOffsets(rows[i], rows[j], hits);
}
function hitOffsets(a: P, b: P, hits: [number, number][]): void {
  for (const n of [-10080, 0, 10080]) hit(a, b, n, hits);
}
function hit(a: P, b: P, n: number, hits: [number, number][]): void {
  const lo = startAt(a, b, n), hi = endAt(a, b, n);
  if (lo < hi) hits.push([lo, Math.max(a.index, b.index)]);
}
function startAt(a: P, b: P, n: number): number { return Math.max(a.timeline, b.timeline + n); }
function endAt(a: P, b: P, n: number): number {
  return Math.min(a.timeline + a.duration, b.timeline + n + b.duration);
}
function price(r: string, rows: P[], bonus: boolean): Record<string, unknown> {
  const out: R[] = [], prior = collect(r, rows, out);
  if (bonus && prior >= 600) award(out[out.length - 1]);
  return finish(out, prior);
}
function collect(r: string, rows: P[], out: R[]): number {
  let prior = 0;
  for (const p of rows) { out.push(minutes(r, p, prior)); prior += p.paid; }
  return prior;
}
function minutes(r: string, p: P, prior: number): R {
  const row = emptyRow(p);
  for (let k = 0; k < p.paid; k++) minute(row, r, p, prior, k);
  top(row, r, p); return row;
}
function emptyRow(p: P): R {
  return { day: p.day, start: p.start, end: p.end, paid_minutes: p.paid,
    regular_minutes: 0, overtime_minutes: 0, night_minutes: 0, weekend_minutes: 0,
    holiday_minutes: 0, callout_minutes: 0, bonus_cents: 0, cents: 0, daily: 0, weekly: 0 };
}
function minute(row: R, r: string, p: P, prior: number, k: number): void {
  const f = minuteFlags(p, prior, k);
  recordFlags(row, f);
  row.cents += A[r] * minuteUnits(f);
}
function recordFlags(row: R, f: boolean[]): void {
  recordOvertime(row, f);
  row.regular_minutes += Number(!f[0]); row.overtime_minutes += Number(f[0]);
  row.night_minutes += Number(f[1]); row.weekend_minutes += Number(f[2]);
  row.holiday_minutes += Number(f[3]);
}
function recordOvertime(row: R, f: boolean[]): void {
  row.daily ||= Number(f[4]); row.weekly ||= Number(f[5]);
}
function minuteFlags(p: P, prior: number, k: number): boolean[] {
  const abs = p.timeline + p.duration - p.paid + k;
  return classify(abs, k, prior, p.holiday);
}
function classify(abs: number, k: number, prior: number, holiday: boolean): boolean[] {
  const [d, m] = dayClock(abs);
  const daily = k >= 480, weekly = prior + k >= 2400;
  return [daily || weekly, nightAt(m), weekendAt(d), holiday, daily, weekly];
}
function dayClock(abs: number): [number, number] {
  return [Math.floor(abs / 1440) % 7, abs % 1440];
}
function nightAt(m: number): boolean { return m >= 1320 || m < 360; }
function weekendAt(d: number): boolean { return d >= 5; }
function minuteUnits(f: boolean[]): number {
  return 20 + 10 * Number(f[0]) + 4 * Number(f[1])
    + 5 * Number(f[2]) + 20 * Number(f[3]);
}
function top(row: R, r: string, p: P): void {
  row.callout_minutes = p.callout ? Math.max(0, 180 - p.paid) : 0;
  row.cents = round(row.cents + A[r] * row.callout_minutes * 20, 1200);
}
function round(n: number, d: number): number { return Math.floor((2 * n + d) / (2 * d)); }
function award(row: R): void { row.bonus_cents = 500; row.cents += 500; }
function finish(rows: R[], paid: number): Record<string, unknown> { return result(rows, paid); }
function result(rows: R[], paid: number): Record<string, unknown> {
  const clean = publicRows(rows);
  return {
    shifts: clean, weekly_paid_minutes: paid,
    weekly_cents: totalCents(clean), applied: active(rows),
  };
}
function publicRows(rows: R[]): Record<string, number>[] {
  return rows.map(({ daily: _d, weekly: _w, ...row }) => row);
}
function totalCents(rows: Record<string, number>[]): number {
  return rows.reduce((n, x) => n + x.cents, 0);
}
function active(rows: R[]): string[] {
  return B.filter(([k]) => rows.some((x) => x[k] > 0)).map(([, v]) => v);
}
