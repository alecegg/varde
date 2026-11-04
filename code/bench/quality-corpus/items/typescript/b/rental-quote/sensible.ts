type RecordValue = Record<string, unknown>;
type ErrorValue = { error: string; index: number | null };
type Booking = { property_id: string; arrival: number; departure: number };
type Night = {
  day: number;
  season: string;
  base_cents: number;
  weekend_cents: number;
  night_cents: number;
};
type QuoteData = {
  property_id: string;
  arrival: number;
  departure: number;
  adults: number;
  children: number;
  extras: string[];
  bookings: Booking[];
  promo_code: string;
};
type Price = {
  cleaning: number;
  guests: number;
  tax: number;
  extras: number;
  long: number;
  promo: number;
  total: number;
  deposit: number;
};
type Fees = { cleaning: number; guests: number; tax: number; extras: number; pre: number };

/** Quote a stay with seasonal rates, fees, discounts, and deposit. */
export function solution(request: RecordValue): RecordValue {
  const data = normalise(request);
  const error = validateRequest(data);
  if (error) return error;
  const nights = buildNights(data);
  const price = priceStay(data, nights);
  return assemble(data, nights, price);
}

function normalise(request: RecordValue): QuoteData {
  const extras = (request.extras as string[]).map((item) => item.trim().toUpperCase());
  const bookings = (request.bookings as RecordValue[]).map((row) => ({
    property_id: (row.property_id as string).trim().toUpperCase(),
    arrival: row.arrival as number,
    departure: row.departure as number,
  }));
  return {
    ...request,
    property_id: (request.property_id as string).trim().toUpperCase(),
    promo_code: (request.promo_code as string).trim().toUpperCase(),
    extras,
    bookings,
  } as QuoteData;
}

function validateRequest(data: QuoteData): ErrorValue | null {
  const checks = [
    () => validateIdentity(data),
    () => validateDays(data),
    () => validateExtras(data.extras),
    () => validateBookings(data.bookings),
    () => validateStay(data),
    () => validateMinimums(data, data.departure - data.arrival),
    () => validateAvailability(data),
  ];
  for (const check of checks) {
    const error = check();
    if (error) return error;
  }
  return validatePromo(data.promo_code);
}

function validatePromo(code: string): ErrorValue | null {
  return ["", "PCT10", "FIXED5000", "ONENIGHT"].includes(code)
    ? null : { error: "BAD_PROMO", index: null };
}

function validateStay(data: QuoteData): ErrorValue | null {
  const nights = data.departure - data.arrival;
  if (nights < 1 || nights > 30) return { error: "BAD_STAY", index: null };
  return data.adults + data.children <= (data.property_id === "CEDAR" ? 4 : 6)
    ? null : { error: "OVER_CAPACITY", index: null };
}

function validateAvailability(data: QuoteData): ErrorValue | null {
  const overlap = data.bookings.findIndex((row) =>
    row.property_id === data.property_id
      && data.arrival < row.departure
      && row.arrival < data.departure
  );
  return overlap < 0 ? null : { error: "UNAVAILABLE", index: overlap };
}

function validateIdentity(data: QuoteData): ErrorValue | null {
  if (data.property_id !== "CEDAR" && data.property_id !== "LAKE") {
    return { error: "BAD_PROPERTY", index: null };
  }
  if (!Number.isInteger(data.adults) || data.adults < 1 || data.adults > 8) {
    return { error: "BAD_ADULTS", index: null };
  }
  if (!Number.isInteger(data.children) || data.children < 0 || data.children > 8) {
    return { error: "BAD_CHILDREN", index: null };
  }
  return null;
}

function validateDays(data: QuoteData): ErrorValue | null {
  const { arrival, departure } = data;
  const integers = Number.isInteger(arrival) && Number.isInteger(departure);
  const inRange = arrival >= 0 && departure >= 0 && arrival <= 1_000_000 && departure <= 1_000_000;
  return integers && inRange && departure > arrival ? null : { error: "BAD_DAYS", index: null };
}

function validateExtras(extras: string[]): ErrorValue | null {
  if (extras.length > 4) return { error: "BAD_EXTRA", index: null };
  const seen = new Set<string>();
  for (let index = 0; index < extras.length; index++) {
    const item = extras[index];
    if ((item !== "PARKING" && item !== "PET") || seen.has(item)) {
      return { error: "BAD_EXTRA", index };
    }
    seen.add(item);
  }
  return null;
}

function validateBookings(bookings: Booking[]): ErrorValue | null {
  if (bookings.length > 100) return { error: "BAD_BOOKING", index: null };
  for (let index = 0; index < bookings.length; index++) {
    const row = bookings[index];
    if ((row.property_id !== "CEDAR" && row.property_id !== "LAKE")
      || !Number.isInteger(row.arrival) || !Number.isInteger(row.departure)
      || row.arrival < 0 || row.arrival > 1_000_000
      || row.departure > 1_000_000 || row.departure <= row.arrival)
      return { error: "BAD_BOOKING", index };
  }
  return null;
}

function validateMinimums(data: QuoteData, nights: number): ErrorValue | null {
  const occupied = { LOW: false, PEAK: false, SHOULDER: false };
  for (let day = data.arrival; day < data.departure; day++) {
    const phase = day % 365;
    if (phase < 120) occupied.LOW = true;
    else if (phase < 240) occupied.PEAK = true;
    else occupied.SHOULDER = true;
  }
  if (occupied.PEAK && nights < 3) return { error: "MIN_STAY", index: null };
  if (occupied.SHOULDER && nights < 2) return { error: "MIN_STAY", index: null };
  return null;
}

function buildNights(data: QuoteData): Night[] {
  const result: Night[] = [];
  for (let day = data.arrival; day < data.departure; day++) {
    const phase = day % 365, season = phase < 120 ? "LOW" : phase < 240 ? "PEAK" : "SHOULDER";
    const base = season === "LOW" ? 5000 : season === "PEAK" ? 9000 : 6500;
    const weekend = day % 7 === 4 || day % 7 === 5 ? 1500 : 0;
    result.push({
      day,
      season,
      base_cents: base,
      weekend_cents: weekend,
      night_cents: base + weekend,
    });
  }
  return result;
}

function priceStay(data: QuoteData, nights: Night[]): Price {
  const count = data.departure - data.arrival;
  const subtotal = nights.reduce((sum, row) => sum + row.night_cents, 0);
  const fees = baseFees(data, count, subtotal);
  return discountedPrice(data, nights, fees, subtotal, count);
}

function baseFees(data: QuoteData, count: number, subtotal: number): Fees {
  const cleaning = 4500;
  const guests = (Math.max(0, data.adults - 2) * 2000 + data.children * 1000) * count;
  const tax = 800 * (data.adults + data.children) * Math.min(count, 5);
  const extraTotal = data.extras.reduce(
    (sum, item) => sum + (item === "PARKING" ? 1200 * count : 2500),
    0,
  );
  return { cleaning, guests, tax, extras: extraTotal,
    pre: subtotal + cleaning + guests + tax + extraTotal };
}

function discountedPrice(
  data: QuoteData,
  nights: Night[],
  fees: Fees,
  subtotal: number,
  count: number,
): Price {
  const long = count >= 14 ? rhu(subtotal * 15, 100) : count >= 7 ? rhu(subtotal * 10, 100) : 0;
  const afterLong = fees.pre - long;
  const promo = promoCut(data.promo_code, afterLong, nights);
  const total = afterLong - promo, deposit = Math.min(total, Math.max(10000, rhu(total * 30, 100)));
  return { cleaning: fees.cleaning, guests: fees.guests, tax: fees.tax, extras: fees.extras,
    long, promo, total, deposit };
}

function promoCut(code: string, amount: number, nights: Night[]): number {
  if (code === "PCT10") return Math.floor((2 * amount * 10 + 100) / 200);
  if (code === "FIXED5000") return Math.min(5000, amount);
  return code === "ONENIGHT" ? Math.min(...nights.map((row) => row.night_cents)) : 0;
}

function assemble(data: QuoteData, nights: Night[], price: Price): RecordValue {
  const applied = [
    ...baseAppliedRules(data, nights, price),
    ...discountAppliedRules(price),
  ];
  const cancellation = data.arrival >= 30 ? "FLEX" : data.arrival >= 7 ? "STANDARD" : "FIRM";
  return { nights: nights.length, night_lines: nights, cleaning_fee: price.cleaning,
    extra_guest_fee: price.guests, tourist_tax: price.tax, extras_fee: price.extras,
    long_stay_discount: price.long, promo_discount: price.promo, total: price.total,
    deposit: price.deposit, balance_due: price.total - price.deposit, applied,
    cancellation };
}

function baseAppliedRules(data: QuoteData, nights: Night[], price: Price): string[] {
  const result: string[] = [];
  if (nights.some((row) => row.weekend_cents > 0)) result.push("weekend");
  if (price.cleaning) result.push("cleaning");
  if (price.guests) result.push("extra-guests");
  if (price.tax) result.push("tourist-tax");
  if (data.extras.includes("PARKING")) result.push("parking");
  if (data.extras.includes("PET")) result.push("pet");
  return result;
}

function discountAppliedRules(price: Price): string[] {
  const result: string[] = [];
  if (price.long) result.push("long-stay");
  if (price.promo) result.push("promo");
  if (price.total) result.push("deposit");
  return result;
}

function rhu(n: number, d: number): number { return Math.floor((2 * n + d) / (2 * d)); }
