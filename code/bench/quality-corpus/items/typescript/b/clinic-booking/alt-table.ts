type Row = Record<string, unknown>;
type Request = Row & { doctors: Row[]; bookings: Row[]; holidays: unknown[] };
type Failure = { error: string; index: number | null };
type Doctor = Row & { name: string; key: string; windows: Row[] };
type Booking = Row & { key: string };
type Data = Request & {
  kind: unknown;
  preferred_doctor: unknown;
  preferred_key: string;
  doctors: Doctor[];
  bookings: Booking[];
};
type ValidData = Data & {
  kind: string;
  preferred_doctor: string;
  now_day: number;
  now_minute: number;
  requested_day: number;
  horizon_days: number;
  urgent: boolean;
};
type Slot = { day: number; start: number; end: number; doctor: string; key: string };
type Result<T> = { ok: true; value: T } | { ok: false; failure: Failure };
const KINDS: Record<string, [number, number]> = { checkup: [20, 5], consultation: [30, 10],
  procedure: [60, 15] };
const OPENINGS: [number, number][] = [[540, 1020], [540, 1020], [540, 1020], [540, 1020], [540,
  1020], [600, 840], [0, 0]];
const SCALAR_RANGES = [
  { field: "now_day", low: 0, high: 1_000_000 },
  { field: "now_minute", low: 0, high: 1439 },
  { field: "requested_day", low: 0, high: 1_000_000 },
  { field: "horizon_days", low: 0, high: 14 },
] as const;
const WINDOW_RANGES = [
  { field: "weekday", low: 0, high: 6 },
  { field: "open", low: 0, high: 1439 },
  { field: "close", low: 1, high: 1440 },
] as const;
const BOOKING_RANGES = [
  { field: "day", low: 0, high: 1_000_000 },
  { field: "start", low: 0, high: 1439 },
  { field: "end", low: 1, high: 1440 },
] as const;
const TRACE = ["normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
  "doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority", "earliest-grid-slot"];

/** Return the earliest valid appointment or the first validation error. */
export function solution(request: Request): Record<string, unknown> {
  const data = normalise(request);
  const checked = validate(data);
  if (!checked.ok) return checked.failure;
  const slot = findSlot(checked.value);
  if (!slot) return { error: "NO_SLOT", index: null };
  return { day: slot.day, start: slot.start, end: slot.end, doctor: slot.doctor, trace: TRACE };
}

function normalise(request: Request): Data {
  const kind = typeof request.kind === "string"
    ? request.kind.trim().toLowerCase() : request.kind;
  const preferred = typeof request.preferred_doctor === "string"
    ? request.preferred_doctor.trim() : request.preferred_doctor;
  return {
    ...request,
    kind,
    preferred_doctor: preferred,
    preferred_key: nameKey(preferred),
    doctors: normaliseDoctors(request.doctors),
    bookings: normaliseBookings(request.bookings),
  };
}

function normaliseDoctors(rows: Row[]): Doctor[] {
  return rows.map((row) => ({
    ...row,
    name: typeof row.name === "string" ? row.name.trim() : row.name,
    key: typeof row.name === "string" && row.name.trim()
      && /^[A-Za-z0-9 -]+$/.test(row.name.trim())
      ? row.name.trim().toLowerCase() : "",
  }));
}

function normaliseBookings(rows: Row[]): Booking[] {
  return rows.map((row) => ({
    ...row,
    doctor: typeof row.doctor === "string" ? row.doctor.trim() : row.doctor,
    key: typeof row.doctor === "string" && row.doctor.trim()
      && /^[A-Za-z0-9 -]+$/.test(row.doctor.trim())
      ? row.doctor.trim().toLowerCase() : "",
  }));
}

function nameKey(value: unknown): string {
  if (typeof value !== "string") return "";
  const cleaned = value.trim();
  return cleaned && /^[A-Za-z0-9 -]+$/.test(cleaned) ? cleaned.toLowerCase() : "";
}

function validate(data: Data): Result<ValidData> {
  if (!checkScalars(data)) return { ok: false, failure: { error: "BAD_REQUEST", index: null } };
  const listIssue = checkDoctors(data) ?? checkWindows(data) ?? checkHolidays(data);
  if (listIssue) return { ok: false, failure: listIssue };
  const bookingIssue = checkBookings(data);
  if (bookingIssue) return { ok: false, failure: bookingIssue };
  const issue = checkPreferenceAndDay(data);
  return issue ? { ok: false, failure: issue } : { ok: true, value: data };
}

function checkPreferenceAndDay(data: ValidData): Failure | null {
  const names = new Set(data.doctors.map((doctor) => doctor.key));
  if (data.preferred_doctor && !names.has(data.preferred_key)) return { error: "UNKNOWN_DOCTOR",
    index: null };
  return data.requested_day >= data.now_day && data.requested_day <= data.now_day + 8 ? null :
    { error: "BAD_DAY_ORDER", index: null };
}

function checkScalars(data: Data): data is ValidData {
  let inRange = true;
  for (const rule of SCALAR_RANGES) {
    const value = data[rule.field];
    if (typeof value !== "number" || !Number.isInteger(value)
      || value < rule.low || value > rule.high) inRange = false;
  }
  return inRange && typeof data.urgent === "boolean" && typeof data.kind === "string"
    && Object.hasOwn(KINDS, data.kind) && typeof data.preferred_doctor === "string";
}

function checkDoctors(data: Data): Failure | null {
  if (data.doctors.length < 1 || data.doctors.length > 12) return { error: "BAD_DOCTORS",
    index: null };
  const seen = new Set<string>();
  for (let index = 0; index < data.doctors.length; index++) {
    const key = data.doctors[index].key;
    if (!key || seen.has(key)) return { error: "BAD_DOCTORS", index };
    seen.add(key);
  }
  return null;
}

function checkWindows(data: Data): Failure | null {
  for (let index = 0; index < data.doctors.length; index++) {
    const windows = data.doctors[index].windows;
    if (windows.length > 8) return { error: "BAD_WINDOW", index };
    for (const window of windows) {
      let inRange = true;
      for (const { field, low, high } of WINDOW_RANGES) {
        const value = window[field];
        if (!Number.isInteger(value) || value < low || value > high) inRange = false;
      }
      if (!inRange || window.open >= window.close) return { error: "BAD_WINDOW", index };
    }
  }
  return null;
}


function checkHolidays(data: Data): Failure | null {
  if (data.holidays.length > 60) return { error: "BAD_HOLIDAY", index: null };
  const seen = new Set<unknown>();
  for (let index = 0; index < data.holidays.length; index++) {
    const day = data.holidays[index];
    if (typeof day !== "number" || !Number.isInteger(day) || day < 0 || day > 1_000_000 ||
      seen.has(day)) return { error: "BAD_HOLIDAY", index };
    seen.add(day);
  }
  return null;
}

function checkBookings(data: Data): Failure | null {
  if (data.bookings.length > 200) return { error: "BAD_BOOKING", index: null };
  const names = new Set(data.doctors.map((doctor) => doctor.key));
  for (let index = 0; index < data.bookings.length; index++) {
    if (!bookingIsValid(data.bookings[index], names)) return { error: "BAD_BOOKING", index };
  }
  return null;
}

function bookingIsValid(booking: Booking, names: Set<string>): boolean {
  let inRange = true;
  for (const rule of BOOKING_RANGES) {
    const value = booking[rule.field];
    if (typeof value !== "number" || !Number.isInteger(value)
      || value < rule.low || value > rule.high) inRange = false;
  }
  return inRange && booking.start < booking.end && names.has(booking.key);
}

function findSlot(data: ValidData): Slot | null {
  const [duration, buffer] = KINDS[data.kind];
  const lastDay = Math.min(data.requested_day + data.horizon_days, data.requested_day + 14,
    1_000_000);
  const slots: Slot[] = [];
  for (let day = data.requested_day; day <= lastDay; day++) {
    if (!data.holidays.includes(day)) slots.push(...slotsForDay(data, day, duration, buffer));
  }
  return earliestSlot(slots);
}

function earliestSlot(slots: Slot[]): Slot | null {
  slots.sort((a, b) => a.day - b.day || a.start - b.start || (a.key < b.key ? -1 :
    a.key > b.key ? 1 : 0));
  return slots[0] ?? null;
}

function slotsForDay(data: ValidData, day: number, duration: number, buffer: number): Slot[] {
  const slots: Slot[] = [];
  for (let start = 0; start <= 1435; start += 5) for (const doctor of data.doctors) {
    if (data.preferred_doctor && !data.urgent && doctor.key !== data.preferred_key) continue;
    const end = start + duration;
    if (timeAllows(data, doctor, day, start, end + buffer) && bookingsAllow(data, doctor, day,
      start, end + buffer)) slots.push({ day, start, end, doctor: doctor.name, key: doctor.key });
  }
  return slots;
}

function timeAllows(data: ValidData, doctor: Doctor, day: number, start: number,
  reservedEnd: number): boolean {
  const weekday = day % 7;
  const [opening, closing] = OPENINGS[weekday];
  const policy = start >= opening && reservedEnd <= closing
    && !(start < 780 && reservedEnd > 720)
    && (day !== data.now_day || start >= data.now_minute + 60);
  return policy && doctor.windows.some((window) => window.weekday === weekday
    && typeof window.open === "number" && typeof window.close === "number"
    && window.open <= start && reservedEnd <= window.close);
}

function bookingsAllow(data: ValidData, doctor: Doctor, day: number, start: number,
  reservedEnd: number): boolean {
  const bookings = data.bookings.filter((booking) => booking.day === day &&
    booking.key === doctor.key);
  if (bookings.length >= 4) return false;
  return !bookings.some((booking) => typeof booking.end === "number" &&
    typeof booking.start === "number" && start < booking.end && booking.start < reservedEnd);
}

