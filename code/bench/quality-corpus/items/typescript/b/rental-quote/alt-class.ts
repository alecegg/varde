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

/** Quote a stay with seasonal rates, fees, discounts, and deposit. */
export function solution(request: RecordValue): RecordValue {
  const quote = new Quote(request);
  const issue = quote.checkRequest();
  if (issue) return issue;
  quote.priceNights();
  quote.priceFees();
  quote.applyPromo();
  return quote.finish();
}

class Quote {
  private data: Input;
  private nights: Night[];
  private cleaning: number;
  private guests: number;
  private tax: number;
  private extras: number;
  private longDiscount: number;
  private promoDiscount: number;
  private total: number;
  private deposit: number;

  constructor(request: RecordValue) {
    if (this.constructor !== Quote) throw new TypeError();
    this.data = normalise(request, normaliseBookings(request));
    this.nights = [];
    this.cleaning = 4500;
    this.guests = 0;
    this.tax = 0;
    this.extras = 0;
    this.longDiscount = 0;
    this.promoDiscount = 0;
    this.total = 0;
    this.deposit = 0;
  }

  checkRequest(): ErrorValue | null {
    const issue = checkIdentity(this.data);
    if (issue) return issue;
    const { arrival, departure } = this.data;
    const validDates = Number.isInteger(arrival) && Number.isInteger(departure)
      && arrival >= 0 && departure >= 0 && arrival <= 1_000_000
      && departure <= 1_000_000 && departure > arrival;
    if (!validDates) return { error: "BAD_DAYS", index: null };
    const listIssue = checkExtras(this.data.extras) ?? checkBookings(this.data.bookings);
    if (listIssue) return listIssue;
    const stayIssue = this.checkStay();
    if (stayIssue) return stayIssue;
    return this.checkPromo();
  }

  checkStay(): ErrorValue | null {
    const count = this.data.departure - this.data.arrival;
    if (count < 1 || count > 30) return { error: "BAD_STAY", index: null };
    const capacity = this.data.property_id === "CEDAR" ? 4 : 6;
    if (this.data.adults + this.data.children > capacity) {
      return { error: "OVER_CAPACITY", index: null };
    }

  }

  private checkPromo(): ErrorValue | null {
    const count = this.data.departure - this.data.arrival;
    const issue = checkMinimums(this.data, count);
    if (issue) return issue;
    return ["", "PCT10", "FIXED5000", "ONENIGHT"].includes(this.data.promo_code)
      ? null : { error: "BAD_PROMO", index: null };
  }

  priceNights(): void {
    const data = this.data;
    for (let day = data.arrival; day < data.departure; day++) {
      const phase = day % 365, season = phase < 120 ? "LOW"
        : phase < 240 ? "PEAK" : "SHOULDER";
      const base = season === "LOW" ? 5000 : season === "PEAK" ? 9000 : 6500;
      const weekend = day % 7 === 4 || day % 7 === 5 ? 1500 : 0;
      this.nights.push({ day, season, base_cents: base, weekend_cents: weekend,
        night_cents: base + weekend });
    }
  }

  priceFees(): void {
    const count = this.data.departure - this.data.arrival;
    const subtotal = this.nights.reduce((sum, night) => sum + night.night_cents, 0);
    const fees = baseFees(this.data, count);
    this.guests = fees.guests;
    this.tax = fees.tax;
    this.extras = fees.extras;
    this.longDiscount = count >= 14 ? Math.floor((2 * subtotal * 15 + 100) / 200)
      : count >= 7 ? Math.floor((2 * subtotal * 10 + 100) / 200) : 0;
    this.total = subtotal + this.cleaning + this.guests + this.tax + this.extras
      - this.longDiscount;
  }

  applyPromo(): void {
    this.promoDiscount = promoAmount(this.data.promo_code, this.total, this.nights);
    this.total -= this.promoDiscount;
    this.deposit = Math.min(this.total,
      Math.max(10000, Math.floor((2 * this.total * 30 + 100) / 200)));
  }

  finish(): RecordValue {
    const applied = this.appliedNames();
    const cancellation = this.data.arrival >= 30 ? "FLEX"
      : this.data.arrival >= 7 ? "STANDARD" : "FIRM";
    return {
      nights: this.nights.length, night_lines: this.nights, cleaning_fee: this.cleaning,
      extra_guest_fee: this.guests, tourist_tax: this.tax, extras_fee: this.extras,
      long_stay_discount: this.longDiscount, promo_discount: this.promoDiscount,
      total: this.total, deposit: this.deposit, balance_due: this.total - this.deposit,
      applied, cancellation,
    };
  }



  private appliedNames(): string[] {
    const active = [this.nights.some((night) => night.weekend_cents > 0),
      this.cleaning > 0, this.guests > 0, this.tax > 0,
      this.data.extras.includes("PARKING"), this.data.extras.includes("PET"),
      this.longDiscount > 0, this.promoDiscount > 0, this.total > 0];
    const labels = ["weekend", "cleaning", "extra-guests", "tourist-tax", "parking",
      "pet", "long-stay", "promo", "deposit"];
    return labels.filter((_, index) => active[index]);
  }

}

function baseFees(data: Input, count: number) {
  return {
    guests: (Math.max(0, data.adults - 2) * 2000 + data.children * 1000) * count,
    tax: 800 * (data.adults + data.children) * Math.min(count, 5),
    extras: data.extras.reduce((sum, item) =>
      sum + (item === "PARKING" ? 1200 * count : 2500), 0),
  };
}

function normalise(request: RecordValue, bookings: Booking[]): Input {
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
    extras, bookings,
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
    if ((row.property_id !== "CEDAR" && row.property_id !== "LAKE")
      || !Number.isInteger(row.arrival) || !Number.isInteger(row.departure)
      || row.arrival < 0 || row.arrival > 1_000_000
      || row.departure > 1_000_000 || row.departure <= row.arrival) {
      return { error: "BAD_BOOKING", index };
    }
  }
  return null;
}

function checkMinimums(data: Input, count: number): ErrorValue | null {
  for (let day = data.arrival; day < data.departure; day++) {
    const phase = day % 365;
    if ((phase >= 120 && phase < 240 && count < 3)
      || (phase >= 240 && count < 2)) return { error: "MIN_STAY", index: null };
  }
  const index = data.bookings.findIndex((row) =>
    row.property_id === data.property_id && data.arrival < row.departure
      && row.arrival < data.departure);
  return index < 0 ? null : { error: "UNAVAILABLE", index };
}

function promoAmount(code: string, amount: number, nights: Night[]): number {
  if (code === "PCT10") return Math.floor((2 * amount * 10 + 100) / 200);
  if (code === "FIXED5000") return Math.min(5000, amount);
  if (code === "ONENIGHT") return Math.min(...nights.map((row) => row.night_cents));
  return 0;
}

