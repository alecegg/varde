import java.util.ArrayList;
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
    private static final List<String> TRACE = List.of("normalised", "validated", "holiday-filter",
            "hours-and-lunch", "notice", "doctor-availability", "daily-cap", "booking-conflicts",
            "urgent-priority", "earliest-grid-slot");
    private static final Map<String, Timing> TIMINGS = Map.of("checkup", new Timing(20, 5),
            "consultation", new Timing(30, 10), "procedure", new Timing(60, 15));
    private static final long[][] OPENINGS = {{540, 1020}, {540, 1020}, {540, 1020}, {540, 1020},
            {540, 1020}, {600, 840}, {0, 0}};

    /** Return the earliest valid appointment or the first validation error. */
    public static Object solution(Request request) {
        Clinic clinic = normalise(request);
        ClinicError error = validate(clinic);
        if (error != null) return error;
        Slot slot = findSlot(clinic);
        if (slot == null) return new ClinicError("NO_SLOT", null);
        return new Appointment(slot.day(), slot.start(), slot.end(), slot.doctor(), TRACE);
    }

    private static Clinic normalise(Request request) {
        String kind = request.kind().strip().toLowerCase(Locale.ROOT);
        String preferred = request.preferredDoctor().strip();
        return new Clinic(request.nowDay(), request.nowMinute(), request.requestedDay(),
                request.horizonDays(), kind, request.urgent(), preferred, nameKey(preferred),
                request.holidays(), normaliseDoctors(request.doctors()),
                normaliseBookings(request.bookings()));
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
            String key = nameKey(booking.doctor());
            normal.add(new NormalBooking(booking.day(), booking.start(), booking.end(), key));
        }
        return normal;
    }

    private static String nameKey(String name) {
        if (name == null) return null;
        String cleaned = name.strip();
        if (cleaned.isEmpty() || !NAME.matcher(cleaned).matches()) return null;
        return cleaned.toLowerCase(Locale.ROOT);
    }

    private static ClinicError validate(Clinic clinic) {
        ClinicError error = checkScalars(clinic);
        if (error != null) return error;
        error = checkDoctors(clinic);
        if (error != null) return error;
        error = checkWindows(clinic);
        if (error != null) return error;
        error = checkHolidays(clinic);
        if (error != null) return error;
        error = checkBookings(clinic);
        if (error != null) return error;
        return checkOrder(clinic);
    }

    private static ClinicError checkScalars(Clinic clinic) {
        boolean daysInRange = clinic.nowDay() >= 0 && clinic.nowDay() <= 1_000_000
                && clinic.requestedDay() >= 0 && clinic.requestedDay() <= 1_000_000;
        boolean timesInRange = clinic.nowMinute() >= 0 && clinic.nowMinute() <= 1439
                && clinic.horizonDays() >= 0 && clinic.horizonDays() <= 14;
        if (daysInRange && timesInRange && TIMINGS.containsKey(clinic.kind())) return null;
        return new ClinicError("BAD_REQUEST", null);
    }

    private static ClinicError checkDoctors(Clinic clinic) {
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

    private static ClinicError checkWindows(Clinic clinic) {
        int index = 0;
        for (NormalDoctor doctor : clinic.doctors()) {
            List<Window> windows = doctor.windows();
            if (windows.size() > 8) return new ClinicError("BAD_WINDOW", index);
            for (Window window : windows) {
                boolean outOfRange = window.weekday() < 0 || window.weekday() > 6
                        || window.open() < 0 || window.open() >= window.close()
                        || window.close() > 1440;
                if (outOfRange) return new ClinicError("BAD_WINDOW", index);
            }
            index++;
        }
        return null;
    }

    private static ClinicError checkHolidays(Clinic clinic) {
        List<Long> holidays = clinic.holidays();
        if (holidays.size() > 60) return new ClinicError("BAD_HOLIDAY", null);
        Set<Long> seen = new HashSet<>();
        for (int index = 0; index < holidays.size(); index++) {
            long day = holidays.get(index);
            if (day < 0 || day > 1_000_000 || !seen.add(day)) {
                return new ClinicError("BAD_HOLIDAY", index);
            }
        }
        return null;
    }

    private static ClinicError checkBookings(Clinic clinic) {
        List<NormalBooking> bookings = clinic.bookings();
        if (bookings.size() > 200) return new ClinicError("BAD_BOOKING", null);
        Set<String> names = new HashSet<>();
        for (NormalDoctor doctor : clinic.doctors()) names.add(doctor.key());
        for (int index = 0; index < bookings.size(); index++) {
            if (!validBooking(bookings.get(index), names)) {
                return new ClinicError("BAD_BOOKING", index);
            }
        }
        return null;
    }

    private static boolean validBooking(NormalBooking booking, Set<String> names) {
        long day = booking.day();
        long start = booking.start();
        long end = booking.end();
        return day >= 0 && day <= 1_000_000 && start >= 0 && start < end && end <= 1440
                && names.contains(booking.key());
    }

    private static ClinicError checkOrder(Clinic clinic) {
        boolean unknownPreferred = !clinic.preferredDoctor().isEmpty()
                && clinic.doctors().stream()
                        .noneMatch(doctor -> doctor.key().equals(clinic.preferredKey()));
        if (unknownPreferred) return new ClinicError("UNKNOWN_DOCTOR", null);
        boolean outOfOrder = clinic.requestedDay() < clinic.nowDay()
                || clinic.requestedDay() > clinic.nowDay() + 8;
        if (outOfOrder) return new ClinicError("BAD_DAY_ORDER", null);
        return null;
    }

    private static Slot findSlot(Clinic clinic) {
        Timing timing = TIMINGS.get(clinic.kind());
        List<NormalDoctor> doctors = eligibleDoctors(clinic);
        for (long day : candidateDays(clinic)) {
            Slot slot = firstSlotOn(clinic, doctors, day, timing.duration(), timing.buffer());
            if (slot != null) return slot;
        }
        return null;
    }

    private static List<NormalDoctor> eligibleDoctors(Clinic clinic) {
        List<NormalDoctor> doctors = new ArrayList<>(clinic.doctors());
        if (!clinic.urgent() && !clinic.preferredDoctor().isEmpty()) {
            doctors.removeIf(doctor -> !doctor.key().equals(clinic.preferredKey()));
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
            if (!holidays.contains(day)) days.add(day);
        }
        return days;
    }

    private static Slot firstSlotOn(Clinic clinic, List<NormalDoctor> doctors, long day,
            long duration, long buffer) {
        Map<String, List<NormalBooking>> daily = dailyBookings(clinic, day);
        long weekday = day % 7;
        for (long start = 0; start < 1440; start += 5) {
            long reservedEnd = start + duration + buffer;
            for (NormalDoctor doctor : doctors) {
                List<NormalBooking> taken = daily.getOrDefault(doctor.key(), List.of());
                if (withinHours(doctor, weekday, start, reservedEnd)
                        && scheduleClear(clinic, day, start, reservedEnd, taken)) {
                    return new Slot(day, start, start + duration, doctor.name());
                }
            }
        }
        return null;
    }

    private static Map<String, List<NormalBooking>> dailyBookings(Clinic clinic, long day) {
        Map<String, List<NormalBooking>> daily = new HashMap<>();
        for (NormalBooking booking : clinic.bookings()) {
            if (booking.day() != day) continue;
            daily.computeIfAbsent(booking.key(), key -> new ArrayList<>()).add(booking);
        }
        return daily;
    }

    private static boolean withinHours(NormalDoctor doctor, long weekday, long start,
            long reservedEnd) {
        long[] opening = OPENINGS[(int) weekday];
        boolean inWindow = false;
        for (Window window : doctor.windows()) {
            boolean matches = window.weekday() == weekday && window.open() <= start
                    && reservedEnd <= window.close();
            inWindow = inWindow || matches;
        }
        boolean inOpening = opening[0] <= start && reservedEnd <= opening[1];
        boolean missesLunch = !(start < 780 && reservedEnd > 720);
        return inWindow && inOpening && missesLunch;
    }

    private static boolean scheduleClear(Clinic clinic, long day, long start, long reservedEnd,
            List<NormalBooking> taken) {
        boolean noticed = day > clinic.nowDay() || start >= clinic.nowMinute() + 60;
        boolean underCap = taken.size() < 4;
        boolean noOverlap = true;
        for (NormalBooking booking : taken) {
            noOverlap = noOverlap && (start >= booking.end() || reservedEnd <= booking.start());
        }
        return noticed && underCap && noOverlap;
    }
}
