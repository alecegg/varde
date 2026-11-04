type RecordValue = Record<string, unknown>;

/** Quote a stay with seasonal rates, fees, discounts, and deposit. */
export function solution(request: RecordValue): RecordValue {
  const property = (request.property_id as string).trim().toUpperCase();
  const arrival = request.arrival as number;
  const departure = request.departure as number;
  const adults = request.adults as number;
  const children = request.children as number;
  const extras = (request.extras as string[]).map((item) => item.trim().toUpperCase());
  const bookings = (request.bookings as RecordValue[]).map((booking) => ({
    property: (booking.property_id as string).trim().toUpperCase(),
    arrival: booking.arrival as number,
    departure: booking.departure as number,
  }));
  const promo = (request.promo_code as string).trim().toUpperCase();
  const propertyIsCedar = property === "CEDAR";
  const propertyIsLake = property === "LAKE";
  const propertyIsKnown = propertyIsCedar || propertyIsLake;
  if (!propertyIsKnown) return { error: "BAD_PROPERTY", index: null };
  const adultsAreInteger = Number.isInteger(adults);
  const adultsMeetMinimum = adults >= 1;
  const adultsMeetMaximum = adults <= 8;
  if (!adultsAreInteger || !adultsMeetMinimum || !adultsMeetMaximum) {
    return { error: "BAD_ADULTS", index: null };
  }
  const childrenAreInteger = Number.isInteger(children);
  const childrenMeetMinimum = children >= 0;
  const childrenMeetMaximum = children <= 8;
  if (!childrenAreInteger || !childrenMeetMinimum || !childrenMeetMaximum) {
    return { error: "BAD_CHILDREN", index: null };
  }
  const arrivalIsInteger = Number.isInteger(arrival);
  const departureIsInteger = Number.isInteger(departure);
  const arrivalIsNonnegative = arrival >= 0;
  const arrivalIsBelowLimit = arrival <= 1_000_000;
  const departureIsNonnegative = departure >= 0;
  const departureIsBelowLimit = departure <= 1_000_000;
  const arrivalIsInRange = arrivalIsNonnegative && arrivalIsBelowLimit;
  const departureIsInRange = departureIsNonnegative && departureIsBelowLimit;
  const bothDaysAreIntegers = arrivalIsInteger && departureIsInteger;
  const bothDaysAreInRange = arrivalIsInRange && departureIsInRange;
  const validDays = bothDaysAreIntegers && bothDaysAreInRange;
  const departureFollowsArrival = departure > arrival;
  if (!validDays || !departureFollowsArrival) {
    return { error: "BAD_DAYS", index: null };
  }
  if (extras.length > 4) return { error: "BAD_EXTRA", index: null };
  const seenExtras = new Set<string>();
  for (let index = 0; index < extras.length; index++) {
    const extra = extras[index];
    const isParking = extra === "PARKING";
    const isPet = extra === "PET";
    const isSupportedExtra = isParking || isPet;
    const wasAlreadySelected = seenExtras.has(extra);
    if (!isSupportedExtra || wasAlreadySelected) {
      return { error: "BAD_EXTRA", index };
    }
    seenExtras.add(extra);
  }
  if (bookings.length > 100) return { error: "BAD_BOOKING", index: null };
  for (let index = 0; index < bookings.length; index++) {
    const booking = bookings[index];
    const isCedarBooking = booking.property === "CEDAR";
    const isLakeBooking = booking.property === "LAKE";
    const validProperty = isCedarBooking || isLakeBooking;
    const startIsInteger = Number.isInteger(booking.arrival);
    const endIsInteger = Number.isInteger(booking.departure);
    const startIsInRange = booking.arrival >= 0 && booking.arrival <= 1_000_000;
    const endIsInRange = booking.departure >= 0 && booking.departure <= 1_000_000;
    const endFollowsStart = booking.departure > booking.arrival;
    const validBookingDays = startIsInteger && endIsInteger && startIsInRange
      && endIsInRange && endFollowsStart;
    const bookingIsInvalid = !validProperty || !validBookingDays;
    if (bookingIsInvalid) return { error: "BAD_BOOKING", index };
  }
  const nightCount = departure - arrival;
  const stayHasAtLeastOneNight = nightCount >= 1;
  const stayHasAtMostThirtyNights = nightCount <= 30;
  const stayLengthIsAllowed = stayHasAtLeastOneNight && stayHasAtMostThirtyNights;
  if (!stayLengthIsAllowed) return { error: "BAD_STAY", index: null };
  const capacity = propertyIsCedar ? 4 : 6;
  const guestCount = adults + children;
  const exceedsCapacity = guestCount > capacity;
  if (exceedsCapacity) return { error: "OVER_CAPACITY", index: null };
  const occupied = { LOW: false, PEAK: false, SHOULDER: false };
  for (let day = arrival; day < departure; day++) {
    const seasonDay = day % 365;
    if (seasonDay < 120) occupied.LOW = true;
    else if (seasonDay < 240) occupied.PEAK = true;
    else occupied.SHOULDER = true;
  }
  if (occupied.LOW && nightCount < 1) return { error: "MIN_STAY", index: null };
  if (occupied.PEAK && nightCount < 3) return { error: "MIN_STAY", index: null };
  if (occupied.SHOULDER && nightCount < 2) return { error: "MIN_STAY", index: null };
  for (let index = 0; index < bookings.length; index++) {
    const booking = bookings[index];
    const sameProperty = booking.property === property;
    const requestStartsBeforeBookingEnds = arrival < booking.departure;
    const bookingStartsBeforeRequestEnds = booking.arrival < departure;
    const dateRangesOverlap = requestStartsBeforeBookingEnds && bookingStartsBeforeRequestEnds;
    if (sameProperty && dateRangesOverlap) {
      return { error: "UNAVAILABLE", index };
    }
  }
  if (!["", "PCT10", "FIXED5000", "ONENIGHT"].includes(promo)) {
    return { error: "BAD_PROMO", index: null };
  }
  const nightLines: RecordValue[] = [];
  let baseSubtotal = 0;
  let weekendSubtotal = 0;
  let hasWeekend = false;
  for (let day = arrival; day < departure; day++) {
    const seasonDay = day % 365;
    const isLowSeason = seasonDay < 120;
    const isPeakSeason = seasonDay >= 120 && seasonDay < 240;
    let season: string;
    let baseCents: number;
    if (isLowSeason) {
      season = "LOW";
      baseCents = 5000;
    } else if (isPeakSeason) {
      season = "PEAK";
      baseCents = 9000;
    } else {
      season = "SHOULDER";
      baseCents = 6500;
    }
    const weekday = day % 7;
    const isFriday = weekday === 4;
    const isSaturday = weekday === 5;
    const isWeekend = isFriday || isSaturday;
    const weekendSurcharge = 1500;
    const weekendCents = isWeekend ? weekendSurcharge : 0;
    if (weekendCents > 0) hasWeekend = true;
    const nightCents = baseCents + weekendCents;
    const nightLine = {
      day,
      season,
      base_cents: baseCents,
      weekend_cents: weekendCents,
      night_cents: nightCents,
    };
    baseSubtotal += baseCents;
    weekendSubtotal += weekendCents;
    nightLines.push(nightLine);
  }
  const nightSubtotal = baseSubtotal + weekendSubtotal;
  const cleaningFee = 4500;
  const chargeableAdults = Math.max(0, adults - 2);
  const adultNightRate = chargeableAdults * 2000;
  const childNightRate = children * 1000;
  const guestNightRate = adultNightRate + childNightRate;
  const guestChargeableNights = nightCount;
  const extraGuestFee = guestNightRate * guestChargeableNights;
  const taxGuestCount = adults + children;
  const taxGuestLimitPerStay = 5;
  const taxEligibleNights = Math.min(nightCount, taxGuestLimitPerStay);
  const taxPerGuestNight = 800;
  const taxableGuestNights = taxGuestCount * taxEligibleNights;
  const touristTax = taxPerGuestNight * taxableGuestNights;
  let extrasFee = 0;
  for (const extra of extras) {
    const isParkingExtra = extra === "PARKING";
    const isPetExtra = extra === "PET";
    if (isParkingExtra) {
      const parkingFeePerNight = 1200;
      const parkingStayFee = parkingFeePerNight * nightCount;
      extrasFee += parkingStayFee;
    } else if (isPetExtra) {
      const petFeePerStay = 2500;
      extrasFee += petFeePerStay;
    }
  }
  const stayFeeComponents = [cleaningFee, extraGuestFee];
  const taxAndExtraComponents = [touristTax, extrasFee];
  const stayAndGuestFees = stayFeeComponents.reduce((sum, fee) => sum + fee, 0);
  const taxAndExtraFees = taxAndExtraComponents.reduce((sum, fee) => sum + fee, 0);
  const allFeeGroups = [stayAndGuestFees, taxAndExtraFees];
  const allFees = allFeeGroups.reduce((sum, fee) => sum + fee, 0);
  const preDiscount = nightSubtotal + allFees;
  const receivesFifteenPercent = nightCount >= 14;
  const receivesTenPercent = nightCount >= 7 && nightCount < 14;
  const discountRate = receivesFifteenPercent ? 15 : receivesTenPercent ? 10 : 0;
  const longDiscountNumerator = nightSubtotal * discountRate;
  const longDiscountDenominator = 100;
  const longDiscountDoubled = 2 * longDiscountNumerator;
  const longDiscountHalfUnit = longDiscountDenominator;
  const longDiscountAdjusted = longDiscountDoubled + longDiscountHalfUnit;
  const longDiscountDoubledDenominator = 2 * longDiscountDenominator;
  const longStayDiscount = Math.floor(longDiscountAdjusted / longDiscountDoubledDenominator);
  const afterLongStay = preDiscount - longStayDiscount;
  let promoDiscount = 0;
  if (promo === "PCT10") {
    const promoNumerator = afterLongStay * 10;
    const promoAdjusted = 2 * promoNumerator + 100;
    promoDiscount = Math.floor(promoAdjusted / 200);
  }
  else if (promo === "FIXED5000") promoDiscount = Math.min(5000, afterLongStay);
  else if (promo === "ONENIGHT") {
    promoDiscount = Math.min(...nightLines.map((line) => line.night_cents as number));
  }
  const total = afterLongStay - promoDiscount;
  const depositNumerator = total * 30;
  const depositAdjusted = 2 * depositNumerator + 100;
  const percentageDeposit = Math.floor(depositAdjusted / 200);
  const minimumDeposit = 10_000;
  const requestedDeposit = Math.max(minimumDeposit, percentageDeposit);
  const deposit = Math.min(total, requestedDeposit);
  const applied: string[] = [];
  const cleaningApplied = cleaningFee > 0;
  const guestFeesApplied = extraGuestFee > 0;
  const touristTaxApplied = touristTax > 0;
  const parkingApplied = extras.includes("PARKING");
  const petApplied = extras.includes("PET");
  const longStayApplied = longStayDiscount > 0;
  const promoApplied = promoDiscount > 0;
  const depositApplied = total > 0;
  if (hasWeekend) applied.push("weekend");
  if (cleaningApplied) applied.push("cleaning");
  if (guestFeesApplied) applied.push("extra-guests");
  if (touristTaxApplied) applied.push("tourist-tax");
  if (parkingApplied) applied.push("parking");
  if (petApplied) applied.push("pet");
  if (longStayApplied) applied.push("long-stay");
  if (promoApplied) applied.push("promo");
  if (depositApplied) applied.push("deposit");
  const epochDay = 0;
  const leadDays = arrival - epochDay;
  const hasFlexibleLead = leadDays >= 30;
  const hasStandardLead = leadDays >= 7;
  let cancellation: string;
  if (hasFlexibleLead) cancellation = "FLEX";
  else if (hasStandardLead) cancellation = "STANDARD";
  else cancellation = "FIRM";
  const balanceDue = total - deposit;
  const quote: RecordValue = {};
  quote.nights = nightCount;
  quote.night_lines = nightLines;
  quote.cleaning_fee = cleaningFee;
  quote.extra_guest_fee = extraGuestFee;
  quote.tourist_tax = touristTax;
  quote.extras_fee = extrasFee;
  quote.long_stay_discount = longStayDiscount;
  quote.promo_discount = promoDiscount;
  quote.total = total;
  quote.deposit = deposit;
  quote.balance_due = balanceDue;
  quote.applied = applied;
  quote.cancellation = cancellation;
  return quote;
}
