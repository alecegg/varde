type Shift = {
  day: number;
  start: number;
  end: number;
  break: number;
  holiday: boolean;
  callout: boolean;
};
type Request = { role: string; shifts: Shift[]; bonus: boolean };
type Span = Shift & {
  index: number;
  duration: number;
  paid: number;
  timeline: number;
};
type Row = Record<string, number> & { daily: number; weekly: number };
type Collision = [startMinute: number, laterInputIndex: number];

/** Return ordered shift pay rows or the first contract validation error. */
export function solution(request: Request): Record<string, unknown> {
  const trimmedRole = request.role.trim();
  const role = trimmedRole.toLowerCase();
  const rates: Record<string, number> = { helper: 1800, nurse: 2400, lead: 3000 };
  const isHelperRole = role === "helper";
  const isNurseRole = role === "nurse";
  const isLeadRole = role === "lead";
  const isKnownRole = isHelperRole || isNurseRole || isLeadRole;
  if (!isKnownRole) return { error: "BAD_ROLE", index: null };
  const dailyOvertimeStartsAfterMinutes = 480;
  const weeklyOvertimeStartsAfterMinutes = 2400;
  const nightShiftStartsAtMinute = 1320;
  const nightShiftEndsBeforeMinute = 360;
  const saturdayWeekdayIndex = 5;
  const sundayWeekdayIndex = 6;
  const standardHourlyRateNumeratorUnits = 20;
  const hasNoShifts = request.shifts.length === 0;
  if (hasNoShifts) return { error: "EMPTY_WEEK", index: null };
  const hasTooManyShifts = request.shifts.length > 14;
  if (hasTooManyShifts) return { error: "TOO_MANY_SHIFTS", index: null };
  const bonusIsBoolean = typeof request.bonus === "boolean";
  if (!bonusIsBoolean) return { error: "BAD_BONUS", index: null };
  const spans: Span[] = request.shifts.map((shift, index) => ({
    ...shift,
    index,
    duration: 0,
    paid: 0,
    timeline: 0,
  }));
  for (const span of spans) {
    const dayIsInteger = Number.isInteger(span.day);
    const dayIsAtLeastMonday = span.day >= 0;
    const dayIsAtMostSunday = span.day <= 6;
    const dayWithinWeek = dayIsAtLeastMonday && dayIsAtMostSunday;
    const dayIsValid = dayIsInteger && dayWithinWeek;
    if (!dayIsValid) return { error: "BAD_DAY", index: span.index };
    const startIsInteger = Number.isInteger(span.start);
    const startIsAfterMidnight = span.start >= 0;
    const startIsBeforeNextMidnight = span.start <= 1439;
    const startIsInClockRange = startIsAfterMidnight && startIsBeforeNextMidnight;
    const startIsValid = startIsInteger && startIsInClockRange;
    if (!startIsValid) return { error: "BAD_START", index: span.index };
    const endIsInteger = Number.isInteger(span.end);
    const endIsAfterMidnight = span.end >= 0;
    const endIsBeforeNextMidnight = span.end <= 1439;
    const endIsInClockRange = endIsAfterMidnight && endIsBeforeNextMidnight;
    const endIsValid = endIsInteger && endIsInClockRange;
    if (!endIsValid) return { error: "BAD_END", index: span.index };
    const breakIsInteger = Number.isInteger(span.break);
    const breakIsNonnegative = span.break >= 0;
    const breakIsAtMostFourHours = span.break <= 240;
    const breakIsInRange = breakIsNonnegative && breakIsAtMostFourHours;
    const breakIsValid = breakIsInteger && breakIsInRange;
    if (!breakIsValid) return { error: "BAD_BREAK", index: span.index };
    if (typeof span.holiday !== "boolean") return { error: "BAD_HOLIDAY", index: span.index };
    if (typeof span.callout !== "boolean") return { error: "BAD_CALLOUT", index: span.index };
    const wrappedDuration = (span.end - span.start + 1440) % 1440;
    const zeroDifferenceMeansOneFullDay = wrappedDuration === 0;
    span.duration = zeroDifferenceMeansOneFullDay ? 1440 : wrappedDuration;
    const durationIsAtLeastOneMinute = span.duration >= 1;
    const durationIsAtMostSixteenHours = span.duration <= 960;
    const durationIsAllowed = durationIsAtLeastOneMinute && durationIsAtMostSixteenHours;
    if (!durationIsAllowed) return { error: "BAD_LENGTH", index: span.index };
    if (span.break > span.duration) return { error: "BREAK_TOO_LONG", index: span.index };
    span.paid = span.duration - (span.duration > 360 ? span.break : 0);
    span.timeline = span.day * 1440 + span.start;
  }
  const collisions: Collision[] = [];
  for (let i = 0; i < spans.length; i++) for (let j = i + 1; j < spans.length; j++) {
    for (const offset of [-10080, 0, 10080]) {
      const left = spans[i], right = spans[j];
      const leftStart = left.timeline;
      const shiftedRightStart = right.timeline + offset;
      const start = Math.max(leftStart, shiftedRightStart);
      const leftEnd = left.timeline + left.duration;
      const shiftedRightEnd = right.timeline + offset + right.duration;
      const end = Math.min(leftEnd, shiftedRightEnd);
      const intervalsOverlap = start < end;
      if (intervalsOverlap) collisions.push([start, Math.max(left.index, right.index)]);
    }
  }
  if (collisions.length) {
    collisions.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    return { error: "OVERLAP", index: collisions[0][1] };
  }
  let weeklyPrior = 0;
  const rows = spans.map((span) => {
    const row: Row = { day: span.day, start: span.start, end: span.end, paid_minutes: span.paid,
      regular_minutes: 0, overtime_minutes: 0, night_minutes: 0, weekend_minutes: 0,
      holiday_minutes: 0, callout_minutes: 0, bonus_cents: 0, cents: 0, daily: 0, weekly: 0 };
    let amountNumerator = 0;
    for (let offset = 0; offset < span.paid; offset++) {
      const absolute = span.timeline + span.duration - span.paid + offset;
      const minute = absolute % 1440, day = Math.floor(absolute / 1440) % 7;
      const daily = offset >= dailyOvertimeStartsAfterMinutes;
      const weekly = weeklyPrior + offset >= weeklyOvertimeStartsAfterMinutes;
      const overtime = daily || weekly;
      const regular = !overtime;
      const nightStartsAtTenPm = minute >= nightShiftStartsAtMinute;
      const nightContinuesUntilSixAm = minute < nightShiftEndsBeforeMinute;
      const night = nightStartsAtTenPm || nightContinuesUntilSixAm;
      const isSaturday = day === saturdayWeekdayIndex;
      const isSunday = day === sundayWeekdayIndex;
      const weekend = isSaturday || isSunday;
      const overtimeUnits = Number(overtime);
      const nightUnits = Number(night);
      const weekendUnits = Number(weekend);
      const holidayUnits = Number(span.holiday);
      row.daily ||= Number(daily); row.weekly ||= Number(weekly);
      row.regular_minutes += Number(regular);
      row.overtime_minutes += overtimeUnits;
      row.night_minutes += nightUnits;
      row.weekend_minutes += weekendUnits;
      row.holiday_minutes += holidayUnits;
      const overtimeRate = 10 * overtimeUnits;
      const nightRate = 4 * nightUnits;
      const weekendRate = 5 * weekendUnits;
      const holidayRate = 20 * holidayUnits;
      const baseRateUnits = standardHourlyRateNumeratorUnits;
      const baseMinuteNumerator = rates[role] * baseRateUnits;
      const overtimeMinuteNumerator = rates[role] * overtimeRate;
      const nightMinuteNumerator = rates[role] * nightRate;
      const weekendMinuteNumerator = rates[role] * weekendRate;
      const holidayMinuteNumerator = rates[role] * holidayRate;
      const premiumNumerators = [overtimeMinuteNumerator, nightMinuteNumerator,
        weekendMinuteNumerator, holidayMinuteNumerator];
      const minutePremiumNumerator = premiumNumerators.reduce((sum, value) => sum + value, 0);
      const minuteNumerator = baseMinuteNumerator + minutePremiumNumerator;
      amountNumerator += minuteNumerator;
    }
    const calloutMinimum = 180;
    const workedMinutesAreBelowMinimum = span.paid < calloutMinimum;
    const calloutNeedsTopUp = span.callout && workedMinutesAreBelowMinimum;
    const topUp = calloutNeedsTopUp ? calloutMinimum - span.paid : 0;
    row.callout_minutes = topUp;
    const calloutTopUpRateUnits = topUp * standardHourlyRateNumeratorUnits;
    const calloutTopUpNumerator = rates[role] * calloutTopUpRateUnits;
    amountNumerator += calloutTopUpNumerator;
    const doubledExactAmount = 2 * amountNumerator;
    const halfCentAdjustment = 1200;
    const adjustedAmount = doubledExactAmount + halfCentAdjustment;
    const doubledDenominator = 2 * 1200;
    row.cents = Math.floor(adjustedAmount / doubledDenominator);
    weeklyPrior += span.paid;
    return row;
  });
  const bonusWasRequested = request.bonus === true;
  const weeklyBonusThresholdWasMet = weeklyPrior >= 600;
  const bonusIsDue = bonusWasRequested && weeklyBonusThresholdWasMet;
  if (bonusIsDue) {
    rows[rows.length - 1].bonus_cents = 500;
    rows[rows.length - 1].cents += 500;
  }
  const names: readonly (readonly [keyof Row, string])[] = [
    ["daily", "daily-overtime"], ["weekly", "weekly-overtime"],
    ["night_minutes", "night-premium"], ["weekend_minutes", "weekend-premium"],
    ["holiday_minutes", "holiday-rate"], ["callout_minutes", "callout-minimum"],
    ["bonus_cents", "bonus"],
  ];
  const applied = names.filter(([key]) => rows.some((row) => row[key] > 0)).map(([, name]) => name);
  const output = rows.map(({ daily: _daily, weekly: _weekly, ...row }) => row);
  const weeklyPaidMinutes = output.reduce((sum, row) => sum + row.paid_minutes, 0);
  const weeklyCents = output.reduce((sum, row) => sum + row.cents, 0);
  const weeklyResult = {
    shifts: output,
    weekly_paid_minutes: weeklyPaidMinutes,
    weekly_cents: weeklyCents,
    applied,
  };
  return weeklyResult;
}
