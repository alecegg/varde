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
  const kindInput = request.kind;
  const kind = typeof kindInput === "string" ? kindInput.trim().toLowerCase() : kindInput;
  const preferredInput = request.preferred_doctor;
  const preferred = typeof preferredInput === "string" ? preferredInput.trim() : preferredInput;
  const preferredIsText = typeof preferred === "string";
  const doctors = request.doctors.map((row) => ({
    ...row,
    name: typeof row.name === "string" ? row.name.trim() : row.name,
    key: typeof row.name === "string"
      ? row.name.trim().toLowerCase()
      : "",
  }));
  const bookings = request.bookings.map((row) => ({
    ...row,
    doctor: typeof row.doctor === "string" ? row.doctor.trim() : row.doctor,
    key: typeof row.doctor === "string" ? row.doctor.trim().toLowerCase() : "",
  }));
  const nowDayIsInteger = typeof request.now_day === "number"
    && Number.isInteger(request.now_day);
  const nowDayIsInRange = nowDayIsInteger
    && request.now_day >= 0 && request.now_day <= 1_000_000;
  const validNowDay = nowDayIsInRange;
  const nowMinuteIsInteger = typeof request.now_minute === "number"
    && Number.isInteger(request.now_minute);
  const nowMinuteIsInRange = nowMinuteIsInteger
    && request.now_minute >= 0 && request.now_minute <= 1439;
  const validNowMinute = nowMinuteIsInRange;
  const requestedDayIsInteger = typeof request.requested_day === "number"
    && Number.isInteger(request.requested_day);
  const requestedDayIsInRange = requestedDayIsInteger
    && request.requested_day >= 0 && request.requested_day <= 1_000_000;
  const validRequestedDay = requestedDayIsInRange;
  const horizonIsInteger = typeof request.horizon_days === "number"
    && Number.isInteger(request.horizon_days);
  const horizonIsInRange = horizonIsInteger
    && request.horizon_days >= 0 && request.horizon_days <= 14;
  const validHorizon = horizonIsInRange;
  const validKind = typeof kind === "string" && Object.hasOwn(KINDS, kind);
  const urgentIsBoolean = typeof request.urgent === "boolean";
  if (!validNowDay || !validNowMinute || !validRequestedDay || !validHorizon
    || !urgentIsBoolean || !validKind || !preferredIsText) {
    return { error: "BAD_REQUEST", index: null };
  }
  if (doctors.length < 1 || doctors.length > 12) return { error: "BAD_DOCTORS", index: null };
  const doctorKeys = new Set<string>();
  for (let index = 0; index < doctors.length; index++) {
    const doctor = doctors[index];
    const doctorNameIsText = typeof doctor.name === "string";
    const doctorNameIsPresent = doctorNameIsText && doctor.name.length > 0;
    const doctorNameUsesAllowedCharacters = doctorNameIsText
      && /^[A-Za-z0-9 -]+$/.test(doctor.name);
    const doctorNameWasAlreadySeen = doctorKeys.has(doctor.key);
    if (!doctorNameIsText || !doctorNameIsPresent || !doctorNameUsesAllowedCharacters
      || doctorNameWasAlreadySeen) return { error: "BAD_DOCTORS", index };
    doctorKeys.add(doctor.key);
  }
  for (let index = 0; index < doctors.length; index++) {
    const windows = doctors[index].windows;
    if (windows.length > 8) return { error: "BAD_WINDOW", index };
    for (const window of windows) {
      const weekdayIsInteger = typeof window.weekday === "number"
        && Number.isInteger(window.weekday);
      const weekdayIsAllowed = weekdayIsInteger
        && window.weekday >= 0 && window.weekday <= 6;
      const openingMinuteIsInteger = typeof window.open === "number"
        && Number.isInteger(window.open);
      const openingIsAllowed = openingMinuteIsInteger
        && window.open >= 0 && window.open <= 1440;
      const closingMinuteIsInteger = typeof window.close === "number"
        && Number.isInteger(window.close);
      const closingIsAllowed = closingMinuteIsInteger
        && window.close >= 0 && window.close <= 1440;
      const orderedInterval = (window.open as number) < (window.close as number);
      if (!weekdayIsAllowed || !openingIsAllowed || !closingIsAllowed || !orderedInterval) {
        return { error: "BAD_WINDOW", index };
      }
    }
  }
  if (request.holidays.length > 60) return { error: "BAD_HOLIDAY", index: null };
  const holidayDays = new Set<unknown>();
  for (let index = 0; index < request.holidays.length; index++) {
    const day = request.holidays[index];
    const validHoliday = typeof day === "number" && Number.isInteger(day)
      && day >= 0 && day <= 1_000_000;
    const holidayWasAlreadySeen = holidayDays.has(day);
    const holidayRowIsValid = validHoliday && !holidayWasAlreadySeen;
    if (!holidayRowIsValid) {
      return { error: "BAD_HOLIDAY", index };
    }
    holidayDays.add(day);
  }
  if (bookings.length > 200) return { error: "BAD_BOOKING", index: null };
  for (let index = 0; index < bookings.length; index++) {
    const booking = bookings[index];
    const validDay = typeof booking.day === "number" && Number.isInteger(booking.day)
      && booking.day >= 0 && booking.day <= 1_000_000;
    const validStart = typeof booking.start === "number" && Number.isInteger(booking.start)
      && booking.start >= 0 && booking.start <= 1440;
    const validEnd = typeof booking.end === "number" && Number.isInteger(booking.end)
      && booking.end >= 0 && booking.end <= 1440;
    const orderedInterval = (booking.start as number) < (booking.end as number);
    const bookingDoctorIsKnown = doctorKeys.has(booking.key);
    if (!validDay || !validStart || !validEnd || !orderedInterval
      || !bookingDoctorIsKnown) {
      return { error: "BAD_BOOKING", index };
    }
  }
  const preferredKey = typeof preferred === "string" ? preferred.toLowerCase() : "";
  if (preferred && !doctorKeys.has(preferredKey)) {
    return { error: "UNKNOWN_DOCTOR", index: null };
  }
  const requestedDay = request.requested_day as number;
  const nowDay = request.now_day as number;
  const requestedDayIsNotEarlier = requestedDay >= nowDay;
  const requestedDayIsToday = requestedDay === nowDay;
  const requestedDayOffset = requestedDay - nowDay;
  const requestedDayIsTooFarAhead = requestedDayOffset > 8;
  const requestOrderIsValid = requestedDayIsToday
    || (requestedDayIsNotEarlier && !requestedDayIsTooFarAhead);
  if (!requestOrderIsValid) {
    return { error: "BAD_DAY_ORDER", index: null };
  }

  const [duration, buffer] = KINDS[kind as string];
  const horizonEnd = requestedDay + (request.horizon_days as number);
  const latestPermittedDay = requestedDay + 14;
  const lastDay = Math.min(horizonEnd, latestPermittedDay, 1_000_000);
  const slots: { day: number; start: number; end: number; doctor: string; key: string }[] = [];
  for (let day = requestedDay; day <= lastDay; day++) {
    if (holidayDays.has(day)) continue;
    const weekday = day % 7;
    const opening = weekday === 5 ? 600 : weekday === 6 ? 0 : 540;
    const closing = weekday === 5 ? 840 : weekday === 6 ? 0 : 1020;
    const dayHasClinicHours = opening < closing;
    if (!dayHasClinicHours) continue;
    for (const doctor of doctors) {
      const preferenceAllowsDoctor = request.urgent || !preferred
        || doctor.key === preferredKey;
      if (!preferenceAllowsDoctor) continue;
      for (let start = 0; start <= 1435; start += 5) {
        const appointmentEnd = start + duration;
        const reservedEnd = appointmentEnd + buffer;
        const startIsDuringOpening = start >= opening;
        const reservationEndsBeforeClosing = reservedEnd <= closing;
        const appointmentFitsClinicHours = startIsDuringOpening
          && reservationEndsBeforeClosing;
        if (!appointmentFitsClinicHours) continue;
        const startsBeforeLunchEnds = start < 780;
        const endsAfterLunchStarts = reservedEnd > 720;
        const reservationOverlapsLunch = startsBeforeLunchEnds && endsAfterLunchStarts;
        if (reservationOverlapsLunch) continue;
        const meetsMinimumNotice = day !== nowDay
          || start >= (request.now_minute as number) + 60;
        if (!meetsMinimumNotice) continue;
        const fitsDoctorWindow = doctor.windows.some((window) =>
          {
            const weekdayMatches = window.weekday === weekday;
            const appointmentStartsInside = (window.open as number) <= start;
            const reservationEndsInside = reservedEnd <= (window.close as number);
            return weekdayMatches && appointmentStartsInside && reservationEndsInside;
          });
        if (!fitsDoctorWindow) continue;
        const sameDoctorDay = bookings.filter((booking) =>
          booking.day === day && booking.key === doctor.key);
        const doctorHasDailyCapacity = sameDoctorDay.length < 4;
        if (!doctorHasDailyCapacity) continue;
        const conflicts = sameDoctorDay.some((booking) =>
          {
            const appointmentStartsBeforeBookingEnds = start < (booking.end as number);
            const bookingStartsBeforeAppointmentEnds = (booking.start as number) < reservedEnd;
            return appointmentStartsBeforeBookingEnds && bookingStartsBeforeAppointmentEnds;
          });
        if (conflicts) continue;
        slots.push({
          day,
          start,
          end: appointmentEnd,
          doctor: doctor.name as string,
          key: doctor.key,
        });
      }
    }
  }
  slots.sort((left, right) => {
    const dayDifference = left.day - right.day;
    if (dayDifference !== 0) return dayDifference;
    const startDifference = left.start - right.start;
    if (startDifference !== 0) return startDifference;
    return left.key < right.key ? -1 : left.key > right.key ? 1 : 0;
  });
  const selected = slots[0];
  if (!selected) return { error: "NO_SLOT", index: null };
  return {
    day: selected.day,
    start: selected.start,
    end: selected.end,
    doctor: selected.doctor,
    trace: TRACE,
  };
}
