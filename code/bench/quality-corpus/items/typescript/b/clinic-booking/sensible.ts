type Row = Record<string, unknown>;
type Request = Row & { doctors: Row[]; bookings: Row[]; holidays: unknown[] };
type Failure = { error: string; index: number | null };
type Doctor = Row & { name: string; key: string; windows: Row[] };
type Booking = Row & { key: string };
type Data = Request & {
  kind: string;
  preferred_doctor: string;
  preferred_key: string;
  doctors: Doctor[];
  bookings: Booking[];
};
type Slot = { day: number; start: number; end: number; doctor: string; key: string };

const KINDS: Record<string, [number, number]> = {
  checkup: [20, 5],
  consultation: [30, 10],
  procedure: [60, 15],
};
const OPENINGS: [number, number][] = [
  [540, 1020], [540, 1020], [540, 1020], [540, 1020], [540, 1020],
  [600, 840], [0, 0],
];
const TRACE = [
  "normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
  "doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
  "earliest-grid-slot",
];

/** Return the earliest valid appointment or the first validation error. */
export function solution(request: Request): Record<string, unknown> {
  const data = normalise(request);
  const error = validate(data);
  if (error) return error;

  const slot = findSlot(data);
  if (!slot) return { error: "NO_SLOT", index: null };
  return {
    day: slot.day,
    start: slot.start,
    end: slot.end,
    doctor: slot.doctor,
    trace: TRACE,
  };
}

function normalise(request: Request): Data {
  const kind = typeof request.kind === "string"
    ? request.kind.trim().toLowerCase()
    : request.kind;
  const preferred = typeof request.preferred_doctor === "string"
    ? request.preferred_doctor.trim()
    : request.preferred_doctor;
  return {
    ...request,
    kind,
    preferred_doctor: preferred,
    preferred_key: nameKey(preferred),
    ...normaliseRecords(request),
  } as Data;
}

function normaliseRecords(request: Request): Pick<Data, "doctors" | "bookings"> {
  const doctors = request.doctors.map((row) => ({
    ...row,
    name: typeof row.name === "string" ? row.name.trim() : row.name,
    key: nameKey(row.name),
  }));
  const bookings = request.bookings.map((row) => ({
    ...row,
    doctor: typeof row.doctor === "string" ? row.doctor.trim() : row.doctor,
    key: nameKey(row.doctor),
  }));
  return { doctors, bookings };
}

function nameKey(value: unknown): string {
  if (typeof value !== "string") return "";
  const cleaned = value.trim();
  if (!cleaned || !/^[A-Za-z0-9 -]+$/.test(cleaned)) return "";
  return cleaned.toLowerCase();
}

function validate(data: Data): Failure | null {
  if (!checkScalars(data)) return { error: "BAD_REQUEST", index: null };
  const listIssue = validateLists(data);
  if (listIssue) return listIssue;
  const bookingIssue = checkBookings(data);
  if (bookingIssue) return bookingIssue;
  return checkPreferenceAndDay(data);
}

function checkPreferenceAndDay(data: Data): Failure | null {
  const names = new Set(data.doctors.map((doctor) => doctor.key));
  if (data.preferred_doctor && !names.has(data.preferred_key)) {
    return { error: "UNKNOWN_DOCTOR", index: null };
  }
  const ordered = data.requested_day >= (data.now_day as number)
    && data.requested_day <= (data.now_day as number) + 8;
  return ordered ? null : { error: "BAD_DAY_ORDER", index: null };
}

function validateLists(data: Data): Failure | null {
  const doctorIssue = checkDoctors(data);
  if (doctorIssue) return doctorIssue;
  const windowIssue = checkWindows(data);
  if (windowIssue) return windowIssue;
  const holidayIssue = checkHolidays(data);
  if (holidayIssue) return holidayIssue;
  return null;
}

function checkScalars(data: Data): boolean {
  const inRange = (value: unknown, low: number, high: number) =>
    typeof value === "number" && Number.isInteger(value)
      && value >= low && value <= high;
  return inRange(data.now_day, 0, 1_000_000)
    && inRange(data.now_minute, 0, 1439)
    && inRange(data.requested_day, 0, 1_000_000)
    && inRange(data.horizon_days, 0, 14)
    && typeof data.urgent === "boolean"
    && typeof data.kind === "string"
    && Object.hasOwn(KINDS, data.kind)
    && typeof data.preferred_doctor === "string";
}

function checkDoctors(data: Data): Failure | null {
  if (data.doctors.length < 1 || data.doctors.length > 12) {
    return { error: "BAD_DOCTORS", index: null };
  }
  const seen = new Set<string>();
  for (let index = 0; index < data.doctors.length; index++) {
    const key = data.doctors[index].key;
    if (!key || seen.has(key)) return { error: "BAD_DOCTORS", index };
    seen.add(key);
  }
  return null;
}

function checkWindows(data: Data): Failure | null {
  const inRange = (value: unknown, low: number, high: number) =>
    typeof value === "number" && Number.isInteger(value)
      && value >= low && value <= high;
  for (let index = 0; index < data.doctors.length; index++) {
    const windows = data.doctors[index].windows;
    if (windows.length > 8) return { error: "BAD_WINDOW", index };
    for (const window of windows) {
      if (!inRange(window.weekday, 0, 6)
        || !inRange(window.open, 0, 1439)
        || !inRange(window.close, 1, 1440)
        || (window.open as number) >= (window.close as number)) {
        return { error: "BAD_WINDOW", index };
      }
    }
  }
  return null;
}

function checkHolidays(data: Data): Failure | null {
  if (data.holidays.length > 60) return { error: "BAD_HOLIDAY", index: null };
  const seen = new Set<unknown>();
  for (let index = 0; index < data.holidays.length; index++) {
    const day = data.holidays[index];
    const validDay = typeof day === "number" && Number.isInteger(day)
      && day >= 0 && day <= 1_000_000;
    if (!validDay || seen.has(day)) {
      return { error: "BAD_HOLIDAY", index };
    }
    seen.add(day);
  }
  return null;
}

function checkBookings(data: Data): Failure | null {
  if (data.bookings.length > 200) return { error: "BAD_BOOKING", index: null };
  const names = new Set(data.doctors.map((doctor) => doctor.key));
  for (let index = 0; index < data.bookings.length; index++) {
    const booking = data.bookings[index];
    if (!bookingIsValid(booking, names)) return { error: "BAD_BOOKING", index };
  }
  return null;
}

function bookingIsValid(booking: Booking, names: Set<string>): boolean {
  return typeof booking.day === "number" && Number.isInteger(booking.day)
    && booking.day >= 0 && booking.day <= 1_000_000
    && typeof booking.start === "number" && Number.isInteger(booking.start)
    && booking.start >= 0 && booking.start <= 1439
    && typeof booking.end === "number" && Number.isInteger(booking.end)
    && booking.end >= 1 && booking.end <= 1440
    && (booking.start as number) < (booking.end as number)
    && names.has(booking.key);
}

function findSlot(data: Data): Slot | null {
  const [duration, buffer] = KINDS[data.kind];
  const lastDay = Math.min(
    (data.requested_day as number) + (data.horizon_days as number),
    (data.requested_day as number) + 14,
    1_000_000,
  );
  const slots: Slot[] = [];
  for (let day = data.requested_day as number; day <= lastDay; day++) {
    if (data.holidays.includes(day)) continue;
    slots.push(...slotsForDay(data, day, duration, buffer));
  }
  return earliestSlot(slots);
}

function earliestSlot(slots: Slot[]): Slot | null {
  slots.sort((a, b) => a.day - b.day || a.start - b.start
    || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  return slots[0] ?? null;
}

function slotsForDay(data: Data, day: number, duration: number, buffer: number) {
  const slots: Slot[] = [];
  for (let start = 0; start <= 1435; start += 5) {
    for (const doctor of data.doctors) {
      if (data.preferred_doctor && !data.urgent
        && doctor.key !== data.preferred_key) continue;
      const end = start + duration;
      if (!timeAllows(data, doctor, day, start, end + buffer)
        || !bookingsAllow(data, doctor, day, start, end + buffer)) continue;
      slots.push({ day, start, end, doctor: doctor.name, key: doctor.key });
    }
  }
  return slots;
}

function timeAllows(
  data: Data,
  doctor: Doctor,
  day: number,
  start: number,
  reservedEnd: number,
): boolean {
  const weekday = day % 7;
  const [opening, closing] = OPENINGS[weekday];
  if (start < opening || reservedEnd > closing
    || (start < 780 && reservedEnd > 720)
    || (day === data.now_day && start < (data.now_minute as number) + 60)) return false;
  return doctor.windows.some((window) =>
    window.weekday === weekday && (window.open as number) <= start
      && reservedEnd <= (window.close as number));
}

function bookingsAllow(
  data: Data,
  doctor: Doctor,
  day: number,
  start: number,
  reservedEnd: number,
): boolean {
  const bookings = data.bookings.filter((booking) =>
    booking.day === day && booking.key === doctor.key);
  if (bookings.length >= 4) return false;
  return !bookings.some((booking) =>
    start < (booking.end as number) && (booking.start as number) < reservedEnd);
}
