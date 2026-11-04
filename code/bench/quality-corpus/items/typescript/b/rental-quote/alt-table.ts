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
  for (const row of VALIDATION_ROWS) {
    const issue = ruleIssue(data, row);
    if (issue) return { error: issue.error || row.code, index: issue.index };
  }
  const stay = checkStay(data);
  if ("error" in stay) return stay;
  return assemble(priceFees({ data: stay, nights: createNights(stay) }));
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
    promo_code: stringField(request, "promo_code"),
    extras, bookings: normaliseBookings(request),
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

function ruleIssue(data: Input, row: Rule): ErrorValue | null {
  if (row.test === "identity") return checkIdentity(data);
  if (row.test === "extras") return checkExtras(data.extras);
  if (row.test === "bookings") return checkBookings(data.bookings);
  const valid = Number.isInteger(data.arrival) && Number.isInteger(data.departure)
    && data.arrival >= 0 && data.departure >= 0 && data.arrival <= 1_000_000
    && data.departure <= 1_000_000 && data.departure > data.arrival;
  return valid ? null : { error: row.code, index: null };
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
    if (!["CEDAR", "LAKE"].includes(row.property_id)
      || !Number.isInteger(row.arrival) || !Number.isInteger(row.departure)
      || row.arrival < 0 || row.arrival > 1_000_000
      || row.departure > 1_000_000 || row.departure <= row.arrival) {
      return { error: "BAD_BOOKING", index };
    }
  }
  return null;
}

function checkStay(data: Input): Input | ErrorValue {
  const count = data.departure - data.arrival;
  if (count < 1 || count > 30) return { error: "BAD_STAY", index: null };
  if (data.adults + data.children > (data.property_id === "CEDAR" ? 4 : 6)) {
    return { error: "OVER_CAPACITY", index: null };
  }
  const minimumIssue = checkMinimums(data, count);
  if (minimumIssue) return minimumIssue;
  if (!["", "PCT10", "FIXED5000", "ONENIGHT"].includes(data.promo_code)) {
    return { error: "BAD_PROMO", index: null };
  }
  return data;
}

function checkMinimums(data: Input, count: number): ErrorValue | null {
  for (let day = data.arrival; day < data.departure; day++) {
    const phase = day % 365;
    const season = SEASONS.find((row) => phase >= row.from && phase < row.to);
    if (season && count < season.minStay) return { error: "MIN_STAY", index: null };
  }
  const overlap = data.bookings.findIndex((row) =>
    row.property_id === data.property_id
      && data.arrival < row.departure && row.arrival < data.departure);
  return overlap < 0 ? null : { error: "UNAVAILABLE", index: overlap };
}

function createNights(data: Input): Night[] {
  const nights: Night[] = [];
  for (let day = data.arrival; day < data.departure; day++) {
    const phase = day % 365;
    const season = SEASONS.find((row) => phase >= row.from && phase < row.to);
    if (!season) continue;
    const weekend = WEEKEND.days.includes(day % 7) ? WEEKEND.surcharge : 0;
    nights.push({ day, season: season.label, base_cents: season.rate,
      weekend_cents: weekend, night_cents: season.rate + weekend });
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
type Rule = { code: string; test: string };
type Season = { from: number; to: number; label: string; rate: number; minStay: number };

const SEASONS: Season[] = [
  { from: 0, to: 120, label: "LOW", rate: 5000, minStay: 1 },
  { from: 120, to: 240, label: "PEAK", rate: 9000, minStay: 3 },
  { from: 240, to: 365, label: "SHOULDER", rate: 6500, minStay: 2 },
];
const WEEKEND = { days: [4, 5], surcharge: 1500 };
const FEE_ROWS = [
  { kind: "cleaning", amount: 4500 }, { kind: "adult", amount: 2000 },
  { kind: "child", amount: 1000 }, { kind: "tax", amount: 800 },
  { kind: "parking", amount: 1200 }, { kind: "pet", amount: 2500 },
];
const PROMOS = [
  { code: "PCT10", kind: "percent", value: 10 },
  { code: "FIXED5000", kind: "fixed", value: 5000 },
  { code: "ONENIGHT", kind: "night", value: 0 },
];
const VALIDATION_ROWS: Rule[] = [
  { code: "identity", test: "identity" }, { code: "BAD_DAYS", test: "dates" },
  { code: "BAD_EXTRA", test: "extras" }, { code: "BAD_BOOKING", test: "bookings" },
];

function calculateFees(data: Input, count: number, subtotal: number): FeeSet {
  const cleaning = FEE_ROWS[0].amount;
  const guests = (Math.max(0, data.adults - 2) * FEE_ROWS[1].amount
    + data.children * FEE_ROWS[2].amount) * count;
  const tax = FEE_ROWS[3].amount * (data.adults + data.children)
    * Math.min(count, 5);
  const extras = data.extras.reduce(
    (sum, item) => sum + (item === "PARKING"
      ? FEE_ROWS[4].amount * count : FEE_ROWS[5].amount), 0);
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
  const promo = PROMOS.find((row) => row.code === code);
  if (!promo) return 0;
  if (promo.kind === "percent") {
    return Math.floor((2 * amount * promo.value + 100) / 200);
  }
  if (promo.kind === "fixed") return Math.min(promo.value, amount);
  return Math.min(...nights.map((night) => night.night_cents));
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
  return [...baseApplied(price), ...(price.long ? ["long-stay"] : []),
    ...(price.promo ? ["promo"] : []), ...(price.total ? ["deposit"] : [])];
}

function baseApplied(price: Priced): string[] {
  const rows: [boolean, string][] = [
    [price.nights.some((night) => night.weekend_cents > 0), "weekend"],
    [Boolean(price.cleaning), "cleaning"], [Boolean(price.guests), "extra-guests"],
    [Boolean(price.tax), "tourist-tax"],
    [price.data.extras.includes("PARKING"), "parking"],
    [price.data.extras.includes("PET"), "pet"],
  ];
  return rows.filter(([active]) => active).map(([, name]) => name);
}
