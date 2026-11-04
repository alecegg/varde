type Row = Record<string, unknown>;
type Request = Row & { doctors: Row[]; bookings: Row[]; holidays: unknown[] };

const KINDS: Record<string, [number, number]> = {
  checkup: [20, 5],
  consultation: [30, 10],
  procedure: [60, 15],
};
const TRACE = [
  "normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
  "doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
  "earliest-grid-slot",
];

/** Return the earliest valid appointment or the first validation error. */
export function solution(request: Request): Record<string, unknown> {
  const kindValue = request.kind;
  const kind = typeof kindValue === "string" ? kindValue.trim().toLowerCase() : kindValue;
  const preferredValue = request.preferred_doctor;
  const preferred = typeof preferredValue === "string" ? preferredValue.trim() : preferredValue;
  const preferredKey = typeof preferred === "string" ? preferred.toLowerCase() : "";
  const doctors: (Row & { name: unknown; key: string })[] = [];
  for (const inputDoctor of request.doctors) {
    const rawDoctorName = inputDoctor.name;
    const trimmedDoctorName = typeof rawDoctorName === "string"
      ? rawDoctorName.trim()
      : rawDoctorName;
    const normalizedDoctorKey = typeof trimmedDoctorName === "string"
      ? trimmedDoctorName.toLowerCase()
      : "";
    doctors.push({
      ...inputDoctor,
      name: trimmedDoctorName,
      key: normalizedDoctorKey,
    });
  }
  const bookings: (Row & { doctor: unknown; key: string })[] = [];
  for (const inputBooking of request.bookings) {
    const rawBookingDoctor = inputBooking.doctor;
    const trimmedBookingDoctor = typeof rawBookingDoctor === "string"
      ? rawBookingDoctor.trim()
      : rawBookingDoctor;
    const normalizedBookingKey = typeof trimmedBookingDoctor === "string"
      ? trimmedBookingDoctor.toLowerCase()
      : "";
    bookings.push({
      ...inputBooking,
      doctor: trimmedBookingDoctor,
      key: normalizedBookingKey,
    });
  }
  const kindIsValid = typeof kind === "string" && Object.hasOwn(KINDS, kind);
  const nowDayIsInteger = typeof request.now_day === "number"
    && Number.isInteger(request.now_day);
  const nowDayIsInRange = nowDayIsInteger
    && request.now_day >= 0 && request.now_day <= 1_000_000;
  const nowMinuteIsInteger = typeof request.now_minute === "number"
    && Number.isInteger(request.now_minute);
  const nowMinuteIsInRange = nowMinuteIsInteger
    && request.now_minute >= 0 && request.now_minute <= 1439;
  const requestedDayIsInteger = typeof request.requested_day === "number"
    && Number.isInteger(request.requested_day);
  const requestedDayIsInRange = requestedDayIsInteger
    && request.requested_day >= 0 && request.requested_day <= 1_000_000;
  const horizonIsInteger = typeof request.horizon_days === "number"
    && Number.isInteger(request.horizon_days);
  const horizonIsInRange = horizonIsInteger
    && request.horizon_days >= 0 && request.horizon_days <= 14;
  const urgencyIsBoolean = typeof request.urgent === "boolean";
  const preferredNameIsText = typeof preferred === "string";
  const scalarFieldsAreValid = nowDayIsInRange && nowMinuteIsInRange
    && requestedDayIsInRange && horizonIsInRange
    && urgencyIsBoolean && kindIsValid && preferredNameIsText;
  if (!scalarFieldsAreValid) return { error: "BAD_REQUEST", index: null };

  if (doctors.length < 1 || doctors.length > 12) return { error: "BAD_DOCTORS", index: null };
  const known = new Set<string>();
  for (let index = 0; index < doctors.length; index++) {
    const doctor = doctors[index];
    const name = doctor.name;
    const key = doctor.key;
    const doctorNameIsText = typeof name === "string";
    const doctorNameHasAllowedCharacters = doctorNameIsText
      && /^[A-Za-z0-9 -]+$/.test(name);
    const doctorNameIsNotEmpty = doctorNameIsText && name.length > 0;
    const normalizedDoctorNameWasSeen = known.has(key);
    if (!doctorNameIsText || !doctorNameHasAllowedCharacters
      || !doctorNameIsNotEmpty || normalizedDoctorNameWasSeen) {
      return { error: "BAD_DOCTORS", index };
    }
    known.add(key);
  }
  for (let index = 0; index < doctors.length; index++) {
    const windows = doctors[index].windows;
    if (windows.length > 8) return { error: "BAD_WINDOW", index };
    for (const window of windows) {
      const weekdayIsInteger = typeof window.weekday === "number"
        && Number.isInteger(window.weekday);
      const weekdayIsInRange = weekdayIsInteger
        && window.weekday >= 0 && window.weekday <= 6;
      const openingMinuteIsInteger = typeof window.open === "number"
        && Number.isInteger(window.open);
      const openingMinuteIsInRange = openingMinuteIsInteger
        && window.open >= 0 && window.open <= 1440;
      const closingMinuteIsInteger = typeof window.close === "number"
        && Number.isInteger(window.close);
      const closingMinuteIsInRange = closingMinuteIsInteger
        && window.close >= 0 && window.close <= 1440;
      const windowIntervalIsOrdered = (window.open as number) < (window.close as number);
      if (!weekdayIsInRange || !openingMinuteIsInRange
        || !closingMinuteIsInRange || !windowIntervalIsOrdered) {
        return { error: "BAD_WINDOW", index };
      }
    }
  }
  if (request.holidays.length > 60) return { error: "BAD_HOLIDAY", index: null };
  const holidays = new Set<unknown>();
  for (let index = 0; index < request.holidays.length; index++) {
    const day = request.holidays[index];
    if (!(typeof day === "number" && Number.isInteger(day) && day >= 0 && day <= 1_000_000)
      || holidays.has(day)) return { error: "BAD_HOLIDAY", index };
    holidays.add(day);
  }
  if (bookings.length > 200) return { error: "BAD_BOOKING", index: null };
  for (let index = 0; index < bookings.length; index++) {
    const booking = bookings[index];
    const bookingDayIsInteger = typeof booking.day === "number"
      && Number.isInteger(booking.day);
    const bookingDayIsInRange = bookingDayIsInteger
      && booking.day >= 0 && booking.day <= 1_000_000;
    const bookingStartIsInteger = typeof booking.start === "number"
      && Number.isInteger(booking.start);
    const bookingStartIsInRange = bookingStartIsInteger
      && booking.start >= 0 && booking.start <= 1440;
    const bookingEndIsInteger = typeof booking.end === "number"
      && Number.isInteger(booking.end);
    const bookingEndIsInRange = bookingEndIsInteger
      && booking.end >= 0 && booking.end <= 1440;
    const bookingIntervalIsOrdered = (booking.start as number) < (booking.end as number);
    const bookingDoctorExists = known.has(booking.key);
    if (!bookingDayIsInRange || !bookingStartIsInRange || !bookingEndIsInRange
      || !bookingIntervalIsOrdered || !bookingDoctorExists) {
      return { error: "BAD_BOOKING", index };
    }
  }
  if (preferred && !known.has(preferredKey)) return { error: "UNKNOWN_DOCTOR", index: null };
  const requestDay = request.requested_day as number;
  const currentDay = request.now_day as number;
  const requestDayIsBeforeToday = requestDay < currentDay;
  const requestDayIsToday = requestDay === currentDay;
  const requestedOffset = requestDay - currentDay;
  const requestDayIsAfterBookingWindow = requestedOffset > 8;
  const requestDayIsWithinBookingWindow = requestDayIsToday
    || (requestedOffset >= 0 && !requestDayIsAfterBookingWindow);
  const requestDayOrderIsInvalid = requestDayIsBeforeToday
    || !requestDayIsWithinBookingWindow;
  if (requestDayOrderIsInvalid) {
    return { error: "BAD_DAY_ORDER", index: null };
  }

  const [duration, buffer] = KINDS[kind as string];
  const earliestDay = request.requested_day as number;
  const lastDay = Math.min(
    earliestDay + (request.horizon_days as number),
    earliestDay + 14,
    1_000_000,
  );
  const candidates: { day: number; start: number; end: number; name: string; key: string }[] = [];
  for (let day = earliestDay; day <= lastDay; day++) {
    if (holidays.has(day)) continue;
    const weekday = day % 7;
    const opening = weekday === 5 ? 600 : weekday === 6 ? 0 : 540;
    const closing = weekday === 5 ? 840 : weekday === 6 ? 0 : 1020;
    for (const doctor of doctors) {
      if (!request.urgent && preferred && doctor.key !== preferredKey) continue;
      for (let start = 0; start <= 1435; start += 5) {
        const appointmentEnd = start + duration;
        const reservedEnd = appointmentEnd + buffer;
        const candidateStartsDuringClinicHours = start >= opening;
        const candidateEndsBeforeClinicCloses = reservedEnd <= closing;
        const reservedIntervalFitsClinicHours =
          candidateStartsDuringClinicHours && candidateEndsBeforeClinicCloses;
        if (!reservedIntervalFitsClinicHours) continue;
        const startsBeforeLunchEnds = start < 780;
        const endsAfterLunchStarts = reservedEnd > 720;
        const reservedIntervalOverlapsLunch =
          startsBeforeLunchEnds && endsAfterLunchStarts;
        if (reservedIntervalOverlapsLunch) continue;
        if (day === request.now_day && start < (request.now_minute as number) + 60) continue;
        let covered = false;
        for (const window of doctor.windows) {
          const windowMatchesWeekday = window.weekday === weekday;
          const candidateStartsAfterWindowOpens = (window.open as number) <= start;
          const reservationEndsBeforeWindowCloses = reservedEnd <= (window.close as number);
          const windowContainsReservation = windowMatchesWeekday
            && candidateStartsAfterWindowOpens && reservationEndsBeforeWindowCloses;
          if (windowContainsReservation) covered = true;
        }
        if (!covered) continue;
        const sameDay = bookings.filter((booking) =>
          booking.day === day && booking.key === doctor.key);
        if (sameDay.length >= 4) continue;
        let collision = false;
        for (const booking of sameDay) {
          const candidateStartsBeforeBookingEnds = start < (booking.end as number);
          const bookingStartsBeforeReservationEnds = (booking.start as number) < reservedEnd;
          const intervalsOverlap = candidateStartsBeforeBookingEnds
            && bookingStartsBeforeReservationEnds;
          if (intervalsOverlap) collision = true;
        }
        if (collision) continue;
        candidates.push({
          day,
          start,
          end: appointmentEnd,
          name: doctor.name as string,
          key: doctor.key,
        });
      }
    }
  }
  candidates.sort((left, right) => {
    const dayDifference = left.day - right.day;
    const startsAreOnSameDay = dayDifference === 0;
    const startDifference = left.start - right.start;
    const startsAreTied = startsAreOnSameDay && startDifference === 0;
    const namesAreOrdered = left.key < right.key;
    const namesAreReversed = left.key > right.key;
    if (!startsAreOnSameDay) return dayDifference;
    if (startDifference !== 0) return startDifference;
    if (startsAreTied && left.key === right.key) return 0;
    if (namesAreOrdered) return -1;
    if (namesAreReversed) return 1;
    return 0;
  });
  const first = candidates[0];
  if (!first) return { error: "NO_SLOT", index: null };
  return { day: first.day, start: first.start, end: first.end, doctor: first.name, trace: TRACE };
}
