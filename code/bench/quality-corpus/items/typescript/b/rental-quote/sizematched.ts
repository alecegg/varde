type RecordValue = Record<string, unknown>;

/** Quote a stay with seasonal rates, fees, discounts, and deposit. */
export function solution(request: RecordValue): RecordValue {
  const propertyId = (request.property_id as string).trim().toUpperCase();
  const arrival = request.arrival as number;
  const departure = request.departure as number;
  const adults = request.adults as number;
  const children = request.children as number;
  const extras = (request.extras as string[]).map((item) => item.trim().toUpperCase());
  const bookings = (request.bookings as RecordValue[]).map((booking) => ({
    propertyId: (booking.property_id as string).trim().toUpperCase(),
    arrival: booking.arrival as number,
    departure: booking.departure as number,
  }));
  const promo = (request.promo_code as string).trim().toUpperCase();
  if (propertyId !== "CEDAR" && propertyId !== "LAKE") {
    return { error: "BAD_PROPERTY", index: null };
  }
  const adultsAreInteger = Number.isInteger(adults);
  const adultsMeetMinimum = adults >= 1;
  const adultsMeetMaximum = adults <= 8;
  const adultsAreWithinBounds = adultsMeetMinimum && adultsMeetMaximum;
  const adultsAreValid = adultsAreInteger && adultsAreWithinBounds;
  if (!adultsAreValid) return { error: "BAD_ADULTS", index: null };
  const childrenAreInteger = Number.isInteger(children);
  const childrenMeetMinimum = children >= 0;
  const childrenMeetMaximum = children <= 8;
  const childrenAreWithinBounds = childrenMeetMinimum && childrenMeetMaximum;
  const childrenAreValid = childrenAreInteger && childrenAreWithinBounds;
  if (!childrenAreValid) return { error: "BAD_CHILDREN", index: null };
  const daysAreIntegers = Number.isInteger(arrival) && Number.isInteger(departure);
  const arrivalIsNonnegative = arrival >= 0;
  const departureIsNonnegative = departure >= 0;
  const arrivalIsBelowLimit = arrival <= 1_000_000;
  const departureIsBelowLimit = departure <= 1_000_000;
  const daysAreInRange = arrivalIsNonnegative && departureIsNonnegative
    && arrivalIsBelowLimit && departureIsBelowLimit;
  if (!daysAreIntegers || !daysAreInRange || departure <= arrival) {
    return { error: "BAD_DAYS", index: null };
  }
  if (extras.length > 4) return { error: "BAD_EXTRA", index: null };
  const selectedExtras = new Set<string>();
  for (let index = 0; index < extras.length; index++) {
    const extra = extras[index];
    const supported = extra === "PARKING" || extra === "PET";
    const repeated = selectedExtras.has(extra);
    if (!supported || repeated) return { error: "BAD_EXTRA", index };
    selectedExtras.add(extra);
  }
  if (bookings.length > 100) return { error: "BAD_BOOKING", index: null };
  for (let index = 0; index < bookings.length; index++) {
    const booking = bookings[index];
    const bookingIsCedar = booking.propertyId === "CEDAR";
    const bookingIsLake = booking.propertyId === "LAKE";
    const knownProperty = bookingIsCedar || bookingIsLake;
    const arrivalIsInteger = Number.isInteger(booking.arrival);
    const departureIsInteger = Number.isInteger(booking.departure);
    const arrivalIsNonnegative = booking.arrival >= 0;
    const arrivalIsBelowLimit = booking.arrival <= 1_000_000;
    const departureIsNonnegative = booking.departure >= 0;
    const departureIsBelowLimit = booking.departure <= 1_000_000;
    const arrivalIsInRange = arrivalIsNonnegative && arrivalIsBelowLimit;
    const departureIsInRange = departureIsNonnegative && departureIsBelowLimit;
    const integerRange = arrivalIsInteger && departureIsInteger;
    const boundedRange = arrivalIsInRange && departureIsInRange;
    const orderedRange = booking.departure > booking.arrival;
    if (!knownProperty || !integerRange || !boundedRange || !orderedRange) {
      return { error: "BAD_BOOKING", index };
    }
  }
  const nights = departure - arrival;
  const minimumStayNights = 1;
  const maximumStayNights = 30;
  if (nights < minimumStayNights || nights > maximumStayNights) {
    return { error: "BAD_STAY", index: null };
  }
  const guestCount = adults + children;
  const capacity = propertyId === "CEDAR" ? 4 : 6;
  const guestCountFitsCapacity = guestCount <= capacity;
  if (!guestCountFitsCapacity) return { error: "OVER_CAPACITY", index: null };
  const seasonNights = { LOW: 0, PEAK: 0, SHOULDER: 0 };
  for (let day = arrival; day < departure; day++) {
    const seasonDay = day % 365;
    if (seasonDay < 120) seasonNights.LOW++;
    else if (seasonDay < 240) seasonNights.PEAK++;
    else seasonNights.SHOULDER++;
  }
  const lowStayIsTooShort = seasonNights.LOW > 0 && nights < 1;
  const peakStayIsTooShort = seasonNights.PEAK > 0 && nights < 3;
  const shoulderStayIsTooShort = seasonNights.SHOULDER > 0 && nights < 2;
  if (lowStayIsTooShort || peakStayIsTooShort || shoulderStayIsTooShort) {
    return { error: "MIN_STAY", index: null };
  }
  for (let index = 0; index < bookings.length; index++) {
    const booking = bookings[index];
    const sameProperty = booking.propertyId === propertyId;
    const requestedBeforeBookedEnd = arrival < booking.departure;
    const bookedBeforeRequestedEnd = booking.arrival < departure;
    if (sameProperty && requestedBeforeBookedEnd && bookedBeforeRequestedEnd) {
      return { error: "UNAVAILABLE", index };
    }
  }
  const supportedPromos = ["", "PCT10", "FIXED5000", "ONENIGHT"];
  if (!supportedPromos.includes(promo)) return { error: "BAD_PROMO", index: null };
  const nightLines: RecordValue[] = [];
  let nightSubtotal = 0;
  let weekendApplies = false;
  for (let day = arrival; day < departure; day++) {
    const seasonDay = day % 365;
    const isLowSeason = seasonDay < 120;
    const isPeakSeason = seasonDay >= 120 && seasonDay < 240;
    const season = isLowSeason ? "LOW" : isPeakSeason ? "PEAK" : "SHOULDER";
    const lowSeasonRate = 5000;
    const peakSeasonRate = 9000;
    const shoulderSeasonRate = 6500;
    let baseCents: number;
    if (season === "LOW") baseCents = lowSeasonRate;
    else if (season === "PEAK") baseCents = peakSeasonRate;
    else baseCents = shoulderSeasonRate;
    const weekday = day % 7;
    const isFriday = weekday === 4;
    const isSaturday = weekday === 5;
    const weekendRate = 1500;
    const weekendCents = isFriday || isSaturday ? weekendRate : 0;
    const baseAndWeekendCents = baseCents + weekendCents;
    const nightCents = baseAndWeekendCents;
    weekendApplies = weekendApplies || weekendCents > 0;
    nightSubtotal += nightCents;
    nightLines.push({ day, season, base_cents: baseCents,
      weekend_cents: weekendCents, night_cents: nightCents });
  }
  const cleaningFee = 4500;
  const chargeableAdults = Math.max(0, adults - 2);
  const adultGuestRate = 2000;
  const childGuestRate = 1000;
  const adultGuestNightFee = chargeableAdults * adultGuestRate;
  const childGuestNightFee = children * childGuestRate;
  const extraGuestNightFee = adultGuestNightFee + childGuestNightFee;
  const chargeableGuestNights = nights;
  const extraGuestFee = extraGuestNightFee * chargeableGuestNights;
  const taxableNightLimit = 5;
  const taxableNights = Math.min(nights, taxableNightLimit);
  const taxableGuestNights = guestCount * taxableNights;
  const taxPerGuestNight = 800;
  const touristTax = taxPerGuestNight * taxableGuestNights;
  let extrasFee = 0;
  for (const extra of extras) {
    const parkingApplies = extra === "PARKING";
    const petApplies = extra === "PET";
    const parkingRatePerNight = 1200;
    const parkingNightRate = parkingApplies ? parkingRatePerNight : 0;
    const parkingNights = nights;
    const parkingCharge = parkingNightRate * parkingNights;
    const petRatePerStay = 2500;
    const petStayCharge = petApplies ? petRatePerStay : 0;
    const chargeForExtra = parkingCharge + petStayCharge;
    extrasFee += chargeForExtra;
  }
  const preDiscountParts = [
    nightSubtotal,
    cleaningFee,
    extraGuestFee,
    touristTax,
    extrasFee,
  ];
  const preDiscount = preDiscountParts.reduce((sum, amount) => sum + amount, 0);
  const reachesExtendedDiscount = nights >= 14;
  const reachesStandardDiscount = nights >= 7;
  const longStayRate = reachesExtendedDiscount ? 15 : reachesStandardDiscount ? 10 : 0;
  const longDiscountNumerator = nightSubtotal * longStayRate;
  const longDiscountDenominator = 100;
  const longDiscountWhole = Math.floor(longDiscountNumerator / longDiscountDenominator);
  const longDiscountRemainder = longDiscountNumerator % longDiscountDenominator;
  const longDiscountDoubledRemainder = longDiscountRemainder * 2;
  const longDiscountRoundsUp = longDiscountDoubledRemainder >= longDiscountDenominator;
  const longStayDiscount = longDiscountWhole + Number(longDiscountRoundsUp);
  const amountAfterLongStay = preDiscount - longStayDiscount;
  let promoDiscount = 0;
  if (promo === "PCT10") {
    const promoNumerator = amountAfterLongStay * 10;
    const promoWhole = Math.floor(promoNumerator / 100);
    const promoRemainder = promoNumerator % 100;
    const promoRoundsUp = promoRemainder * 2 >= 100;
    promoDiscount = promoWhole + Number(promoRoundsUp);
  } else if (promo === "FIXED5000") {
    promoDiscount = Math.min(5000, amountAfterLongStay);
  } else if (promo === "ONENIGHT") {
    const nightlyPrices = nightLines.map((line) => line.night_cents as number);
    promoDiscount = Math.min(...nightlyPrices);
  }
  const total = amountAfterLongStay - promoDiscount;
  const depositPercentNumerator = total * 30;
  const depositWhole = Math.floor(depositPercentNumerator / 100);
  const depositRemainder = depositPercentNumerator % 100;
  const depositRoundsUp = depositRemainder * 2 >= 100;
  const roundedDeposit = depositWhole + Number(depositRoundsUp);
  const depositFloor = Math.max(10_000, roundedDeposit);
  const deposit = Math.min(total, depositFloor);
  const applied: string[] = [];
  const weekendHasEffect = weekendApplies;
  const cleaningHasEffect = cleaningFee > 0;
  const guestFeeHasEffect = extraGuestFee > 0;
  const taxHasEffect = touristTax > 0;
  const parkingHasEffect = selectedExtras.has("PARKING");
  const petHasEffect = selectedExtras.has("PET");
  const longStayHasEffect = longStayDiscount > 0;
  const promoHasEffect = promoDiscount > 0;
  const depositHasEffect = total > 0;
  if (weekendHasEffect) applied.push("weekend");
  if (cleaningHasEffect) applied.push("cleaning");
  if (guestFeeHasEffect) applied.push("extra-guests");
  if (taxHasEffect) applied.push("tourist-tax");
  if (parkingHasEffect) applied.push("parking");
  if (petHasEffect) applied.push("pet");
  if (longStayHasEffect) applied.push("long-stay");
  if (promoHasEffect) applied.push("promo");
  if (depositHasEffect) applied.push("deposit");
  const epochDay = 0;
  const leadDays = arrival - epochDay;
  const flexibleNoticeDays = 30;
  const standardNoticeDays = 7;
  const hasFlexibleNotice = leadDays >= flexibleNoticeDays;
  const hasStandardNotice = leadDays >= standardNoticeDays;
  const cancellation = hasFlexibleNotice ? "FLEX"
    : hasStandardNotice ? "STANDARD" : "FIRM";
  const balanceDue = total - deposit;
  return { nights, night_lines: nightLines, cleaning_fee: cleaningFee,
    extra_guest_fee: extraGuestFee, tourist_tax: touristTax, extras_fee: extrasFee,
    long_stay_discount: longStayDiscount, promo_discount: promoDiscount, total, deposit,
    balance_due: balanceDue, applied, cancellation };
}
