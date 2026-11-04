type RecordValue = Record<string, unknown>;
type R = RecordValue;
type D = R & { property_id: string; extras: string[]; bookings: B[]; promo_code: string };
type B = { property_id: string; arrival: number; departure: number };
type N = {
  day: number;
  season: string;
  base_cents: number;
  weekend_cents: number;
  night_cents: number;
};
type V = [number, number, number, number, number, number, number, number, number];

/** Quote a stay with seasonal rates, fees, discounts, and deposit. */
export function solution(request: RecordValue): RecordValue {
  const data = shape(request), error = verify(data);
  if (error) return error;
  const lines = rows(data), values = amounts(data, lines);
  return pack(data, lines, values);
}

function shape(x: R): D {
  return {
    ...x,
    property_id: prop(x.property_id),
    extras: ext(x.extras),
    bookings: books(x.bookings),
    promo_code: code(x.promo_code),
  } as D;
}
function prop(x: unknown): string {
  return typeof x === "string" ? x.trim().toUpperCase() : "";
}
function ext(x: unknown): string[] {
  return Array.isArray(x) ? x.map((v) => prop(v)) : [];
}
function books(x: unknown): B[] { return Array.isArray(x) ? x.map(book) : []; }
function book(x: R): B {
  return {
    property_id: prop(x.property_id),
    arrival: x.arrival as number,
    departure: x.departure as number,
  };
}
function code(x: unknown): string { return prop(x); }
function verify(x: D): R | null { return fields(x) || days(x) || lists(x) || rules(x); }
function fields(x: D): R | null { return property(x) || adults(x) || children(x); }
function property(x: D): R | null {
  return x.property_id === "CEDAR" || x.property_id === "LAKE"
    ? null
    : fail("BAD_PROPERTY", null);
}
function adults(x: D): R | null {
  const n = x.adults;
  return Number.isInteger(n) && (n as number) >= 1 && (n as number) <= 8
    ? null
    : fail("BAD_ADULTS", null);
}
function children(x: D): R | null {
  const n = x.children;
  return Number.isInteger(n) && (n as number) >= 0 && (n as number) <= 8
    ? null
    : fail("BAD_CHILDREN", null);
}
function days(x: D): R | null {
  return dayok(x.arrival, x.departure) ? null : fail("BAD_DAYS", null);
}
function dayok(a: unknown, b: unknown): boolean {
  return Number.isInteger(a) && Number.isInteger(b) && inDays(a, b)
    && (b as number) > (a as number);
}
function inDays(a: unknown, b: unknown): boolean {
  return (a as number) >= 0 && (b as number) >= 0
    && (a as number) <= 1_000_000 && (b as number) <= 1_000_000;
}
function lists(x: D): R | null { return extras(x.extras) || bookings(x.bookings); }
function extras(xs: string[]): R | null {
  return xs.length > 4 ? fail("BAD_EXTRA", null) : extraAt(xs, new Set());
}
function extraAt(xs: string[], seen: Set<string>): R | null {
  for (let i = 0; i < xs.length; i++) {
    if (badExtra(xs[i], seen)) return fail("BAD_EXTRA", i);
  }
  return null;
}
function badExtra(v: string, seen: Set<string>): boolean {
  if (v !== "PET" && v !== "PARKING" || seen.has(v)) return true;
  seen.add(v);
  return false;
}
function bookings(xs: B[]): R | null {
  return xs.length > 100 ? fail("BAD_BOOKING", null) : bookingAt(xs);
}
function bookingAt(xs: B[]): R | null {
  for (let i = 0; i < xs.length; i++) {
    if (badBooking(xs[i])) return fail("BAD_BOOKING", i);
  }
  return null;
}
function badBooking(b: B): boolean {
  return !b || !knownProperty(b.property_id) || !dayok(b.arrival, b.departure);
}
function knownProperty(x: string): boolean { return x === "CEDAR" || x === "LAKE"; }
function rules(x: D): R | null {
  return stay(x) || capacity(x) || minimum(x) || overlap(x) || promo(x);
}
function stay(x: D): R | null {
  const n = x.departure - x.arrival;
  return n >= 1 && n <= 30 ? null : fail("BAD_STAY", null);
}
function capacity(x: D): R | null {
  const cap = x.property_id === "CEDAR" ? 4 : 6;
  return (x.adults as number) + (x.children as number) <= cap
    ? null
    : fail("OVER_CAPACITY", null);
}
function minimum(x: D): R | null {
  const count = x.departure - x.arrival;
  return hasShort(seasons(x), count) ? fail("MIN_STAY", null) : null;
}
function seasons(x: D): Set<string> {
  const s = new Set<string>();
  for (let d = x.arrival; d < x.departure; d++) s.add(season(d));
  return s;
}
function hasShort(s: Set<string>, n: number): boolean {
  return s.has("LOW") && n < 1 || s.has("PEAK") && n < 3
    || s.has("SHOULDER") && n < 2;
}
function overlap(x: D): R | null {
  const i = x.bookings.findIndex((b) => isOverlap(x, b));
  return i < 0 ? null : fail("UNAVAILABLE", i);
}
function isOverlap(x: D, b: B): boolean {
  return b.property_id === x.property_id
    && x.arrival < b.departure && b.arrival < x.departure;
}
function promo(x: D): R | null {
  const codes = ["", "PCT10", "FIXED5000", "ONENIGHT"];
  return codes.includes(x.promo_code) ? null : fail("BAD_PROMO", null);
}
function rows(x: D): N[] { return daysIn(x.arrival, x.departure); }
function daysIn(a: number, b: number): N[] {
  const out: N[] = [];
  for (let d = a; d < b; d++) out.push(line(d));
  return out;
}
function line(d: number): N {
  const s = season(d), base = rate(s), weekend = wknd(d);
  return {
    day: d, season: s, base_cents: base,
    weekend_cents: weekend, night_cents: base + weekend,
  };
}
function season(d: number): string {
  const n = d % 365;
  return n < 120 ? "LOW" : n < 240 ? "PEAK" : "SHOULDER";
}
function rate(s: string): number {
  return s === "LOW" ? 5000 : s === "PEAK" ? 9000 : 6500;
}
function wknd(d: number): number { return d % 7 === 4 || d % 7 === 5 ? 1500 : 0; }
function amounts(x: D, ns: N[]): V { return price(x, ns, subtotal(ns)); }
function subtotal(ns: N[]): number { return ns.reduce((n, row) => n + row.night_cents, 0); }
function price(x: D, ns: N[], sub: number): V {
  const n = x.departure - x.arrival, f = fees(x, n);
  return quote(x, ns, sub, n, f);
}
function quote(x: D, ns: N[], sub: number, n: number, f: number[]): V {
  const pre = beforeDiscount(sub, f), long = discount(sub, n);
  return finishPrice(x, ns, n, f, pre, long);
}
function finishPrice(x: D, ns: N[], n: number, f: number[], pre: number, long: number): V {
  const cut = promoCut(x.promo_code, pre - long, ns);
  const total = afterDiscount(pre, long, cut);
  return [n, ...f, long, cut, total, deposit(total)];
}
function beforeDiscount(sub: number, f: number[]): number {
  return sub + f[0] + f[1] + f[2] + f[3];
}
function afterDiscount(pre: number, long: number, cut: number): number {
  return pre - long - cut;
}
function fees(x: D, n: number): [number, number, number, number] {
  return [4500, guest(x, n), tax(x, n), extraFee(x.extras, n)];
}
function guest(x: D, n: number): number {
  const adults = Math.max(0, (x.adults as number) - 2);
  return (adults * 2000 + (x.children as number) * 1000) * n;
}
function tax(x: D, n: number): number {
  const guests = (x.adults as number) + (x.children as number);
  return 800 * guests * Math.min(n, 5);
}
function extraFee(xs: string[], n: number): number {
  return xs.reduce((sum, v) => sum + extraCost(v, n), 0);
}
function extraCost(v: string, n: number): number { return v === "PARKING" ? 1200 * n : 2500; }
function discount(sub: number, n: number): number {
  return rhu(sub * discountRate(n), 100);
}
function discountRate(n: number): number { return n >= 14 ? 15 : n >= 7 ? 10 : 0; }
function promoCut(c: string, amount: number, ns: N[]): number {
  return c === "PCT10" ? percentCut(amount)
    : c === "FIXED5000" ? fixedCut(amount)
    : c === "ONENIGHT" ? oneNight(ns) : 0;
}
function percentCut(n: number): number { return rhu(n * 10, 100); }
function fixedCut(n: number): number { return Math.min(5000, n); }
function oneNight(ns: N[]): number { return Math.min(...ns.map((v) => v.night_cents)); }
function rhu(n: number, d: number): number { return Math.floor((2 * n + d) / (2 * d)); }
function deposit(n: number): number { return Math.min(n, Math.max(10000, rhu(n * 30, 100))); }
function pack(x: D, ns: N[], v: V): R { return record(x, ns, v); }
function record(x: D, ns: N[], v: V): R {
  return { ...amountFields(v), ...stayFields(x, ns), applied: applied(x, ns, v) };
}
function amountFields(v: V): R {
  const [n, cleaning, guests, tourist, extras, long, cut, total, dep] = v;
  return { nights: n, cleaning_fee: cleaning, extra_guest_fee: guests,
    tourist_tax: tourist, extras_fee: extras, long_stay_discount: long,
    promo_discount: cut, total, deposit: dep, balance_due: total - dep };
}
function stayFields(x: D, ns: N[]): R {
  return { night_lines: ns, cancellation: cancel(x.arrival) };
}
function applied(x: D, ns: N[], v: V): string[] {
  const flags = effectFlags(x, ns, v);
  return names(flags);
}
function effectFlags(x: D, ns: N[], v: V): boolean[] {
  return weekendFlags(ns).concat(baseFlags(v), extraFlags(x), discountFlags(v));
}
function weekendFlags(ns: N[]): boolean[] { return [ns.some((r) => r.weekend_cents > 0)]; }
function baseFlags(v: V): boolean[] { return [v[1] > 0, v[2] > 0, v[3] > 0]; }
function extraFlags(x: D): boolean[] {
  return [x.extras.includes("PARKING"), x.extras.includes("PET")];
}
function discountFlags(v: V): boolean[] { return [v[5] > 0, v[6] > 0, v[7] > 0]; }
function names(flags: boolean[]): string[] {
  const all = ["weekend", "cleaning", "extra-guests", "tourist-tax", "parking",
    "pet", "long-stay", "promo", "deposit"];
  return all.filter((_, i) => flags[i]);
}
function cancel(a: number): string { return a >= 30 ? "FLEX" : a >= 7 ? "STANDARD" : "FIRM"; }
function fail(error: string, index: number | null): R { return { error, index }; }
