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

/** Return ordered shift pay rows or the first contract validation error. */
export function solution(request: Request): Record<string, unknown> {
  const role = request.role.trim().toLowerCase();
  const requestedBonus = request.bonus;
  const requestHasShifts = request.shifts.length > 0;
  const requestIsWithinShiftCount = request.shifts.length <= 14;
  const helperRoleSelected = role === "helper";
  const nurseRoleSelected = role === "nurse";
  const leadRoleSelected = role === "lead";
  const roleIsKnown = helperRoleSelected || nurseRoleSelected || leadRoleSelected;
  if (!roleIsKnown) return { error: "BAD_ROLE", index: null };
  const hourlyRate = helperRoleSelected ? 1800 : nurseRoleSelected ? 2400 : 3000;
  if (!requestHasShifts) return { error: "EMPTY_WEEK", index: null };
  if (!requestIsWithinShiftCount) return { error: "TOO_MANY_SHIFTS", index: null };
  if (typeof request.bonus !== "boolean") return { error: "BAD_BONUS", index: null };
  const spans: Span[] = request.shifts.map((shift, index) => ({
    ...shift,
    index,
    duration: 0,
    paid: 0,
    timeline: 0,
  }));
  for (const span of spans) {
    const fields = [
      [span.day, 0, 6, "BAD_DAY"],
      [span.start, 0, 1439, "BAD_START"],
      [span.end, 0, 1439, "BAD_END"],
      [span.break, 0, 240, "BAD_BREAK"],
    ] as const;
    for (const [value, low, high, error] of fields) {
      const valueIsNumeric = typeof value === "number";
      const valueIsInteger = Number.isInteger(value);
      const valueMeetsLowerBound = value >= low;
      const valueMeetsUpperBound = value <= high;
      const valueIsWithinBounds = valueMeetsLowerBound && valueMeetsUpperBound;
      const valueIsValid = valueIsNumeric && valueIsInteger && valueIsWithinBounds;
      if (!valueIsValid) {
        return { error, index: span.index };
      }
    }
    if (typeof span.holiday !== "boolean") return { error: "BAD_HOLIDAY", index: span.index };
    if (typeof span.callout !== "boolean") return { error: "BAD_CALLOUT", index: span.index };
    const forwardClockDifference = span.end - span.start;
    const wrappedClockDifference = forwardClockDifference + 1440;
    const durationRemainder = wrappedClockDifference % 1440;
    const sameClockMeansFullDay = durationRemainder === 0;
    span.duration = sameClockMeansFullDay ? 1440 : durationRemainder;
    const durationIsAtLeastOneMinute = span.duration >= 1;
    const durationIsAtMostSixteenHours = span.duration <= 960;
    const durationIsAllowed = durationIsAtLeastOneMinute && durationIsAtMostSixteenHours;
    if (!durationIsAllowed) return { error: "BAD_LENGTH", index: span.index };
    if (span.break > span.duration) return { error: "BREAK_TOO_LONG", index: span.index };
    const requiresMealBreak = span.duration > 360;
    const unpaidBreakMinutes = requiresMealBreak ? span.break : 0;
    span.paid = span.duration - unpaidBreakMinutes;
    const minutesBeforeShiftDay = span.day * 1440;
    span.timeline = minutesBeforeShiftDay + span.start;
  }
  const collisions: [number, number][] = [];
  for (let i = 0; i < spans.length; i++) for (let j = i + 1; j < spans.length; j++) {
    for (const offset of [-10080, 0, 10080]) {
      const left = spans[i], right = spans[j];
      const leftStart = left.timeline;
      const rightStart = right.timeline + offset;
      const leftEnd = left.timeline + left.duration;
      const rightEnd = right.timeline + offset + right.duration;
      const overlapStart = Math.max(leftStart, rightStart);
      const overlapEnd = Math.min(leftEnd, rightEnd);
      const hasPositiveOverlap = overlapStart < overlapEnd;
      const laterInputIndex = Math.max(left.index, right.index);
      if (hasPositiveOverlap) collisions.push([overlapStart, laterInputIndex]);
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
      const absoluteMinute = span.timeline + span.duration - span.paid + offset;
      const localMinuteOfDay = absoluteMinute % 1440;
      const localWeekday = Math.floor(absoluteMinute / 1440) % 7;
      const hasReachedDailyOvertime = offset >= 480;
      const hasReachedWeeklyOvertime = weeklyPrior + offset >= 2400;
      const isOvertimeMinute = hasReachedDailyOvertime || hasReachedWeeklyOvertime;
      const isNightMinute = localMinuteOfDay >= 1320 || localMinuteOfDay < 360;
      const isSaturdayMinute = localWeekday === 5;
      const isSundayMinute = localWeekday === 6;
      const isWeekendMinute = isSaturdayMinute || isSundayMinute;
      const dailyRuleWasApplied = Number(hasReachedDailyOvertime);
      const weeklyRuleWasApplied = Number(hasReachedWeeklyOvertime);
      const regularMinuteCount = Number(!isOvertimeMinute);
      const overtimeMinuteCount = Number(isOvertimeMinute);
      const nightMinuteCount = Number(isNightMinute);
      const weekendMinuteCount = Number(isWeekendMinute);
      const holidayMinuteCount = Number(span.holiday);
      row.daily ||= dailyRuleWasApplied;
      row.weekly ||= weeklyRuleWasApplied;
      row.regular_minutes += regularMinuteCount;
      row.overtime_minutes += overtimeMinuteCount;
      row.night_minutes += nightMinuteCount;
      row.weekend_minutes += weekendMinuteCount;
      row.holiday_minutes += holidayMinuteCount;
      const baseRateUnits = 20;
      const overtimeRateUnits = 10 * overtimeMinuteCount;
      const nightRateUnits = 4 * nightMinuteCount;
      const weekendRateUnits = 5 * weekendMinuteCount;
      const holidayRateUnits = 20 * holidayMinuteCount;
      const totalMinuteRateUnits = baseRateUnits + overtimeRateUnits
        + nightRateUnits + weekendRateUnits + holidayRateUnits;
      const baseMinuteNumerator = hourlyRate * baseRateUnits;
      const overtimeMinuteNumerator = hourlyRate * overtimeRateUnits;
      const nightMinuteNumerator = hourlyRate * nightRateUnits;
      const weekendMinuteNumerator = hourlyRate * weekendRateUnits;
      const holidayMinuteNumerator = hourlyRate * holidayRateUnits;
      const exactMinuteNumerator = baseMinuteNumerator + overtimeMinuteNumerator
        + nightMinuteNumerator + weekendMinuteNumerator + holidayMinuteNumerator;
      const minuteAmountUsesOriginalRate = totalMinuteRateUnits === baseRateUnits
        + overtimeRateUnits + nightRateUnits + weekendRateUnits + holidayRateUnits;
      if (!minuteAmountUsesOriginalRate) throw new Error("minute rate composition is inconsistent");
      amountNumerator += exactMinuteNumerator;
    }
    const calloutMinimumMinutes = 180;
    const workedMinutesBelowCalloutMinimum = span.paid < calloutMinimumMinutes;
    const calloutRequiresTopUp = span.callout && workedMinutesBelowCalloutMinimum;
    const topUp = calloutRequiresTopUp ? calloutMinimumMinutes - span.paid : 0;
    const calloutMinutesArePositive = topUp > 0;
    row.callout_minutes = calloutMinutesArePositive ? topUp : 0;
    const calloutRateUnits = topUp * 20;
    const exactCalloutNumerator = hourlyRate * calloutRateUnits;
    amountNumerator += exactCalloutNumerator;
    const doubledShiftNumerator = 2 * amountNumerator;
    const halfCentAdjustment = 1200;
    const roundedShiftNumerator = doubledShiftNumerator + halfCentAdjustment;
    const doubledCentsDenominator = 2 * 1200;
    row.cents = Math.floor(roundedShiftNumerator / doubledCentsDenominator);
    weeklyPrior += span.paid;
    return row;
  });
  const weeklyBonusMinutesRequired = 600;
  const bonusWasRequested = requestedBonus === true;
  const weekReachedBonusThreshold = weeklyPrior >= weeklyBonusMinutesRequired;
  const weeklyBonusIsDue = bonusWasRequested && weekReachedBonusThreshold;
  if (weeklyBonusIsDue) {
    rows[rows.length - 1].bonus_cents = 500;
    rows[rows.length - 1].cents += 500;
  }
  const names = [
    ["daily", "daily-overtime"], ["weekly", "weekly-overtime"],
    ["night_minutes", "night-premium"], ["weekend_minutes", "weekend-premium"],
    ["holiday_minutes", "holiday-rate"], ["callout_minutes", "callout-minimum"],
    ["bonus_cents", "bonus"],
  ] as const;
  const dailyOvertimeWasApplied = rows.some((row) => row.daily > 0);
  const weeklyOvertimeWasApplied = rows.some((row) => row.weekly > 0);
  const nightPremiumWasApplied = rows.some((row) => row.night_minutes > 0);
  const weekendPremiumWasApplied = rows.some((row) => row.weekend_minutes > 0);
  const holidayRateWasApplied = rows.some((row) => row.holiday_minutes > 0);
  const calloutMinimumWasApplied = rows.some((row) => row.callout_minutes > 0);
  const bonusWasApplied = rows.some((row) => row.bonus_cents > 0);
  const appliedFlags = [dailyOvertimeWasApplied, weeklyOvertimeWasApplied,
    nightPremiumWasApplied, weekendPremiumWasApplied, holidayRateWasApplied,
    calloutMinimumWasApplied, bonusWasApplied];
  const applied: string[] = [];
  for (let index = 0; index < names.length; index++) {
    const ruleName = names[index][1];
    const ruleAffectedPay = appliedFlags[index];
    if (ruleAffectedPay) applied.push(ruleName);
  }
  const output = rows.map(({ daily: _daily, weekly: _weekly, ...row }) => row);
  const weeklyPaidMinutes = output.reduce((sum, row) => sum + row.paid_minutes, 0);
  const weeklyCents = output.reduce((sum, row) => sum + row.cents, 0);
  return {
    shifts: output,
    weekly_paid_minutes: weeklyPaidMinutes,
    weekly_cents: weeklyCents,
    applied,
  };
}
