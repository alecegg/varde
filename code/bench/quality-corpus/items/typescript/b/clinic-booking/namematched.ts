type Row = Record<string, unknown>;
type Request = Row & { doctors: Row[]; bookings: Row[]; holidays: unknown[] };
type Doctor = Row & { name: string; key: string; windows: Row[] };
type Booking = Row & { key: string };
type RequestData = Row & {
  doctors: Doctor[]; bookings: Booking[]; holidays: unknown[]; kind: string;
  preferred_doctor: string; preferred_key: string;
};
type Slot = { day: number; start: number; end: number; name: string; key: string };
type Failure = { error: string; index: number | null };
const KINDS: Record<string, [number, number]> = {
  checkup: [20, 5], consultation: [30, 10], procedure: [60, 15],
};
const TRACE = [
  "normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
  "doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
  "earliest-grid-slot",
];

/** Return the earliest valid appointment or the first validation error. */
export function solution(request: Request): Record<string, unknown> {
  const data = prepare(request), issue = validate(data);
  if (issue) return issue;
  const slot = selectFirst(candidateDays(data).flatMap((day) => candidatesForDay(data, day)));
  return slot ? makeSuccess(slot) : makeFailure("NO_SLOT", null);
}
function prepare(x: Row): RequestData { return requestFields(x); }
function requestFields(x: Row): RequestData {
  const base = normalisedRows(x);
  return {
    ...base, kind: cleanKind(x.kind), preferred_doctor: cleanName(x.preferred_doctor),
    preferred_key: nameKey(x.preferred_doctor),
  } as RequestData;
}
function normalisedRows(x: Row): Row {
  return {
    ...x, doctors: (x.doctors as Row[]).map((row) => cleanDoctor(row)),
    bookings: (x.bookings as Row[]).map((row) => cleanBooking(row)),
    holidays: x.holidays as unknown[],
  };
}
function cleanKind(v: unknown): string {
  return typeof v === "string" ? v.trim().toLowerCase() : v as string;
}
function cleanName(v: unknown): string { return typeof v === "string" ? v.trim() : v as string; }
function nameKey(v: unknown): string { return validNameKey(v); }
function validNameKey(v: unknown): string {
  if (typeof v !== "string") return "";
  const s = v.trim();
  return s && /^[A-Za-z0-9 -]+$/.test(s) ? s.toLowerCase() : "";
}
function cleanDoctor(v: Row): Doctor {
  return {
    ...v, name: cleanName(v.name), key: validNameKey(v.name),
    windows: v.windows as Row[],
  } as Doctor;
}
function cleanBooking(v: Row): Booking {
  return { ...v, doctor: cleanName(v.doctor), key: validNameKey(v.doctor) };
}
function validate(x: RequestData): Failure | null {
  if (!scalarFieldsValid(x)) return makeFailure("BAD_REQUEST", null);
  for (const check of [checkDoctors, checkWindows, checkHolidays, checkBookings]) {
    const issue = check(x);
    if (issue) return issue;
  }
  return checkOrder(x);
}
function scalarFieldsValid(x: RequestData): boolean { return boundsValid(x) && flagsValid(x); }
function boundsValid(x: RequestData): boolean {
  return [x.now_day, x.now_minute, x.requested_day, x.horizon_days]
    .every((v, i) => integerRange(v, [0, 0, 0, 0][i], [1000000, 1439, 1000000, 14][i]));
}
function flagsValid(x: RequestData): boolean {
  return typeof x.urgent === "boolean" && typeof x.kind === "string"
    && Object.hasOwn(KINDS, x.kind) && typeof x.preferred_doctor === "string";
}
function integerRange(v: unknown, lo: number, hi: number): boolean {
  return typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi;
}
function checkDoctors(x: RequestData): Failure | null { return uniqueDoctors(x.doctors); }
function uniqueDoctors(rows: Doctor[]): Failure | null {
  if (rows.length < 1 || rows.length > 12) return makeFailure("BAD_DOCTORS", null);
  return uniqueDoctorRows(rows);
}
function uniqueDoctorRows(rows: Doctor[]): Failure | null {
  const seen = new Set<string>();
  for (let i = 0; i < rows.length; i++) {
    const key = rows[i].key;
    if (!key || seen.has(key)) return makeFailure("BAD_DOCTORS", i);
    seen.add(key);
  }
  return null;
}
function checkWindows(x: RequestData): Failure | null { return windowsValid(x.doctors); }
function windowsValid(rows: Doctor[]): Failure | null {
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].windows.length > 8 || !rows[i].windows.every((window) => windowValid(window))) {
      return makeFailure("BAD_WINDOW", i);
    }
  }
  return null;
}
function windowValid(v: Row): boolean {
  return integerRange(v.weekday, 0, 6) && integerRange(v.open, 0, 1440)
    && integerRange(v.close, 0, 1440)
    && (v.open as number) < (v.close as number);
}
function checkHolidays(x: RequestData): Failure | null { return uniqueHolidays(x.holidays); }
function uniqueHolidays(rows: unknown[]): Failure | null {
  if (rows.length > 60) return makeFailure("BAD_HOLIDAY", null);
  return holidayCountValid(rows);
}
function holidayCountValid(rows: unknown[]): Failure | null {
  return uniqueHolidayRows(rows);
}
function uniqueHolidayRows(rows: unknown[]): Failure | null {
  const seen = new Set<unknown>();
  for (let i = 0; i < rows.length; i++) {
    if (!uniqueHoliday(rows[i], seen)) return makeFailure("BAD_HOLIDAY", i);
  }
  return null;
}
function uniqueHoliday(day: unknown, seen: Set<unknown>): boolean {
  if (!integerRange(day, 0, 1000000) || seen.has(day)) return false;
  seen.add(day);
  return true;
}
function checkBookings(x: RequestData): Failure | null { return bookingRowsValid(x); }
function bookingRowsValid(x: RequestData): Failure | null {
  if (x.bookings.length > 200) return makeFailure("BAD_BOOKING", null);
  return validBookingRows(x);
}
function validBookingRows(x: RequestData): Failure | null {
  const names = new Set(x.doctors.map((doctor) => doctor.key));
  for (let i = 0; i < x.bookings.length; i++) {
    const row = x.bookings[i];
    if (!bookingValid(row, names)) return makeFailure("BAD_BOOKING", i);
  }
  return null;
}
function bookingValid(v: Booking, names: Set<string>): boolean {
  return integerRange(v.day, 0, 1000000) && integerRange(v.start, 0, 1440)
    && integerRange(v.end, 0, 1440)
    && (v.start as number) < (v.end as number) && names.has(v.key);
}
function checkOrder(x: RequestData): Failure | null {
  const names = new Set(x.doctors.map((doctor) => doctor.key));
  if (x.preferred_doctor && !names.has(x.preferred_key)) return makeFailure("UNKNOWN_DOCTOR", null);
  return dayOrderValid(x);
}
function dayOrderValid(x: RequestData): Failure | null {
  return x.requested_day >= (x.now_day as number)
    && x.requested_day <= (x.now_day as number) + 8 ? null : makeFailure("BAD_DAY_ORDER", null);
}
function candidatesForDay(x: RequestData, day: number): Slot[] {
  const slots: Slot[] = [];
  for (const start of gridStarts()) for (const doctor of x.doctors) {
    if (!doctorEligible(x, doctor)) continue;
    const slot = makeCandidate(x, day, start, doctor);
    if (slot) slots.push(slot);
  }
  return slots;
}
function candidateDays(x: RequestData): number[] {
  const first = x.requested_day as number;
  const last = Math.min(first + (x.horizon_days as number), first + 14, 1000000);
  return Array.from({ length: last - first + 1 }, (_, i) => first + i)
    .filter((day) => !isHoliday(x, day));
}
function isHoliday(x: RequestData, day: number): boolean { return x.holidays.includes(day); }
function gridStarts(): number[] { return Array.from({ length: 288 }, (_, i) => i * 5); }
function doctorEligible(x: RequestData, doctor: Doctor): boolean {
  return x.urgent || !x.preferred_doctor || doctor.key === x.preferred_key;
}
function makeCandidate(
  x: RequestData, day: number, start: number, doctor: Doctor,
): Slot | null {
  const [duration, buffer] = KINDS[x.kind];
  const end = start + duration, occupied = end + buffer;
  return candidateWithAvailability(x, day, start, end, occupied, doctor);
}
function candidateWithAvailability(
  x: RequestData, day: number, start: number, end: number,
  occupied: number, doctor: Doctor,
): Slot | null {
  const [weekday, bookings] = dayBookings(x, day, doctor);
  return slotChecks(x, day, start, occupied, weekday, bookings, doctor)
    ? makeSlot(day, start, end, doctor) : null;
}
function dayBookings(x: RequestData, day: number, doctor: Doctor): [number, Booking[]] {
  return [day % 7, x.bookings.filter((row) => row.day === day && row.key === doctor.key)];
}
function slotChecks(
  x: RequestData, day: number, start: number, end: number, weekday: number,
  bookings: Booking[], doctor: Doctor,
): boolean {
  return matchesWindow(doctor, weekday, start, end) && fitsOpeningAndLunch(weekday, start, end)
    && bookingAvailable(x, day, start, end, bookings);
}
function makeSlot(day: number, start: number, end: number, doctor: Doctor): Slot {
  return { day, start, end, name: doctor.name, key: doctor.key };
}
function bookingAvailable(
  x: RequestData, day: number, start: number, end: number, bookings: Booking[],
): boolean {
  return meetsNotice(x, day, start)
    && belowDailyCap(bookings) && noBookingOverlap(start, end, bookings);
}
function matchesWindow(doctor: Doctor, day: number, start: number, end: number): boolean {
  return doctor.windows.some((w) => w.weekday === day
    && (w.open as number) <= start && end <= (w.close as number));
}
function fitsOpeningAndLunch(day: number, start: number, end: number): boolean {
  return openingContains(day, start, end) && !overlapsLunch(start, end);
}
function openingContains(day: number, start: number, end: number): boolean {
  const open = day === 5 ? 600 : day === 6 ? 0 : 540;
  const close = day === 5 ? 840 : day === 6 ? 0 : 1020;
  return open <= start && end <= close;
}
function overlapsLunch(start: number, end: number): boolean { return start < 780 && end > 720; }
function meetsNotice(x: RequestData, day: number, start: number): boolean {
  return day > (x.now_day as number) || start >= (x.now_minute as number) + 60;
}
function belowDailyCap(rows: Booking[]): boolean { return rows.length < 4; }
function noBookingOverlap(start: number, end: number, rows: Booking[]): boolean {
  return rows.every((row) => start >= (row.end as number) || end <= (row.start as number));
}
function selectFirst(rows: Slot[]): Slot | null {
  return rows.sort((a, b) => slotOrder(a, b))[0] ?? null;
}
function slotOrder(a: Slot, b: Slot): number {
  return a.day - b.day || a.start - b.start
    || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
}
function makeSuccess(slot: Slot): Row { return successRecord(slot); }
function successRecord(slot: Slot): Row {
  return { day: slot.day, start: slot.start, end: slot.end, doctor: slot.name, trace: TRACE };
}
function makeFailure(code: string, index: number | null): Failure {
  return errorRecord(code, index);
}
function errorRecord(code: string, index: number | null): Failure { return { error: code, index }; }
