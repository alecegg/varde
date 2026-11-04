type Row = Record<string, unknown>;
type Request = Row & { doctors: Row[]; bookings: Row[]; holidays: unknown[] };
type Doctor = Row & { name: string; key: string; windows: Row[] };
type Booking = Row & { doctor: string; key: string };
type Data = Request & {
  kind: string;
  preferred_doctor: string;
  preferred_key: string;
  doctors: Doctor[];
  bookings: Booking[];
};
type Failure = { error: string; index: number | null };
type Slot = { day: number; start: number; end: number; doctor: string; key: string };

const KINDS: Record<string, [number, number]> = {
  checkup: [20, 5],
  consultation: [30, 10],
  procedure: [60, 15],
};

/** Return the earliest valid appointment or the first validation error. */
export function solution(request: Request): Record<string, unknown> {
  const kind = typeof request.kind === "string" ? request.kind.trim().toLowerCase() : request.kind;
  const preferred = typeof request.preferred_doctor === "string"
    ? request.preferred_doctor.trim() : request.preferred_doctor;
  const doctors = normaliseRecords(request.doctors, "name") as Doctor[];
  const bookings = normaliseRecords(request.bookings, "doctor") as Booking[];
  const data = {
    ...request,
    kind,
    preferred_doctor: preferred,
    preferred_key: typeof preferred === "string" ? preferred.toLowerCase() : "",
    doctors,
    bookings,
  } as Data;
  const issue = validate(data);
  if (issue) return issue;
  const candidates = collectSlots(data);
  candidates.sort((left, right) => left.day - right.day || left.start - right.start
    || (left.key < right.key ? -1 : left.key > right.key ? 1 : 0));
  const selected = candidates[0];
  if (!selected) return { error: "NO_SLOT", index: null };
  return successRecord(selected);
}

function successRecord(selected: Slot): Record<string, unknown> {
  return {
    day: selected.day, start: selected.start, end: selected.end,
    doctor: selected.doctor, trace: makeTrace(),
  };
}

function makeTrace(): string[] {
  const events = [
    "normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
    "doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
    "earliest-grid-slot",
  ];
  return events;
}

function normaliseRecords(rows: Row[], field: "name" | "doctor"): Row[] {
  return rows.map((row) => {
    const rawName = row[field];
    const cleanedName = typeof rawName === "string" ? rawName.trim() : rawName;
    const key = typeof cleanedName === "string" ? cleanedName.toLowerCase() : "";
    return { ...row, [field]: cleanedName, key };
  });
}

function validate(data: Data): Failure | null {
  const scalarIssue = checkScalars(data);
  if (scalarIssue) return scalarIssue;
  const doctorIssue = checkDoctors(data);
  if (doctorIssue) return doctorIssue;
  const windowIssue = checkWindows(data);
  if (windowIssue) return windowIssue;
  const holidayIssue = checkHolidays(data);
  if (holidayIssue) return holidayIssue;
  const bookingIssue = checkBookings(data);
  if (bookingIssue) return bookingIssue;
  const requestIssue = checkRequest(data);
  if (requestIssue) return requestIssue;
  return null;
}

function checkScalars(data: Data): Failure | null {
  if (!integerBetween(data.now_day, 0, 1_000_000)
    || !integerBetween(data.now_minute, 0, 1439)
    || !integerBetween(data.requested_day, 0, 1_000_000)
    || !integerBetween(data.horizon_days, 0, 14)
    || !Object.hasOwn(KINDS, data.kind)
    || typeof data.preferred_doctor !== "string"
    || typeof data.urgent !== "boolean") return { error: "BAD_REQUEST", index: null };
  return null;
}

function checkDoctors(data: Data): Failure | null {
  const total = data.doctors.length;
  if (total < 1 || total > 12) return { error: "BAD_DOCTORS", index: null };
  const seen = new Set<string>();
  for (let index = 0; index < total; index++) {
    const doctor = data.doctors[index];
    if (!doctorNameIsValid(doctor, seen)) return { error: "BAD_DOCTORS", index };
    seen.add(doctor.key);
  }
  return null;
}

function doctorNameIsValid(doctor: Doctor, seen: Set<string>): boolean {
  const nameIsText = typeof doctor.name === "string";
  if (!nameIsText || doctor.name.length === 0) return false;
  const nameHasAllowedCharacters = /^[A-Za-z0-9 -]+$/.test(doctor.name);
  const nameIsUnique = !seen.has(doctor.key);
  return nameHasAllowedCharacters && nameIsUnique;
}

function checkWindows(data: Data): Failure | null {
  for (let index = 0; index < data.doctors.length; index++) {
    const windows = data.doctors[index].windows;
    if (windows.length > 8) return { error: "BAD_WINDOW", index };
    for (const window of windows) {
      if (!windowIsValid(window)) {
        return { error: "BAD_WINDOW", index };
      }
    }
  }
  return null;
}

function windowIsValid(window: Row): boolean {
  const validWeekday = integerBetween(window.weekday, 0, 6);
  const validOpening = integerBetween(window.open, 0, 1440);
  const validClosing = integerBetween(window.close, 0, 1440);
  const openingPrecedesClosing = (window.open as number) < (window.close as number);
  return validWeekday && validOpening && validClosing && openingPrecedesClosing;
}

function checkHolidays(data: Data): Failure | null {
  if (data.holidays.length > 60) return { error: "BAD_HOLIDAY", index: null };
  const seen = new Set<unknown>();
  for (let index = 0; index < data.holidays.length; index++) {
    const day = data.holidays[index];
    if (!integerBetween(day, 0, 1_000_000) || seen.has(day)) {
      return { error: "BAD_HOLIDAY", index };
    }
    seen.add(day);
  }
  return null;
}

function checkBookings(data: Data): Failure | null {
  if (data.bookings.length > 200) return { error: "BAD_BOOKING", index: null };
  const doctors = new Set(data.doctors.map((doctor) => doctor.key));
  for (let index = 0; index < data.bookings.length; index++) {
    const booking = data.bookings[index];
    if (!bookingIsValid(booking, doctors)) {
      return { error: "BAD_BOOKING", index };
    }
  }
  return null;
}

function bookingIsValid(booking: Booking, doctors: Set<string>): boolean {
  const validDay = integerBetween(booking.day, 0, 1_000_000);
  const validStart = integerBetween(booking.start, 0, 1440);
  const validEnd = integerBetween(booking.end, 0, 1440);
  const ordered = (booking.start as number) < (booking.end as number);
  return validDay && validStart && validEnd && ordered && doctors.has(booking.key);
}

function checkRequest(data: Data): Failure | null {
  const known = new Set(data.doctors.map((doctor) => doctor.key));
  if (data.preferred_doctor && !known.has(data.preferred_key)) {
    return { error: "UNKNOWN_DOCTOR", index: null };
  }
  const requestedDay = data.requested_day as number;
  const currentDay = data.now_day as number;
  const isOrdered = requestedDay >= currentDay && requestedDay - currentDay <= 8;
  return isOrdered ? null : { error: "BAD_DAY_ORDER", index: null };
}

function integerBetween(value: unknown, minimum: number, maximum: number): boolean {
  if (typeof value !== "number") return false;
  if (!Number.isInteger(value)) return false;
  const aboveMinimum = value >= minimum;
  const belowMaximum = value <= maximum;
  return aboveMinimum && belowMaximum;
}

function collectSlots(data: Data): Slot[] {
  const days = candidateDays(data);
  const doctors = eligibleDoctors(data);
  const candidates: Slot[] = [];
  for (const day of days) {
    for (const doctor of doctors) {
      for (let start = 0; start <= 1435; start += 5) {
        const slot = slotFor(data, doctor, day, start);
        if (slot) candidates.push(slot);
      }
    }
  }
  return candidates;
}

function candidateDays(data: Data): number[] {
  const requestedDay = data.requested_day as number;
  const lastDay = Math.min(
    requestedDay + (data.horizon_days as number),
    requestedDay + 14,
    1_000_000,
  );
  const days: number[] = [];
  for (let day = requestedDay; day <= lastDay; day++) {
    if (!data.holidays.includes(day)) days.push(day);
  }
  return days;
}

function eligibleDoctors(data: Data): Doctor[] {
  return data.doctors.filter((doctor) => data.urgent
    || !data.preferred_doctor || doctor.key === data.preferred_key);
}

function slotFor(
  data: Data,
  doctor: Doctor,
  day: number,
  start: number,
): Slot | null {
  const [duration, buffer] = KINDS[data.kind];
  const appointmentEnd = start + duration;
  const reservedEnd = appointmentEnd + buffer;
  if (!timeAllows(data, day, start, reservedEnd)) return null;
  if (!windowAllows(doctor, day, start, reservedEnd)) return null;
  if (!bookingAllows(data, doctor, day, start, reservedEnd)) return null;
  return { day, start, end: appointmentEnd, doctor: doctor.name, key: doctor.key };
}

function timeAllows(data: Data, day: number, start: number, reservedEnd: number): boolean {
  const weekday = day % 7;
  const opening = weekday === 5 ? 600 : weekday === 6 ? 0 : 540;
  const closing = weekday === 5 ? 840 : weekday === 6 ? 0 : 1020;
  const meetsNotice = day !== data.now_day || start >= (data.now_minute as number) + 60;
  return start >= opening && reservedEnd <= closing
    && !(start < 780 && reservedEnd > 720) && meetsNotice;
}

function windowAllows(doctor: Doctor, day: number, start: number, reservedEnd: number): boolean {
  const weekday = day % 7;
  return doctor.windows.some((window) => window.weekday === weekday
    && (window.open as number) <= start && reservedEnd <= (window.close as number));
}

function bookingAllows(
  data: Data,
  doctor: Doctor,
  day: number,
  start: number,
  reservedEnd: number,
): boolean {
  const sameDay = data.bookings.filter((booking) =>
    booking.day === day && booking.key === doctor.key);
  if (sameDay.length >= 4) return false;
  const hasConflict = sameDay.some((booking) =>
    start < (booking.end as number) && (booking.start as number) < reservedEnd);
  return !hasConflict;
}

