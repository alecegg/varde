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
type PayRow = Record<string, number> & { daily: number; weekly: number };
type Failure = { error: string; index: number | null };
type MinuteInfo = {
  daily: boolean;
  weekly: boolean;
  overtime: boolean;
  night: boolean;
  weekend: boolean;
};
const RATES: Record<string, number> = { helper: 1800, nurse: 2400, lead: 3000 };
const RULES: readonly (readonly [keyof PayRow, string])[] = [
  ["daily", "daily-overtime"], ["weekly", "weekly-overtime"],
  ["night_minutes", "night-premium"], ["weekend_minutes", "weekend-premium"],
  ["holiday_minutes", "holiday-rate"], ["callout_minutes", "callout-minimum"],
  ["bonus_cents", "bonus"],
];

/** Return ordered shift pay rows or the first contract validation error. */
export function solution(request: Request): Record<string, unknown> {
  const role = request.role.trim().toLowerCase();
  const requestFailure = validateRequest(role, request.shifts, request.bonus);
  if (requestFailure) return requestFailure;
  const spans = makeSpans(request.shifts);
  const rowFailure = validateRows(spans);
  if (rowFailure) return rowFailure;
  const overlapFailure = findOverlap(spans);
  if (overlapFailure) return overlapFailure;
  const rows = priceWeek(role, spans, request.bonus);
  return assemble(rows, spans.reduce((sum, span) => sum + span.paid, 0));
}

function makeSpans(shifts: Shift[]): Span[] {
  const spans: Span[] = [];
  for (let index = 0; index < shifts.length; index++) {
    const shift = shifts[index];
    const span: Span = { ...shift, index, duration: 0, paid: 0, timeline: 0 };
    spans.push(span);
  }
  return spans;
}

function validateRequest(role: string, shifts: Shift[], bonus: boolean): Failure | null {
  if (!Object.hasOwn(RATES, role)) return { error: "BAD_ROLE", index: null };
  if (shifts.length === 0) return { error: "EMPTY_WEEK", index: null };
  if (shifts.length > 14) return { error: "TOO_MANY_SHIFTS", index: null };
  if (typeof bonus !== "boolean") return { error: "BAD_BONUS", index: null };
  return null;
}

function validateRows(spans: Span[]): Failure | null {
  for (const span of spans) {
    const fieldFailure = validateClockFields(span);
    if (fieldFailure) return fieldFailure;
    const detailFailure = validateShiftDetail(span);
    if (detailFailure) return detailFailure;
  }
  return null;
}

function validateClockFields(span: Span): Failure | null {
  const fields = [
    [span.day, 0, 6, "BAD_DAY"], [span.start, 0, 1439, "BAD_START"],
    [span.end, 0, 1439, "BAD_END"], [span.break, 0, 240, "BAD_BREAK"],
  ] as const;
  for (const [value, low, high, error] of fields) {
    const failure = clockFieldFailure(value, low, high, error, span.index);
    if (failure) return failure;
  }
  return null;
}

function clockFieldFailure(
  value: number,
  low: number,
  high: number,
  error: string,
  index: number,
): Failure | null {
  if (!Number.isInteger(value) || value < low || value > high) return { error, index };
  return null;
}

function validateShiftDetail(span: Span): Failure | null {
  if (typeof span.holiday !== "boolean") return { error: "BAD_HOLIDAY", index: span.index };
  if (typeof span.callout !== "boolean") return { error: "BAD_CALLOUT", index: span.index };
  const durationFailure = validateDuration(span);
  return durationFailure;
}

function validateDuration(span: Span): Failure | null {
  span.duration = (span.end - span.start + 1440) % 1440 || 1440;
  if (span.duration > 960) return { error: "BAD_LENGTH", index: span.index };
  if (span.break > span.duration) return { error: "BREAK_TOO_LONG", index: span.index };
  span.paid = span.duration - (span.duration > 360 ? span.break : 0);
  span.timeline = span.day * 1440 + span.start;
  return null;
}

function findOverlap(spans: Span[]): Failure | null {
  const earliest = { start: Infinity, index: Infinity };
  for (let leftIndex = 0; leftIndex < spans.length; leftIndex++) {
    for (let rightIndex = leftIndex + 1; rightIndex < spans.length; rightIndex++) {
      for (const weekOffset of [-10080, 0, 10080]) {
        considerOverlap(spans[leftIndex], spans[rightIndex], weekOffset, earliest);
      }
    }
  }
  return earliest.index === Infinity ? null : { error: "OVERLAP", index: earliest.index };
}

function considerOverlap(
  left: Span,
  right: Span,
  offset: number,
  earliest: { start: number; index: number },
): void {
  const start = overlapStart(left, right, offset);
  const candidateIndex = Math.max(left.index, right.index);
  if (start !== null && (start < earliest.start
    || (start === earliest.start && candidateIndex < earliest.index))) {
    earliest.start = Math.min(earliest.start, start);
    earliest.index = Math.max(left.index, right.index);
  }
}

function overlapStart(left: Span, right: Span, offset: number): number | null {
  const start = Math.max(left.timeline, right.timeline + offset);
  const end = Math.min(left.timeline + left.duration, right.timeline + offset + right.duration);
  return start < end ? start : null;
}

function priceWeek(role: string, spans: Span[], bonus: boolean): PayRow[] {
  let weeklyPrior = 0;
  const rows: PayRow[] = [];
  for (const span of spans) {
    const row = priceShift(role, span, weeklyPrior);
    rows.push(row);
    weeklyPrior += span.paid;
  }
  if (bonus && weeklyPrior >= 600) addBonus(rows[rows.length - 1]);
  return rows;
}

function priceShift(role: string, span: Span, weeklyPrior: number): PayRow {
  const row = emptyPayRow(span);
  const worked = addWorkedMinutes(role, span, weeklyPrior, row);
  const topUp = span.callout ? Math.max(0, 180 - span.paid) : 0;
  row.callout_minutes = topUp;
  row.cents = roundAmount(worked + RATES[role] * topUp * 20, 1200);
  return row;
}

function emptyPayRow(span: Span): PayRow {
  return {
    day: span.day, start: span.start, end: span.end, paid_minutes: span.paid,
    regular_minutes: 0, overtime_minutes: 0, night_minutes: 0, weekend_minutes: 0,
    holiday_minutes: 0, callout_minutes: 0, bonus_cents: 0, cents: 0, daily: 0, weekly: 0,
  };
}

function addWorkedMinutes(role: string, span: Span, weeklyPrior: number, row: PayRow): number {
  let amountNumerator = 0;
  for (let offset = 0; offset < span.paid; offset++) {
    const minute = minuteInfo(span, weeklyPrior, offset);
    amountNumerator += priceMinute(RATES[role], minute, row, span.holiday);
  }
  return amountNumerator;
}

function minuteInfo(span: Span, weeklyPrior: number, offset: number): MinuteInfo {
  const minutePosition = span.timeline + span.duration - span.paid + offset;
  const minuteOfDay = minutePosition % 1440;
  const weekday = Math.floor(minutePosition / 1440) % 7;
  const daily = offset >= 480;
  const weekly = weeklyPrior + offset >= 2400;
  const overtime = daily || weekly;
  const night = minuteOfDay >= 1320 || minuteOfDay < 360;
  const weekend = weekday === 5 || weekday === 6;
  return { daily, weekly, overtime, night, weekend };
}

function priceMinute(rate: number, minute: MinuteInfo, row: PayRow, holiday: boolean): number {
  recordMinute(row, minute.daily, minute.weekly, minute.overtime,
    minute.night, minute.weekend, holiday);
  const units = 20 + 10 * Number(minute.overtime) + 4 * Number(minute.night)
    + 5 * Number(minute.weekend) + 20 * Number(holiday);
  return rate * units;
}

function recordMinute(
  row: PayRow,
  daily: boolean,
  weekly: boolean,
  overtime: boolean,
  night: boolean,
  weekend: boolean,
  holiday: boolean,
): void {
  row.daily ||= Number(daily);
  row.weekly ||= Number(weekly);
  row.regular_minutes += Number(!overtime);
  row.overtime_minutes += Number(overtime);
  row.night_minutes += Number(night);
  row.weekend_minutes += Number(weekend);
  row.holiday_minutes += Number(holiday);
}

function addBonus(row: PayRow): void {
  const bonusCents = 500;
  const updatedBonus = row.bonus_cents + bonusCents;
  const updatedPay = row.cents + bonusCents;
  row.bonus_cents = updatedBonus;
  row.cents = updatedPay;
}

function roundAmount(numerator: number, denominator: number): number {
  const doubledAmount = 2 * numerator;
  const roundedNumerator = doubledAmount + denominator;
  const doubledDenominator = 2 * denominator;
  const roundedCents = Math.floor(roundedNumerator / doubledDenominator);
  return roundedCents;
}

function assemble(rows: PayRow[], weeklyPaid: number): Record<string, unknown> {
  const finalized = finalizeRows(rows);
  const shifts = finalized.shifts;
  const weeklyCents = shifts.reduce((sum, row) => sum + row.cents, 0);
  return {
    shifts,
    weekly_paid_minutes: weeklyPaid,
    weekly_cents: weeklyCents,
    applied: finalized.applied,
  };
}

function finalizeRows(rows: PayRow[]): { shifts: Record<string, number>[]; applied: string[] } {
  const applied: string[] = [];
  for (const [field, name] of RULES) {
    const ruleAffectedPay = rows.some((row) => row[field] > 0);
    if (ruleAffectedPay) applied.push(name);
  }
  const shifts = rows.map(({ daily: _daily, weekly: _weekly, ...row }) => row);
  return { shifts, applied };
}
