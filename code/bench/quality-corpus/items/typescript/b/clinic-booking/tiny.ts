type R = Record<string, unknown>;
type Request = R & { doctors: R[]; bookings: R[]; holidays: unknown[] };
type D = R & { name: string; key: string; windows: R[] };
type B = R & { key: string };
type X = R & {
  doctors: D[]; bookings: B[]; holidays: unknown[]; kind: string;
  preferred_doctor: string; preferred_key: string;
};
type S = { day: number; start: number; end: number; name: string; key: string };
type E = { error: string; index: number | null };
const k: Record<string, [number, number]> = {
  checkup: [20, 5], consultation: [30, 10], procedure: [60, 15],
};
const t = [
  "normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
  "doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
  "earliest-grid-slot",
];

/** Return the earliest valid appointment or the first validation error. */
export function solution(request: Request): Record<string, unknown> {
  const data = a(request), issue = b(data);
  if (issue) return issue;
  const slot = ai(al(data).flatMap((day) => ak(data, day)));
  return slot ? d(slot) : e("NO_SLOT", null);
}
function a(x: R): X { return g(x); }
function g(x: R): X {
  const base = ca(x);
  return {
    ...base, kind: j(x.kind), preferred_doctor: l(x.preferred_doctor),
    preferred_key: m(x.preferred_doctor),
  } as X;
}
function ca(x: R): R {
  return {
    ...x, doctors: (x.doctors as R[]).map((row) => n(row)),
    bookings: (x.bookings as R[]).map((row) => o(row)),
    holidays: x.holidays as unknown[],
  };
}
function j(v: unknown): string {
  return typeof v === "string" ? v.trim().toLowerCase() : v as string;
}
function l(v: unknown): string { return typeof v === "string" ? v.trim() : v as string; }
function m(v: unknown): string { return p(v); }
function p(v: unknown): string {
  if (typeof v !== "string") return "";
  const s = v.trim();
  return s && /^[A-Za-z0-9 -]+$/.test(s) ? s.toLowerCase() : "";
}
function n(v: R): D {
  return { ...v, name: l(v.name), key: p(v.name), windows: v.windows as R[] } as D;
}
function o(v: R): B { return { ...v, doctor: l(v.doctor), key: p(v.doctor) }; }
function b(x: X): E | null {
  if (!q(x)) return e("BAD_REQUEST", null);
  for (const check of [r, s, u, v]) { const issue = check(x); if (issue) return issue; }
  return y(x);
}
function q(x: X): boolean { return z(x) && aa(x); }
function z(x: X): boolean {
  return [x.now_day, x.now_minute, x.requested_day, x.horizon_days]
    .every((v, i) => ab(v, [0, 0, 0, 0][i], [1000000, 1439, 1000000, 14][i]));
}
function aa(x: X): boolean {
  return typeof x.urgent === "boolean" && typeof x.kind === "string"
    && Object.hasOwn(k, x.kind) && typeof x.preferred_doctor === "string";
}
function ab(v: unknown, lo: number, hi: number): boolean {
  return typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi;
}
function r(x: X): E | null { return ac(x.doctors); }
function ac(rows: D[]): E | null {
  if (rows.length < 1 || rows.length > 12) return e("BAD_DOCTORS", null);
  return cc(rows);
}
function cc(rows: D[]): E | null {
  const seen = new Set<string>();
  for (let i = 0; i < rows.length; i++) {
    const key = rows[i].key;
    if (!key || seen.has(key)) return e("BAD_DOCTORS", i);
    seen.add(key);
  }
  return null;
}
function s(x: X): E | null { return ad(x.doctors); }
function ad(rows: D[]): E | null {
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].windows.length > 8 || !rows[i].windows.every((window) => ae(window))) {
      return e("BAD_WINDOW", i);
    }
  }
  return null;
}
function ae(v: R): boolean {
  return ab(v.weekday, 0, 6) && ab(v.open, 0, 1440) && ab(v.close, 0, 1440)
    && (v.open as number) < (v.close as number);
}
function u(x: X): E | null { return af(x.holidays); }
function af(rows: unknown[]): E | null {
  if (rows.length > 60) return e("BAD_HOLIDAY", null);
  return cd(rows);
}
function cd(rows: unknown[]): E | null {
  return cl(rows);
}
function cl(rows: unknown[]): E | null {
  const seen = new Set<unknown>();
  for (let i = 0; i < rows.length; i++) {
    if (!cm(rows[i], seen)) return e("BAD_HOLIDAY", i);
  }
  return null;
}
function cm(day: unknown, seen: Set<unknown>): boolean {
  if (!ab(day, 0, 1000000) || seen.has(day)) return false;
  seen.add(day);
  return true;
}
function v(x: X): E | null { return ag(x); }
function ag(x: X): E | null {
  if (x.bookings.length > 200) return e("BAD_BOOKING", null);
  return ce(x);
}
function ce(x: X): E | null {
  const names = new Set(x.doctors.map((doctor) => doctor.key));
  for (let i = 0; i < x.bookings.length; i++) {
    const row = x.bookings[i];
    if (!ah(row, names)) return e("BAD_BOOKING", i);
  }
  return null;
}
function ah(v: B, names: Set<string>): boolean {
  return ab(v.day, 0, 1000000) && ab(v.start, 0, 1440) && ab(v.end, 0, 1440)
    && (v.start as number) < (v.end as number) && names.has(v.key);
}
function y(x: X): E | null {
  const names = new Set(x.doctors.map((doctor) => doctor.key));
  if (x.preferred_doctor && !names.has(x.preferred_key)) return e("UNKNOWN_DOCTOR", null);
  return cf(x);
}
function cf(x: X): E | null {
  return x.requested_day >= (x.now_day as number)
    && x.requested_day <= (x.now_day as number) + 8 ? null : e("BAD_DAY_ORDER", null);
}
function ak(x: X, day: number): S[] {
  const slots: S[] = [];
  for (const start of ap()) for (const doctor of x.doctors) {
    if (!ar(x, doctor)) continue;
    const slot = ci(x, day, start, doctor);
    if (slot) slots.push(slot);
  }
  return slots;
}
function al(x: X): number[] {
  const first = x.requested_day as number;
  const last = Math.min(first + (x.horizon_days as number), first + 14, 1000000);
  return Array.from({ length: last - first + 1 }, (_, i) => first + i).filter((day) => !an(x, day));
}
function an(x: X, day: number): boolean { return x.holidays.includes(day); }
function ap(): number[] { return Array.from({ length: 288 }, (_, i) => i * 5); }
function ar(x: X, doctor: D): boolean {
  return x.urgent || !x.preferred_doctor || doctor.key === x.preferred_key;
}
function ci(
  x: X, day: number, start: number, doctor: D,
): S | null {
  const [duration, buffer] = k[x.kind];
  const end = start + duration, occupied = end + buffer;
  return co(x, day, start, end, occupied, doctor);
}
function co(x: X, day: number, start: number, end: number, occupied: number, doctor: D): S | null {
  const [weekday, bookings] = ct(x, day, doctor);
  return cr(x, day, start, occupied, weekday, bookings, doctor)
    ? cp(day, start, end, doctor) : null;
}
function ct(x: X, day: number, doctor: D): [number, B[]] {
  return [day % 7, x.bookings.filter((row) => row.day === day && row.key === doctor.key)];
}
function cr(
  x: X, day: number, start: number, end: number, weekday: number,
  bookings: B[], doctor: D,
): boolean {
  return ay(doctor, weekday, start, end) && az(weekday, start, end)
    && ch(x, day, start, end, bookings);
}
function cp(day: number, start: number, end: number, doctor: D): S {
  return { day, start, end, name: doctor.name, key: doctor.key };
}
function ch(
  x: X, day: number, start: number, end: number, bookings: B[],
): boolean {
  return av(x, day, start)
    && aw(bookings) && ax(start, end, bookings);
}
function ay(doctor: D, day: number, start: number, end: number): boolean {
  return doctor.windows.some((w) => w.weekday === day
    && (w.open as number) <= start && end <= (w.close as number));
}
function az(day: number, start: number, end: number): boolean {
  return ba(day, start, end) && !bb(start, end);
}
function ba(day: number, start: number, end: number): boolean {
  const open = day === 5 ? 600 : day === 6 ? 0 : 540;
  const close = day === 5 ? 840 : day === 6 ? 0 : 1020;
  return open <= start && end <= close;
}
function bb(start: number, end: number): boolean { return start < 780 && end > 720; }
function av(x: X, day: number, start: number): boolean {
  return day > (x.now_day as number) || start >= (x.now_minute as number) + 60;
}
function aw(rows: B[]): boolean { return rows.length < 4; }
function ax(start: number, end: number, rows: B[]): boolean {
  return rows.every((row) => start >= (row.end as number) || end <= (row.start as number));
}
function ai(rows: S[]): S | null { return rows.sort((a, b) => bc(a, b))[0] ?? null; }
function bc(a: S, b: S): number {
  return a.day - b.day || a.start - b.start
    || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
}
function d(slot: S): R { return bd(slot); }
function bd(slot: S): R {
  return { day: slot.day, start: slot.start, end: slot.end, doctor: slot.name, trace: t };
}
function e(code: string, index: number | null): E { return be(code, index); }
function be(code: string, index: number | null): E { return { error: code, index }; }
