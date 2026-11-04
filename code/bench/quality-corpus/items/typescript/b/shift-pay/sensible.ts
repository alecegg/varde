type Shift = {
  day: number;
  start: number;
  end: number;
  break: number;
  holiday: boolean;
  callout: boolean;
};
type Request = { role: string; shifts: Shift[]; bonus: boolean };
type Span = Shift & { index: number; duration: number; paid: number; timeline: number };
type Row = Record<string, number>;
type Failure = { error: string; index: number | null };
type Prepared = { role: string; spans: Span[] } | Failure;
type MinuteFlags = {
  daily: boolean;
  weekly: boolean;
  overtime: boolean;
  night: boolean;
  weekend: boolean;
};
const RATES: Record<string, number> = { helper: 1800, nurse: 2400, lead: 3000 };
const APPLIED = [
  ["daily", "daily-overtime"], ["weekly", "weekly-overtime"],
  ["night_minutes", "night-premium"], ["weekend_minutes", "weekend-premium"],
  ["holiday_minutes", "holiday-rate"], ["callout_minutes", "callout-minimum"],
  ["bonus_cents", "bonus"],
] as const;

/** Return ordered shift pay rows or the first contract validation error. */
export function solution(request: Request): Record<string, unknown> {
  const prepared = normalizeRequest(request);
  if ("error" in prepared) return prepared;
  const { role, spans } = prepared;
  const rowFailure = validateRows(spans);
  if (rowFailure) return rowFailure;
  const collision = findOverlap(spans);
  if (collision) return collision;
  let weeklyPrior = 0;
  const rows = spans.map((span) => {
    const row = priceShift(role, span, weeklyPrior);
    weeklyPrior += span.paid;
    return row;
  });
  if (request.bonus && weeklyPrior >= 600) {
    const finalRow = rows[rows.length - 1];
    addBonus(finalRow);
  }
  return assemble(rows, weeklyPrior);
}

function validateRequest(role: string, shifts: Shift[], bonus: boolean): Failure | null {
  if (!Object.hasOwn(RATES, role)) return { error: "BAD_ROLE", index: null };
  if (shifts.length === 0) return { error: "EMPTY_WEEK", index: null };
  if (shifts.length > 14) return { error: "TOO_MANY_SHIFTS", index: null };
  return typeof bonus === "boolean" ? null : { error: "BAD_BONUS", index: null };
}

function normalize(shifts: Shift[]): Span[] {
  return shifts.map((shift, index) => ({ ...shift, index, duration: 0, paid: 0, timeline: 0 }));
}

function normalizeRequest(request: Request): Prepared {
  const role = request.role.trim().toLowerCase();
  const failure = validateRequest(role, request.shifts, request.bonus);
  if (failure) return failure;
  return { role, spans: normalize(request.shifts) };
}

function validateRows(spans: Span[]): Failure | null {
  for (const span of spans) {
    const fieldFailure = validateIntegerFields(span) ?? validateFlags(span);
    if (fieldFailure) return fieldFailure;
    const detailFailure = validateShiftDetail(span);
    if (detailFailure) return detailFailure;
  }
  return null;
}

function validateIntegerFields(span: Span): Failure | null {
  const integerFields = [
    [span.day, 0, 6, "BAD_DAY"],
    [span.start, 0, 1439, "BAD_START"],
    [span.end, 0, 1439, "BAD_END"],
    [span.break, 0, 240, "BAD_BREAK"],
  ] as const;
  for (const [value, low, high, error] of integerFields) {
    if (!Number.isInteger(value) || value < low || value > high) {
      return { error, index: span.index };
    }
  }
  return null;
}

function validateFlags(span: Span): Failure | null {
  if (typeof span.holiday !== "boolean") return { error: "BAD_HOLIDAY", index: span.index };
  if (typeof span.callout !== "boolean") return { error: "BAD_CALLOUT", index: span.index };
  return null;
}

function validateShiftDetail(span: Span): Failure | null {
  span.duration = (span.end - span.start + 1440) % 1440 || 1440;
  if (span.duration > 960) return { error: "BAD_LENGTH", index: span.index };
  if (span.break > span.duration) return { error: "BREAK_TOO_LONG", index: span.index };
  const unpaid = span.duration > 360 ? span.break : 0;
  span.paid = span.duration - unpaid;
  span.timeline = span.day * 1440 + span.start;
  return null;
}

function findOverlap(spans: Span[]): Failure | null {
  const collisions = collectOverlaps(spans);
  if (collisions.length === 0) return null;
  collisions.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  return { error: "OVERLAP", index: collisions[0][1] };
}

function collectOverlaps(spans: Span[]): [number, number][] {
  const collisions: [number, number][] = [];
  for (let i = 0; i < spans.length; i++) {
    for (let j = i + 1; j < spans.length; j++) {
      for (const offset of [-10080, 0, 10080]) {
        const overlap = overlapStart(spans[i], spans[j], offset);
        if (overlap !== null) collisions.push([overlap, Math.max(spans[i].index, spans[j].index)]);
      }
    }
  }
  return collisions;
}

function overlapStart(left: Span, right: Span, offset: number): number | null {
  const start = Math.max(left.timeline, right.timeline + offset);
  const end = Math.min(left.timeline + left.duration, right.timeline + offset + right.duration);
  return start < end ? start : null;
}

function priceShift(
  role: string,
  span: Span,
  weeklyPrior: number,
): Row & { daily: number; weekly: number } {
  const row = emptyPayRow(span);
  const amountNumerator = addWorkedMinutes(role, span, weeklyPrior, row);
  const topUp = span.callout ? Math.max(0, 180 - span.paid) : 0;
  row.callout_minutes = topUp;
  row.cents = roundHalfUp(amountNumerator + RATES[role] * topUp * 20, 1200);
  return row;
}

function emptyPayRow(span: Span): Row & { daily: number; weekly: number } {
  return {
    day: span.day, start: span.start, end: span.end, paid_minutes: span.paid,
    regular_minutes: 0, overtime_minutes: 0, night_minutes: 0, weekend_minutes: 0,
    holiday_minutes: 0, callout_minutes: 0, bonus_cents: 0, cents: 0, daily: 0, weekly: 0,
  };
}

function addWorkedMinutes(
  role: string,
  span: Span,
  weeklyPrior: number,
  row: Row & { daily: number; weekly: number },
): number {
  let amountNumerator = 0;
  for (let offset = 0; offset < span.paid; offset++) {
    const flags = minuteFlags(span, weeklyPrior, offset);
    recordMinute(row, flags, span.holiday);
    amountNumerator += minuteAmount(role, flags, span.holiday);
  }
  return amountNumerator;
}

function minuteFlags(span: Span, weeklyPrior: number, offset: number): MinuteFlags {
  const absolute = span.timeline + span.duration - span.paid + offset;
  const minute = absolute % 1440;
  const day = Math.floor(absolute / 1440) % 7;
  const daily = offset >= 480;
  const weekly = weeklyPrior + offset >= 2400;
  return { daily, weekly, overtime: daily || weekly, night: minute >= 1320 || minute < 360,
    weekend: day === 5 || day === 6 };
}

function recordMinute(
  row: Row & { daily: number; weekly: number },
  flags: MinuteFlags,
  holiday: boolean,
): void {
  row.daily ||= Number(flags.daily);
  row.weekly ||= Number(flags.weekly);
  row.regular_minutes += Number(!flags.overtime);
  row.overtime_minutes += Number(flags.overtime);
  row.night_minutes += Number(flags.night);
  row.weekend_minutes += Number(flags.weekend);
  row.holiday_minutes += Number(holiday);
}

function minuteAmount(
  role: string,
  flags: MinuteFlags,
  holiday: boolean,
): number {
  const premiumUnits = 10 * Number(flags.overtime) + 4 * Number(flags.night)
    + 5 * Number(flags.weekend) + 20 * Number(holiday);
  return RATES[role] * (20 + premiumUnits);
}

function roundHalfUp(numerator: number, denominator: number): number {
  return Math.floor((2 * numerator + denominator) / (2 * denominator));
}

function addBonus(row: Row & { daily: number; weekly: number }): void {
  row.bonus_cents = 500;
  row.cents += 500;
}

function assemble(
  rows: (Row & { daily: number; weekly: number })[],
  weeklyPaid: number,
): Record<string, unknown> {
  const applied = APPLIED.filter(([field]) => rows.some((row) => row[field] > 0))
    .map(([, name]) => name);
  const output = rows.map(({ daily: _daily, weekly: _weekly, ...row }) => row);
  return { shifts: output, weekly_paid_minutes: weeklyPaid,
    weekly_cents: output.reduce((sum, row) => sum + row.cents, 0), applied };
}
