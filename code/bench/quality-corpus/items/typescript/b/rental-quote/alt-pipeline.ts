type RecordValue = Record<string, unknown>;
type ErrorValue = { error: string; index: number | null };
type Booking = { property_id: string; arrival: number; departure: number };
type Input = {
  property_id: string; arrival: number; departure: number; adults: number;
  children: number; extras: string[]; bookings: Booking[]; promo_code: string;
};
type Night = {
  day: number; season: string; base_cents: number; weekend_cents: number;
  night_cents: number;
};
type Checked = { data: Input; nights: Night[] };
type Priced = {
  data: Input; nights: Night[]; cleaning: number; guests: number; tax: number;
  extras: number; long: number; promo: number; total: number; deposit: number;
};

/** Quote a stay with seasonal rates, fees, discounts, and deposit. */
export function solution(request: RecordValue): RecordValue {
  const data = normalise(request);
  const issue = checkRequest(data);
  if (issue) return issue;
  const count = data.departure - data.arrival;
  if (count < 1 || count > 30) return { error: "BAD_STAY", index: null };
  if (data.adults + data.children > (data.property_id === "CEDAR" ? 4 : 6)) {
    return { error: "OVER_CAPACITY", index: null };
  }
  const stayIssue = checkMinimums(data, count);
  if (stayIssue) return stayIssue;
  return assemble(priceFees({ data, nights: createNights(data) }));
}

function normalise(request: RecordValue): Input {
  const values = request.extras;
  if (!Array.isArray(values)) throw new TypeError();
  const extras = values.map((value: unknown) => {
    if (typeof value !== "string") throw new TypeError();
    return value.trim().toUpperCase();
  });
  return {
    property_id: stringField(request, "property_id"),
    arrival: numberField(request, "arrival"), departure: numberField(request, "departure"),
    adults: numberField(request, "adults"), children: numberField(request, "children"),
    promo_code: stringField(request, "promo_code"), extras,
    bookings: normaliseBookings(request),
  };
}

function normaliseBookings(request: RecordValue): Booking[] {
  const values = request.bookings;
  if (!Array.isArray(values)) throw new TypeError();
  return values.map((row: unknown) => ({
    property_id: stringField(row, "property_id"),
    arrival: numberField(row, "arrival"), departure: numberField(row, "departure"),
  }));
}

function stringField(record: unknown, key: string): string {
  if (record === null || (typeof record !== "object" && typeof record !== "function")) {
    throw new TypeError();
  }
  const value = Reflect.get(record, key);
  if (typeof value !== "string") throw new TypeError();
  return value.trim().toUpperCase();
}

function numberField(record: unknown, key: string): number {
  if (record === null || (typeof record !== "object" && typeof record !== "function")) {
    throw new TypeError();
  }
  const value = Reflect.get(record, key);
  return typeof value === "number" ? value : Number.NaN;
}

function checkRequest(data: Input): ErrorValue | null {
  const identityIssue = checkIdentity(data);
  if (identityIssue) return identityIssue;
  if (!Number.isInteger(data.arrival) || !Number.isInteger(data.departure)
    || data.arrival < 0 || data.departure < 0 || data.arrival > 1_000_000
    || data.departure > 1_000_000 || data.departure <= data.arrival) {
    return { error: "BAD_DAYS", index: null };
  }
  const extraIssue = checkExtras(data.extras);
  return extraIssue ?? checkBookings(data.bookings);
}

function checkIdentity(data: Input): ErrorValue | null {
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

function checkExtras(extras: string[]): ErrorValue | null {
  if (extras.length > 4) return { error: "BAD_EXTRA", index: null };
  const seen = new Set<string>();
  for (let index = 0; index < extras.length; index++) {
    const extra = extras[index];
    if ((extra !== "PARKING" && extra !== "PET") || seen.has(extra)) {
      return { error: "BAD_EXTRA", index };
    }
    seen.add(extra);
  }
  return null;
}

function checkBookings(bookings: Booking[]): ErrorValue | null {
  if (bookings.length > 100) return { error: "BAD_BOOKING", index: null };
  for (let index = 0; index < bookings.length; index++) {
    const row = bookings[index];
    const known = ["CEDAR", "LAKE"].includes(row.property_id);
    if (!known || !Number.isInteger(row.arrival) || !Number.isInteger(row.departure)
      || row.arrival < 0 || row.arrival > 1_000_000 || row.departure > 1_000_000
      || row.departure <= row.arrival) return { error: "BAD_BOOKING", index };
  }
  return null;
}

function checkMinimums(data: Input, count: number): ErrorValue | null {
  for (let day = data.arrival; day < data.departure; day++) {
    const phase = day % 365;
    if ((phase >= 120 && phase < 240 && count < 3)
      || (phase >= 240 && count < 2)) return { error: "MIN_STAY", index: null };
  }
  return checkAvailability(data);
}

function checkAvailability(data: Input): ErrorValue | null {
  const overlap = data.bookings.findIndex((row) =>
    row.property_id === data.property_id
      && data.arrival < row.departure && row.arrival < data.departure);
  if (overlap >= 0) return { error: "UNAVAILABLE", index: overlap };
  if (!["", "PCT10", "FIXED5000", "ONENIGHT"].includes(data.promo_code)) {
    return { error: "BAD_PROMO", index: null };
  }
  return null;
}

function createNights(data: Input): Night[] {
  const nights: Night[] = [];
  for (let day = data.arrival; day < data.departure; day++) {
    const phase = day % 365, season = phase < 120 ? "LOW" : phase < 240 ? "PEAK" : "SHOULDER";
    const base = season === "LOW" ? 5000 : season === "PEAK" ? 9000 : 6500;
    const weekend = day % 7 === 4 || day % 7 === 5 ? 1500 : 0;
    nights.push({ day, season, base_cents: base, weekend_cents: weekend,
      night_cents: base + weekend });
  }
  return nights;
}

function priceFees(context: Checked): Priced {
  const { data, nights } = context, count = data.departure - data.arrival;
  const subtotal = nights.reduce((sum, night) => sum + night.night_cents, 0);
  const fees = calculateFees(data, count, subtotal);
  const discounts = discountAmounts(data, nights, fees, count);
  return discountStay(data, nights, fees, discounts);
}

type FeeSet = { cleaning: number; guests: number; tax: number; extras: number; subtotal: number };
type DiscountSet = { long: number; promo: number; total: number };

function calculateFees(data: Input, count: number, subtotal: number): FeeSet {
  const cleaning = 4500;
  const guests = (Math.max(0, data.adults - 2) * 2000 + data.children * 1000) * count;
  const tax = 800 * (data.adults + data.children) * Math.min(count, 5);
  const extras = data.extras.reduce(
    (sum, item) => sum + (item === "PARKING" ? 1200 * count : 2500), 0);
  return { cleaning, guests, tax, extras, subtotal };
}

function discountStay(
  data: Input, nights: Night[], fees: FeeSet, discounts: DiscountSet,
): Priced {
  const deposit = Math.min(discounts.total,
    Math.max(10000, Math.floor((2 * discounts.total * 30 + 100) / 200)));
  return { data, nights, cleaning: fees.cleaning, guests: fees.guests,
    tax: fees.tax, extras: fees.extras, ...discounts, deposit };
}

function discountAmounts(data: Input, nights: Night[], fees: FeeSet, count: number): DiscountSet {
  const long = count >= 14 ? Math.floor((2 * fees.subtotal * 15 + 100) / 200)
    : count >= 7 ? Math.floor((2 * fees.subtotal * 10 + 100) / 200) : 0;
  const afterLong = fees.subtotal + fees.cleaning + fees.guests + fees.tax + fees.extras - long;
  const promo = promoCut(data.promo_code, afterLong, nights), total = afterLong - promo;
  return { long, promo, total };
}

function promoCut(code: string, amount: number, nights: Night[]): number {
  if (code === "PCT10") return Math.floor((2 * amount * 10 + 100) / 200);
  if (code === "FIXED5000") return Math.min(5000, amount);
  return code === "ONENIGHT" ? Math.min(...nights.map((night) => night.night_cents)) : 0;
}

function assemble(price: Priced): RecordValue {
  const { data, nights, total, deposit } = price;
  const applied = appliedNames(price);
  const cancellation = data.arrival >= 30 ? "FLEX" : data.arrival >= 7 ? "STANDARD" : "FIRM";
  return { nights: nights.length, night_lines: nights, cleaning_fee: price.cleaning,
    extra_guest_fee: price.guests, tourist_tax: price.tax, extras_fee: price.extras,
    long_stay_discount: price.long, promo_discount: price.promo, total, deposit,
    balance_due: total - deposit, applied, cancellation };
}

function appliedNames(price: Priced): string[] {
  const names = baseApplied(price);
  if (price.long) names.push("long-stay");
  if (price.promo) names.push("promo");
  if (price.total) names.push("deposit");
  return names;
}

function baseApplied(price: Priced): string[] {
  const names: string[] = [];
  if (price.nights.some((night) => night.weekend_cents > 0)) names.push("weekend");
  if (price.cleaning) names.push("cleaning");
  if (price.guests) names.push("extra-guests");
  if (price.tax) names.push("tourist-tax");
  if (price.data.extras.includes("PARKING")) names.push("parking");
  if (price.data.extras.includes("PET")) names.push("pet");
  return names;
}
