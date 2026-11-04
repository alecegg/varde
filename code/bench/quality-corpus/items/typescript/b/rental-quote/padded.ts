type RecordValue = Record<string, unknown>;
type ErrorValue = { error: string; index: number | null };
type Booking = { property_id: string; arrival: number; departure: number };
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
type Night = {
  day: number;
  season: string;
  base_cents: number;
  weekend_cents: number;
  night_cents: number;
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

/** Quote a stay with seasonal rates, fees, discounts, and deposit. */
export function solution(request: RecordValue): RecordValue {
  const lists = normalizeLists(request);
  const data = {
    property_id: (request.property_id as string).trim().toUpperCase(),
    arrival: request.arrival as number,
    departure: request.departure as number,
    adults: request.adults as number,
    children: request.children as number,
    extras: lists.extras,
    bookings: lists.bookings,
    promo_code: (request.promo_code as string).trim().toUpperCase(),
  };
  const failure = validateRequest(data);
  if (failure) return failure;
  const nights: Night[] = [];
  for (let day = data.arrival; day < data.departure; day++) {
    const seasonDay = day % 365;
    const seasonIndex = seasonDay < 120 ? 0 : seasonDay < 240 ? 1 : 2;
    const season = ["LOW", "PEAK", "SHOULDER"][seasonIndex];
    const baseCents = [5000, 9000, 6500][seasonIndex];
    const weekendCents = [0, 0, 0, 0, 1500, 1500, 0][day % 7];
    nights.push({ day, season, base_cents: baseCents, weekend_cents: weekendCents,
      night_cents: baseCents + weekendCents });
  }
  const price = priceQuote(data, nights);
  return assembleQuote(data, nights, price);
}

function normalizeLists(request: RecordValue): { extras: string[]; bookings: Booking[] } {
  const extras = (request.extras as string[]).map((item) => item.trim().toUpperCase());
  const bookings = (request.bookings as RecordValue[]).map((row) => ({
    property_id: (row.property_id as string).trim().toUpperCase(),
    arrival: row.arrival as number,
    departure: row.departure as number,
  }));
  return { extras, bookings };
}

function validateIdentity(data: QuoteData): ErrorValue | null {
  if (data.property_id !== "CEDAR" && data.property_id !== "LAKE")
    return { error: "BAD_PROPERTY", index: null };
  if (!Number.isInteger(data.adults) || data.adults < 1 || data.adults > 8)
    return { error: "BAD_ADULTS", index: null };
  if (!Number.isInteger(data.children) || data.children < 0 || data.children > 8)
    return { error: "BAD_CHILDREN", index: null };
  return null;
}

function validateDays(data: QuoteData): ErrorValue | null {
  const arrivalIsInteger = Number.isInteger(data.arrival);
  const departureIsInteger = Number.isInteger(data.departure);
  const arrivalIsInRange = data.arrival >= 0 && data.arrival <= 1_000_000;
  const departureIsInRange = data.departure >= 0 && data.departure <= 1_000_000;
  const rangeIsValid = data.departure > data.arrival;
  if (!arrivalIsInteger || !departureIsInteger || !arrivalIsInRange
    || !departureIsInRange || !rangeIsValid) {
    return { error: "BAD_DAYS", index: null };
  }
  return null;
}

function validateExtras(extras: string[]): ErrorValue | null {
  if (extras.length > 4) return { error: "BAD_EXTRA", index: null };
  const acceptedExtras = new Set<string>();
  for (let index = 0; index < extras.length; index++) {
    const extra = extras[index];
    const extraIsSupported = extra === "PARKING" || extra === "PET";
    if (!extraIsSupported || acceptedExtras.has(extra)) return { error: "BAD_EXTRA", index };
    acceptedExtras.add(extra);
  }
  return null;
}

function validateBookings(bookings: Booking[]): ErrorValue | null {
  if (bookings.length > 100) return { error: "BAD_BOOKING", index: null };
  const invalid = bookings.findIndex(({ property_id, arrival, departure }) =>
    !["CEDAR", "LAKE"].includes(property_id)
      || !Number.isInteger(arrival) || !Number.isInteger(departure)
      || arrival < 0 || arrival > 1_000_000
      || departure <= arrival || departure > 1_000_000);
  return invalid < 0 ? null : { error: "BAD_BOOKING", index: invalid };
}

function validateStayAndCapacity(data: QuoteData): ErrorValue | null {
  const nightCount = data.departure - data.arrival;
  const stayIsWithinBounds = nightCount >= 1 && nightCount <= 30;
  if (!stayIsWithinBounds) return { error: "BAD_STAY", index: null };
  const capacity = data.property_id === "CEDAR" ? 4 : 6;
  const guestCount = data.adults + data.children;
  const fitsCapacity = guestCount <= capacity;
  if (!fitsCapacity) return { error: "OVER_CAPACITY", index: null };
  return null;
}

function validateMinimums(data: QuoteData): ErrorValue | null {
  const occupied = new Set<number>();
  for (let day = data.arrival; day < data.departure; day++) {
    const seasonDay = day % 365;
    occupied.add(seasonDay < 120 ? 0 : seasonDay < 240 ? 1 : 2);
  }
  const nightCount = data.departure - data.arrival;
  if (occupied.has(1) && nightCount < 3 || occupied.has(2) && nightCount < 2)
    return { error: "MIN_STAY", index: null };
  return null;
}

function validateAvailability(data: QuoteData): ErrorValue | null {
  for (let index = 0; index < data.bookings.length; index++) {
    const booking = data.bookings[index];
    const sameProperty = booking.property_id === data.property_id;
    const requestedStartsBeforeBookedEnd = data.arrival < booking.departure;
    const bookingStartsBeforeRequestedEnd = booking.arrival < data.departure;
    const rangesOverlap = requestedStartsBeforeBookedEnd && bookingStartsBeforeRequestedEnd;
    if (sameProperty && rangesOverlap) return { error: "UNAVAILABLE", index };
  }
  return null;
}

function validateRequest(data: QuoteData): ErrorValue | null {
  const failure = validateIdentity(data) ?? validateDays(data) ?? validateExtras(data.extras)
    ?? validateBookings(data.bookings) ?? validateStayAndCapacity(data)
    ?? validateMinimums(data) ?? validateAvailability(data);
  if (failure) return failure;
  return ["", "PCT10", "FIXED5000", "ONENIGHT"].includes(data.promo_code)
    ? null : { error: "BAD_PROMO", index: null };
}

function roundPercent(amount: number, rate: number): number {
  return Math.floor((2 * amount * rate + 100) / 200);
}

function guestCharges(data: QuoteData, subtotal: number, cleaning: number) {
  const nights = data.departure - data.arrival;
  const guests = (Math.max(0, data.adults - 2) * 2000 + data.children * 1000) * nights;
  const tax = 800 * (data.adults + data.children) * Math.min(nights, 5);
  const preDiscount = [subtotal, cleaning, guests, tax].reduce((sum, fee) => sum + fee, 0);
  return { guests, tax, preDiscount };
}

function extrasFee(data: QuoteData): number {
  const nightCount = data.departure - data.arrival;
  let amount = 0;
  for (const extra of data.extras) {
    if (extra === "PARKING") {
      amount += 1200 * nightCount;
    } else if (extra === "PET") {
      amount += 2500;
    }
  }
  return amount;
}

function longStayDiscount(nightCount: number, subtotal: number): number {
  let discountRate = 0;
  if (nightCount >= 14) discountRate = 15;
  else if (nightCount >= 7) discountRate = 10;
  const discount = roundPercent(subtotal, discountRate);
  return discount;
}

function promoDiscount(data: QuoteData, amount: number, lines: Night[]): number {
  if (data.promo_code === "PCT10") {
    return roundPercent(amount, 10);
  }
  if (data.promo_code === "FIXED5000") return Math.min(5000, amount);
  if (data.promo_code === "ONENIGHT") {
    let lowestNight = lines[0].night_cents;
    for (const line of lines) {
      if (line.night_cents < lowestNight) lowestNight = line.night_cents;
    }
    return lowestNight;
  }
  return 0;
}

function priceQuote(data: QuoteData, lines: Night[]): Price {
  const base = prePromoPrice(data, lines);
  const promo = promoDiscount(data, base.beforePromo, lines);
  const { total, deposit } = finishPrice(base.beforePromo, promo);
  return { ...base.price, promo, total, deposit };
}

function prePromoPrice(data: QuoteData, lines: Night[]) {
  const subtotal = lines.reduce((sum, line) => sum + line.night_cents, 0);
  const cleaning = 4500;
  const fees = guestCharges(data, subtotal, cleaning);
  const extras = extrasFee(data);
  const long = longStayDiscount(data.departure - data.arrival, subtotal);
  return {
    beforePromo: fees.preDiscount + extras - long,
    price: { cleaning, guests: fees.guests, tax: fees.tax, extras, long },
  };
}

function finishPrice(beforePromo: number, promo: number): { total: number; deposit: number } {
  const total = beforePromo - promo;
  const deposit = Math.min(total, Math.max(10_000, roundPercent(total, 30)));
  return { total, deposit };
}

function baseAppliedRules(lines: Night[], price: Price): string[] {
  const applied: string[] = [];
  if (lines.some((line) => line.weekend_cents > 0)) applied.push("weekend");
  if (price.cleaning > 0) applied.push("cleaning");
  if (price.guests > 0) applied.push("extra-guests");
  if (price.tax > 0) applied.push("tourist-tax");
  return applied;
}

function extraAppliedRules(data: QuoteData, price: Price): string[] {
  const applied: string[] = [];
  if (data.extras.includes("PARKING")) applied.push("parking");
  if (data.extras.includes("PET")) applied.push("pet");
  if (price.long > 0) applied.push("long-stay");
  if (price.promo > 0) applied.push("promo");
  if (price.total > 0) applied.push("deposit");
  return applied;
}

function assembleQuote(data: QuoteData, lines: Night[], price: Price) {
  const stay = stayFields(data, lines);
  return {
    ...stay,
    cleaning_fee: price.cleaning,
    extra_guest_fee: price.guests,
    tourist_tax: price.tax,
    extras_fee: price.extras,
    long_stay_discount: price.long,
    promo_discount: price.promo,
    total: price.total,
    deposit: price.deposit,
    balance_due: price.total - price.deposit,
    applied: [...baseAppliedRules(lines, price), ...extraAppliedRules(data, price)],
  };
}

function stayFields(data: QuoteData, lines: Night[]): RecordValue {
  return {
    nights: data.departure - data.arrival,
    night_lines: lines,
    cancellation: data.arrival >= 30 ? "FLEX" : data.arrival >= 7 ? "STANDARD" : "FIRM",
  };
}
