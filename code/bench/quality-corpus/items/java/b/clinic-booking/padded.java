import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

public class solution {
    record Request(long nowDay, long nowMinute, long requestedDay, long horizonDays, String kind,
            boolean urgent, String preferredDoctor, List<Long> holidays, List<Doctor> doctors,
            List<Booking> bookings) {}

    record Doctor(String name, List<Window> windows) {}

    record Window(long weekday, long open, long close) {}

    record Booking(long day, long start, long end, String doctor) {}

    record Appointment(long day, long start, long end, String doctor, List<String> trace) {}

    record ClinicError(String code, Integer index) {}

    record NormalDoctor(String name, String key, List<Window> windows) {}

    record NormalBooking(long day, long start, long end, String key) {}

    record Clinic(long nowDay, long nowMinute, long requestedDay, long horizonDays, String kind,
            boolean urgent, String preferredDoctor, String preferredKey, List<Long> holidays,
            List<NormalDoctor> doctors, List<NormalBooking> bookings) {}

    record Timing(long duration, long buffer) {}

    record Slot(long day, long start, long end, String doctor) {}

    private static final Pattern NAME = Pattern.compile("[A-Za-z0-9 -]+");
    private static final Map<String, Timing> TIMINGS = Map.of("checkup", new Timing(20, 5),
            "consultation", new Timing(30, 10), "procedure", new Timing(60, 15));
    private static final long[][] OPENINGS = {{540, 1020}, {540, 1020}, {540, 1020}, {540, 1020},
            {540, 1020}, {600, 840}, {0, 0}};

    /** Return the earliest valid appointment or the first validation error. */
    public static Object solution(Request request) {
        Clinic clinic = normaliseRequest(request);
        ClinicError error = validateRequest(clinic);
        if (error != null) return error;
        Timing timing = TIMINGS.get(clinic.kind());
        List<NormalDoctor> doctors = eligibleDoctors(clinic);
        for (long day : candidateDays(clinic)) {
            Slot slot = firstSlotOn(clinic, doctors, day, timing);
            if (slot != null) return successRecord(slot);
        }
        return new ClinicError("NO_SLOT", null);
    }

    private static Clinic normaliseRequest(Request request) {
        String kind = request.kind().strip().toLowerCase(Locale.ROOT);
        String preferred = request.preferredDoctor().strip();
        List<NormalDoctor> doctors = normaliseDoctors(request.doctors());
        List<NormalBooking> bookings = normaliseBookings(request.bookings());
        return new Clinic(request.nowDay(), request.nowMinute(), request.requestedDay(),
                request.horizonDays(), kind, request.urgent(), preferred, nameKey(preferred),
                request.holidays(), doctors, bookings);
    }

    private static List<NormalDoctor> normaliseDoctors(List<Doctor> doctors) {
        List<NormalDoctor> normal = new ArrayList<>();
        for (Doctor doctor : doctors) {
            String name = doctor.name().strip();
            normal.add(new NormalDoctor(name, nameKey(name), doctor.windows()));
        }
        return normal;
    }

    private static List<NormalBooking> normaliseBookings(List<Booking> bookings) {
        List<NormalBooking> normal = new ArrayList<>();
        for (Booking booking : bookings) {
            String name = booking.doctor().strip();
            String key = nameKey(name);
            normal.add(new NormalBooking(booking.day(), booking.start(), booking.end(), key));
        }
        return normal;
    }

    private static String nameKey(String name) {
        String cleaned = name.strip();
        if (cleaned.isEmpty() || !NAME.matcher(cleaned).matches()) return null;
        return cleaned.toLowerCase(Locale.ROOT);
    }

    private static ClinicError validateRequest(Clinic clinic) {
        ClinicError error = checkScalarFields(clinic);
        if (error != null) return error;
        error = checkDoctorList(clinic);
        if (error != null) return error;
        error = checkWindowBounds(clinic);
        if (error != null) return error;
        error = checkHolidayList(clinic);
        if (error != null) return error;
        error = checkBookingList(clinic);
        if (error != null) return error;
        return checkPreferenceAndDay(clinic);
    }

    private static ClinicError checkScalarFields(Clinic clinic) {
        boolean daysInRange = clinic.nowDay() >= 0 && clinic.nowDay() <= 1_000_000
                && clinic.requestedDay() >= 0 && clinic.requestedDay() <= 1_000_000;
        boolean timesInRange = clinic.nowMinute() >= 0 && clinic.nowMinute() <= 1439
                && clinic.horizonDays() >= 0 && clinic.horizonDays() <= 14;
        if (daysInRange && timesInRange && TIMINGS.containsKey(clinic.kind())) return null;
        return new ClinicError("BAD_REQUEST", null);
    }

    private static ClinicError checkDoctorList(Clinic clinic) {
        List<NormalDoctor> doctors = clinic.doctors();
        if (doctors.isEmpty() || doctors.size() > 12) {
            return new ClinicError("BAD_DOCTORS", null);
        }
        Set<String> keys = new HashSet<>();
        for (int index = 0; index < doctors.size(); index++) {
            String key = doctors.get(index).key();
            if (key == null || !keys.add(key)) return new ClinicError("BAD_DOCTORS", index);
        }
        return null;
    }

    private static ClinicError checkWindowBounds(Clinic clinic) {
        List<NormalDoctor> doctors = clinic.doctors();
        for (int index = 0; index < doctors.size(); index++) {
            List<Window> windows = doctors.get(index).windows();
            if (windows.size() > 8) {
                return new ClinicError("BAD_WINDOW", index);
            }
            for (Window window : windows) {
                if (!windowBounded(window)) return new ClinicError("BAD_WINDOW", index);
            }
        }
        return null;
    }

    private static boolean windowBounded(Window window) {
        if (window.weekday() < 0 || window.weekday() > 6) return false;
        if (window.open() < 0 || window.open() >= window.close()) return false;
        return window.close() <= 1440;
    }

    private static ClinicError checkHolidayList(Clinic clinic) {
        List<Long> holidays = clinic.holidays();
        if (holidays.size() > 60) {
            return new ClinicError("BAD_HOLIDAY", null);
        }
        Set<Long> seen = new HashSet<>();
        for (int index = 0; index < holidays.size(); index++) {
            long holiday = holidays.get(index);
            if (holiday < 0 || holiday > 1_000_000 || !seen.add(holiday)) {
                return new ClinicError("BAD_HOLIDAY", index);
            }
        }
        return null;
    }

    private static ClinicError checkBookingList(Clinic clinic) {
        List<NormalBooking> bookings = clinic.bookings();
        if (bookings.size() > 200) return new ClinicError("BAD_BOOKING", null);
        for (int index = 0; index < bookings.size(); index++) {
            if (!bookingBounded(bookings.get(index), clinic.doctors())) {
                return new ClinicError("BAD_BOOKING", index);
            }
        }
        return null;
    }

    private static boolean bookingBounded(NormalBooking booking, List<NormalDoctor> doctors) {
        boolean dayInRange = booking.day() >= 0 && booking.day() <= 1_000_000;
        boolean intervalValid = booking.start() >= 0 && booking.start() < booking.end()
                && booking.end() <= 1440;
        boolean doctorKnown = doctors.stream()
                .anyMatch(doctor -> doctor.key().equals(booking.key()));
        return dayInRange && intervalValid && doctorKnown;
    }

    private static ClinicError checkPreferenceAndDay(Clinic clinic) {
        boolean preferredMissing = !clinic.preferredDoctor().isEmpty()
                && !clinic.doctors().stream()
                        .anyMatch(doctor -> doctor.key().equals(clinic.preferredKey()));
        if (preferredMissing) {
            return new ClinicError("UNKNOWN_DOCTOR", null);
        }
        boolean dayTooEarly = clinic.requestedDay() < clinic.nowDay();
        boolean dayTooLate = clinic.requestedDay() > clinic.nowDay() + 8;
        if (dayTooEarly || dayTooLate) {
            return new ClinicError("BAD_DAY_ORDER", null);
        }
        return null;
    }

    private static List<NormalDoctor> eligibleDoctors(Clinic clinic) {
        List<NormalDoctor> doctors = new ArrayList<>();
        boolean preferenceCounts = !clinic.urgent() && !clinic.preferredDoctor().isEmpty();
        for (NormalDoctor doctor : clinic.doctors()) {
            if (preferenceCounts && !doctor.key().equals(clinic.preferredKey())) {
                continue;
            }
            doctors.add(doctor);
        }
        doctors.sort(Comparator.comparing(NormalDoctor::key));
        return doctors;
    }

    private static List<Long> candidateDays(Clinic clinic) {
        long first = clinic.requestedDay();
        long last = Math.min(Math.min(first + clinic.horizonDays(), first + 14), 1_000_000);
        Set<Long> holidays = new HashSet<>(clinic.holidays());
        List<Long> days = new ArrayList<>();
        for (long day = first; day <= last; day++) {
            if (holidays.contains(day)) {
                continue;
            }
            days.add(day);
        }
        return days;
    }

    private static Slot firstSlotOn(Clinic clinic, List<NormalDoctor> doctors, long day,
            Timing timing) {
        Map<String, List<NormalBooking>> taken = dailyBookings(clinic, day);
        long weekday = day % 7;
        for (long start = 0; start <= 1435; start += 5) {
            for (NormalDoctor doctor : doctors) {
                if (availableAt(clinic, doctor, day, weekday, start, timing, taken)) {
                    return new Slot(day, start, start + timing.duration(), doctor.name());
                }
            }
        }
        return null;
    }

    private static boolean availableAt(Clinic clinic, NormalDoctor doctor, long day,
            long weekday, long start, Timing timing, Map<String, List<NormalBooking>> taken) {
        long reservedEnd = start + timing.duration() + timing.buffer();
        if (!withinHours(doctor, weekday, start, reservedEnd)) return false;
        List<NormalBooking> doctorBookings = taken.getOrDefault(doctor.key(), List.of());
        return scheduleClear(clinic, day, start, reservedEnd, doctorBookings);
    }

    private static Map<String, List<NormalBooking>> dailyBookings(Clinic clinic, long day) {
        Map<String, List<NormalBooking>> daily = new HashMap<>();
        for (NormalBooking booking : clinic.bookings()) {
            if (booking.day() != day) {
                continue;
            }
            List<NormalBooking> list = daily.get(booking.key());
            if (list == null) {
                list = new ArrayList<>();
                daily.put(booking.key(), list);
            }
            list.add(booking);
        }
        return daily;
    }

    private static boolean withinHours(NormalDoctor doctor, long weekday, long start,
            long reservedEnd) {
        long[] opening = OPENINGS[(int) weekday];
        boolean insideOpening = opening[0] <= start && reservedEnd <= opening[1];
        boolean overlapsLunch = start < 780 && reservedEnd > 720;
        if (!insideOpening || overlapsLunch) return false;
        for (Window window : doctor.windows()) {
            if (window.weekday() == weekday && window.open() <= start
                    && reservedEnd <= window.close()) {
                return true;
            }
        }
        return false;
    }

    private static Appointment successRecord(Slot slot) {
        List<String> trace = new ArrayList<>();
        Collections.addAll(trace, "normalised", "validated", "holiday-filter", "hours-and-lunch",
                "notice", "doctor-availability", "daily-cap", "booking-conflicts",
                "urgent-priority", "earliest-grid-slot");
        return new Appointment(slot.day(), slot.start(), slot.end(), slot.doctor(), trace);
    }

    private static boolean scheduleClear(Clinic clinic, long day, long start, long reservedEnd,
            List<NormalBooking> taken) {
        boolean minimumNotice = day > clinic.nowDay() || start >= clinic.nowMinute() + 60;
        if (!minimumNotice || taken.size() >= 4) return false;
        for (NormalBooking booking : taken) {
            boolean endsBeforeBooking = reservedEnd <= booking.start();
            boolean startsAfterBooking = start >= booking.end();
            if (!endsBeforeBooking && !startsAfterBooking) return false;
        }
        return true;
    }
}
