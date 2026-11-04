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
const RATES: Record<string, number> = { helper: 1800, nurse: 2400, lead: 3000 };
const APPLIED = [
  ["daily", "daily-overtime"], ["weekly", "weekly-overtime"],
  ["night_minutes", "night-premium"], ["weekend_minutes", "weekend-premium"],
  ["holiday_minutes", "holiday-rate"], ["callout_minutes", "callout-minimum"],
  ["bonus_cents", "bonus"],
] as const;

/** Return ordered shift pay rows or the first contract validation error. */
export function solution(request: Request): Record<string, unknown> {
  const payroll = new Payroll();
  return payroll.run(request);
}

class Payroll {
  private role = "";
  private spans: Span[] = [];
  run(request: Request): Record<string, unknown> {
    const failure = this.check(request);
    if (failure) return failure;
    const rowFailure = validateRows(this.spans);
    if (rowFailure) return rowFailure;
    const collision = findOverlap(this.spans);
    if (collision) return collision;
    let weeklyPrior = 0;
    const rows: Row[] = [];
    for (const span of this.spans) {
      rows.push(this.priceShift(span, weeklyPrior));
      weeklyPrior += span.paid;
    }
    return this.finish(rows, weeklyPrior, request.bonus);
  }

  private check(request: Request): Failure | null {
    const role = request.role.trim().toLowerCase();
    const failure = requestFailure(request, role);
    if (failure) return failure;
    this.role = role;
    this.spans = request.shifts.map((shift, index) => ({
      ...shift, index, duration: 0, paid: 0, timeline: 0,
    }));
    return null;
  }

  private priceShift(span: Span, weeklyPrior: number): Row {
    const row = emptyPayRow(span);
    let numerator = 0;
    for (let offset = 0; offset < span.paid; offset++) {
      const minute = span.timeline + span.duration - span.paid + offset;
      const clock = minute % 1440;
      const overtime = offset >= 480 || weeklyPrior + offset >= 2400;
      const weekend = Math.floor(minute / 1440) % 7 >= 5;
      markOvertime(row, weeklyPrior, offset);
      numerator += workedMinute(this.role, span, clock, overtime, weekend, row);
    }
    return finishShift(this.role, span, row, numerator);
  }

  private finish(rows: Row[], weeklyPaid: number, bonus: boolean): Record<string, unknown> {
    if (bonus && weeklyPaid >= 600) {
      rows[rows.length - 1].bonus_cents = 500;
      rows[rows.length - 1].cents += 500;
    }
    return assemble(rows, weeklyPaid);
  }
}

function markOvertime(row: Row, weeklyPrior: number, offset: number): void {
  row.daily ||= Number(offset >= 480);
  row.weekly ||= Number(weeklyPrior + offset >= 2400);
}

function requestFailure(request: Request, role: string): Failure | null {
  if (!Object.hasOwn(RATES, role)) return { error: "BAD_ROLE", index: null };
  if (!request.shifts.length) return { error: "EMPTY_WEEK", index: null };
  if (request.shifts.length > 14) return { error: "TOO_MANY_SHIFTS", index: null };
  return typeof request.bonus === "boolean" ? null : { error: "BAD_BONUS", index: null };
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
  const hits: [number, number][] = [];
  spans.forEach((left, index) => spans.slice(index + 1).forEach((right) => {
    for (const offset of [-10080, 0, 10080]) {
      const start = Math.max(left.timeline, right.timeline + offset);
      const end = Math.min(left.timeline + left.duration, right.timeline + offset + right.duration);
      if (start < end) hits.push([start, Math.max(left.index, right.index)]);
    }
  }));
  return hits;
}

function finishShift(role: string, span: Span, row: Row, numerator: number): Row {
  const topUp = span.callout ? Math.max(0, 180 - span.paid) : 0;
  row.callout_minutes = topUp;
  row.cents = Math.floor((2 * (numerator + RATES[role] * topUp * 20) + 1200) / 2400);
  return row;
}

function emptyPayRow(span: Span): Row {
  return {
    day: span.day, start: span.start, end: span.end, paid_minutes: span.paid,
    regular_minutes: 0, overtime_minutes: 0, night_minutes: 0, weekend_minutes: 0,
    holiday_minutes: 0, callout_minutes: 0, bonus_cents: 0, cents: 0, daily: 0, weekly: 0,
  };
}


function workedMinute(
  role: string,
  span: Span,
  minute: number,
  overtime: boolean,
  weekend: boolean,
  row: Row,
): number {
  const night = minute >= 1320 || minute < 360;
  row.regular_minutes += Number(!overtime);
  row.overtime_minutes += Number(overtime);
  row.night_minutes += Number(night);
  row.weekend_minutes += Number(weekend);
  row.holiday_minutes += Number(span.holiday);
  const premium = 10 * Number(overtime) + 4 * Number(night)
    + 5 * Number(weekend) + 20 * Number(span.holiday);
  return RATES[role] * (20 + premium);
}

function assemble(
  rows: (Row)[],
  weeklyPaid: number,
): Record<string, unknown> {
  const applied = APPLIED.filter(([field]) => rows.some((row) => row[field] > 0))
    .map(([, name]) => name);
  const output = rows.map(({ daily: _daily, weekly: _weekly, ...row }) => row);
  return { shifts: output, weekly_paid_minutes: weeklyPaid,
    weekly_cents: output.reduce((sum, row) => sum + row.cents, 0), applied };
}
