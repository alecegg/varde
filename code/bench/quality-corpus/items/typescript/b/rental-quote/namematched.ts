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
  const data = normalizeRequest(request), error = validateRequest(data);
  if (error) return error;
  const lines = buildNightRows(data), values = calculateAmounts(data, lines);
  return assembleQuote(data, lines, values);
}

function normalizeRequest(x: R): D {
  return {
    ...x,
    property_id: normalizeText(x.property_id),
    extras: normalizeExtra(x.extras),
    bookings: normalizeBookings(x.bookings),
    promo_code: normalizePromoCode(x.promo_code),
  } as D;
}
function normalizeText(x: unknown): string {
  return typeof x === "string" ? x.trim().toUpperCase() : "";
}
function normalizeExtra(x: unknown): string[] {
  return Array.isArray(x) ? x.map((v) => normalizeText(v)) : [];
}
function normalizeBookings(x: unknown): B[] {
  return Array.isArray(x) ? x.map(normalizeBooking) : [];
}
function normalizeBooking(x: R): B {
  return {
    property_id: normalizeText(x.property_id),
    arrival: x.arrival as number,
    departure: x.departure as number,
  };
}
function normalizePromoCode(x: unknown): string { return normalizeText(x); }
function validateRequest(x: D): R | null {
  return validateFields(x) || validateDays(x) || validateLists(x) || validateStayRules(x);
}
function validateFields(x: D): R | null {
  return validateProperty(x) || validateAdults(x) || validateChildren(x);
}
function validateProperty(x: D): R | null {
  return x.property_id === "CEDAR" || x.property_id === "LAKE"
    ? null
    : errorRecord("BAD_PROPERTY", null);
}
function validateAdults(x: D): R | null {
  const n = x.adults;
  return Number.isInteger(n) && (n as number) >= 1 && (n as number) <= 8
    ? null
    : errorRecord("BAD_ADULTS", null);
}
function validateChildren(x: D): R | null {
  const n = x.children;
  return Number.isInteger(n) && (n as number) >= 0 && (n as number) <= 8
    ? null
    : errorRecord("BAD_CHILDREN", null);
}
function validateDays(x: D): R | null {
  return validDayRange(x.arrival, x.departure) ? null : errorRecord("BAD_DAYS", null);
}
function validDayRange(a: unknown, b: unknown): boolean {
  return Number.isInteger(a) && Number.isInteger(b) && daysInRange(a, b)
    && (b as number) > (a as number);
}
function daysInRange(a: unknown, b: unknown): boolean {
  return (a as number) >= 0 && (b as number) >= 0
    && (a as number) <= 1_000_000 && (b as number) <= 1_000_000;
}
function validateLists(x: D): R | null {
  return validateExtras(x.extras) || validateBookings(x.bookings);
}
function validateExtras(xs: string[]): R | null {
  return xs.length > 4 ? errorRecord("BAD_EXTRA", null) : validateExtraItems(xs, new Set());
}
function validateExtraItems(xs: string[], seen: Set<string>): R | null {
  for (let i = 0; i < xs.length; i++) {
    if (invalidExtra(xs[i], seen)) return errorRecord("BAD_EXTRA", i);
  }
  return null;
}
function invalidExtra(v: string, seen: Set<string>): boolean {
  if (v !== "PET" && v !== "PARKING" || seen.has(v)) return true;
  seen.add(v);
  return false;
}
function validateBookings(xs: B[]): R | null {
  return xs.length > 100 ? errorRecord("BAD_BOOKING", null) : validateBookingItems(xs);
}
function validateBookingItems(xs: B[]): R | null {
  for (let i = 0; i < xs.length; i++) {
    if (invalidBooking(xs[i])) return errorRecord("BAD_BOOKING", i);
  }
  return null;
}
function invalidBooking(b: B): boolean {
  return !b || !propertyIsSupported(b.property_id) || !validDayRange(b.arrival, b.departure);
}
function propertyIsSupported(x: string): boolean { return x === "CEDAR" || x === "LAKE"; }
function validateStayRules(x: D): R | null {
  return validateStay(x) || validateCapacity(x) || validateMinimumStay(x)
    || validateAvailability(x) || validatePromo(x);
}
function validateStay(x: D): R | null {
  const n = x.departure - x.arrival;
  return n >= 1 && n <= 30 ? null : errorRecord("BAD_STAY", null);
}
function validateCapacity(x: D): R | null {
  const cap = x.property_id === "CEDAR" ? 4 : 6;
  return (x.adults as number) + (x.children as number) <= cap
    ? null
    : errorRecord("OVER_CAPACITY", null);
}
function validateMinimumStay(x: D): R | null {
  const count = x.departure - x.arrival;
  return hasShortSeason(occupiedSeasons(x), count) ? errorRecord("MIN_STAY", null) : null;
}
function occupiedSeasons(x: D): Set<string> {
  const s = new Set<string>();
  for (let d = x.arrival; d < x.departure; d++) s.add(seasonForDay(d));
  return s;
}
function hasShortSeason(s: Set<string>, n: number): boolean {
  return s.has("LOW") && n < 1 || s.has("PEAK") && n < 3
    || s.has("SHOULDER") && n < 2;
}
function validateAvailability(x: D): R | null {
  const i = x.bookings.findIndex((b) => bookingOverlaps(x, b));
  return i < 0 ? null : errorRecord("UNAVAILABLE", i);
}
function bookingOverlaps(x: D, b: B): boolean {
  return b.property_id === x.property_id
    && x.arrival < b.departure && b.arrival < x.departure;
}
function validatePromo(x: D): R | null {
  const codes = ["", "PCT10", "FIXED5000", "ONENIGHT"];
  return codes.includes(x.promo_code) ? null : errorRecord("BAD_PROMO", null);
}
function buildNightRows(x: D): N[] { return enumerateDays(x.arrival, x.departure); }
function enumerateDays(a: number, b: number): N[] {
  const out: N[] = [];
  for (let d = a; d < b; d++) out.push(buildNightLine(d));
  return out;
}
function buildNightLine(d: number): N {
  const s = seasonForDay(d), base = baseRate(s), weekend = weekendSurcharge(d);
  return {
    day: d, season: s, base_cents: base,
    weekend_cents: weekend, night_cents: base + weekend,
  };
}
function seasonForDay(d: number): string {
  const n = d % 365;
  return n < 120 ? "LOW" : n < 240 ? "PEAK" : "SHOULDER";
}
function baseRate(s: string): number {
  return s === "LOW" ? 5000 : s === "PEAK" ? 9000 : 6500;
}
function weekendSurcharge(d: number): number { return d % 7 === 4 || d % 7 === 5 ? 1500 : 0; }
function calculateAmounts(x: D, ns: N[]): V { return calculatePrice(x, ns, nightSubtotal(ns)); }
function nightSubtotal(ns: N[]): number { return ns.reduce((n, row) => n + row.night_cents, 0); }
function calculatePrice(x: D, ns: N[], sub: number): V {
  const n = x.departure - x.arrival, f = calculateFees(x, n);
  return assemblePrice(x, ns, sub, n, f);
}
function assemblePrice(x: D, ns: N[], sub: number, n: number, f: number[]): V {
  const pre = amountBeforeDiscount(sub, f), long = calculateLongStayDiscount(sub, n);
  return finishPriceValues(x, ns, n, f, pre, long);
}
function finishPriceValues(x: D, ns: N[], n: number, f: number[], pre: number, long: number): V {
  const cut = calculatePromoDiscount(x.promo_code, pre - long, ns);
  const total = amountAfterDiscount(pre, long, cut);
  return [n, ...f, long, cut, total, calculateDeposit(total)];
}
function amountBeforeDiscount(sub: number, f: number[]): number {
  return sub + f[0] + f[1] + f[2] + f[3];
}
function amountAfterDiscount(pre: number, long: number, cut: number): number {
  return pre - long - cut;
}
function calculateFees(x: D, n: number): [number, number, number, number] {
  return [4500, guestFee(x, n), touristTax(x, n), calculateExtraFee(x.extras, n)];
}
function guestFee(x: D, n: number): number {
  const adults = Math.max(0, (x.adults as number) - 2);
  return (adults * 2000 + (x.children as number) * 1000) * n;
}
function touristTax(x: D, n: number): number {
  const guests = (x.adults as number) + (x.children as number);
  return 800 * guests * Math.min(n, 5);
}
function calculateExtraFee(xs: string[], n: number): number {
  return xs.reduce((sum, v) => sum + extraCostForStay(v, n), 0);
}
function extraCostForStay(v: string, n: number): number {
  return v === "PARKING" ? 1200 * n : 2500;
}
function calculateLongStayDiscount(sub: number, n: number): number {
  return roundHalfUp(sub * longStayRate(n), 100);
}
function longStayRate(n: number): number { return n >= 14 ? 15 : n >= 7 ? 10 : 0; }
function calculatePromoDiscount(c: string, amount: number, ns: N[]): number {
  return c === "PCT10" ? percentageDiscount(amount)
    : c === "FIXED5000" ? fixedDiscount(amount)
    : c === "ONENIGHT" ? cheapestNight(ns) : 0;
}
function percentageDiscount(n: number): number { return roundHalfUp(n * 10, 100); }
function fixedDiscount(n: number): number { return Math.min(5000, n); }
function cheapestNight(ns: N[]): number { return Math.min(...ns.map((v) => v.night_cents)); }
function roundHalfUp(n: number, d: number): number {
  return Math.floor((2 * n + d) / (2 * d));
}
function calculateDeposit(n: number): number {
  return Math.min(n, Math.max(10000, roundHalfUp(n * 30, 100)));
}
function assembleQuote(x: D, ns: N[], v: V): R { return quoteRecord(x, ns, v); }
function quoteRecord(x: D, ns: N[], v: V): R {
  return {
    ...quoteAmountFields(v), ...quoteStayFields(x, ns), applied: appliedRules(x, ns, v),
  };
}
function quoteAmountFields(v: V): R {
  const [n, cleaning, guests, tourist, extras, long, cut, total, dep] = v;
  return { nights: n, cleaning_fee: cleaning, extra_guest_fee: guests,
    tourist_tax: tourist, extras_fee: extras, long_stay_discount: long,
    promo_discount: cut, total, deposit: dep, balance_due: total - dep };
}
function quoteStayFields(x: D, ns: N[]): R {
  return { night_lines: ns, cancellation: cancellationFor(x.arrival) };
}
function appliedRules(x: D, ns: N[], v: V): string[] {
  const flags = quoteEffectFlags(x, ns, v);
  return appliedNames(flags);
}
function quoteEffectFlags(x: D, ns: N[], v: V): boolean[] {
  return weekendEffectFlags(ns).concat(
    baseEffectFlags(v), extraEffectFlags(x), discountEffectFlags(v),
  );
}
function weekendEffectFlags(ns: N[]): boolean[] { return [ns.some((r) => r.weekend_cents > 0)]; }
function baseEffectFlags(v: V): boolean[] { return [v[1] > 0, v[2] > 0, v[3] > 0]; }
function extraEffectFlags(x: D): boolean[] {
  return [x.extras.includes("PARKING"), x.extras.includes("PET")];
}
function discountEffectFlags(v: V): boolean[] { return [v[5] > 0, v[6] > 0, v[7] > 0]; }
function appliedNames(flags: boolean[]): string[] {
  const all = ["weekend", "cleaning", "extra-guests", "tourist-tax", "parking",
    "pet", "long-stay", "promo", "deposit"];
  return all.filter((_, i) => flags[i]);
}
function cancellationFor(a: number): string {
  return a >= 30 ? "FLEX" : a >= 7 ? "STANDARD" : "FIRM";
}
function errorRecord(error: string, index: number | null): R { return { error, index }; }
